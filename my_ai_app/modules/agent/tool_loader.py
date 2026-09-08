# my_ai_app/modules/agent/tool_loader.py
# 工具按需动态加载器：模型发出调用指令后，才 import 对应包的实现代码。
# 配合 tool_registry（只管元数据）实现"元数据与实现分离"：
# Agent 启动只扫 manifest（毫秒级），实现代码首次调用才进内存。
import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Dict, Callable, Optional, Tuple

from my_ai_app.modules.agent.tool_registry import ToolRegistry


class RemoteFetcher:
    """
    云端工具包拉取（占位，暂不实现）。

    将来实现方式（HTTPS 下载 → 签名/哈希校验 → 落盘 tool_packages 目录 → 交回 loader 加载）：
    1. GET {REMOTE_BASE}/{package}/{version}/package.zip
    2. 校验 sha256 / 数字签名
    3. 解压到 data/agent_tools/{package}/，写回 manifest
    4. registry.reload() 后正常走本地加载
    """

    REMOTE_BASE = None  # 云端地址，配置后才启用拉取

    @staticmethod
    def fetch(package: str, version: str) -> Path:
        raise NotImplementedError("云端拉取暂未实现：当前仅支持本地 data/agent_tools/ 下的工具包")


class ToolLoader:
    """
    工具函数加载器。

    get_function(tool_name) 首次调用时用 importlib 导入该包的
    implementation.py 并取入口函数；同包工具共享一次模块导入，
    结果按 (包名, 版本) 缓存，manifest 版本变化后自动重新加载。
    """

    def __init__(self, registry: ToolRegistry = None):
        self.registry = registry if registry is not None else ToolRegistry()
        # {包名: (版本, module)} —— 模块级缓存，同包多工具只导入一次
        self._module_cache: Dict[str, Tuple[str, object]] = {}
        # {工具名: (版本, function)} —— 工具级缓存，命中直接返回
        self._function_cache: Dict[str, Tuple[str, Callable]] = {}

    def get_function(self, tool_name: str) -> Optional[Callable]:
        """按工具名取入口函数；未知工具或实现缺失返回 None"""
        info = self.registry.get_tool_info(tool_name)
        if info is None:
            return None

        # 工具级缓存命中且版本未变，直接返回
        cached = self._function_cache.get(tool_name)
        if cached and cached[0] == info["version"]:
            return cached[1]

        module = self._load_module(info)
        if module is None:
            return None

        func = getattr(module, info["entry_function"], None)
        if func is None or not callable(func):
            print(f"⚠️ 包 {info['package']} 中没有入口函数 {info['entry_function']}（工具 {tool_name}）")
            return None

        self._function_cache[tool_name] = (info["version"], func)
        return func

    def get_helper_function(self, helper_info: Dict) -> Optional[Callable]:
        """加载 manifest 里 fallback_helper 声明的辅助函数（如 has_real_results）"""
        module = self._load_module(helper_info)
        if module is None:
            return None
        func = getattr(module, helper_info["entry_function"], None)
        return func if callable(func) else None

    def _load_module(self, info: Dict):
        """导入包实现模块（带缓存与版本比对）；失败返回 None"""
        package = info["package"]

        # 模块级缓存命中且版本一致，直接复用
        cached = self._module_cache.get(package)
        if cached and cached[0] == info["version"]:
            return cached[1]

        # 本地没有该包时的云端拉取点（当前占位，必抛 NotImplementedError）
        pkg_dir = Path(info["package_dir"])
        impl_path = pkg_dir / info["entry_module"]
        if not impl_path.is_file():
            if RemoteFetcher.REMOTE_BASE:
                RemoteFetcher.fetch(package, info["version"])
            else:
                print(f"⚠️ 工具包实现文件不存在: {impl_path}")
                return None

        if not self._verify_sha256(pkg_dir, impl_path):
            return None

        module = self._import_from_file(package, impl_path)
        if module is None:
            return None

        self._module_cache[package] = (info["version"], module)
        return module

    def _import_from_file(self, package: str, impl_path: Path):
        """用 importlib 从指定文件导入模块（唯一模块名避免 sys.modules 冲突）"""
        module_name = f"agent_tool_{package}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, impl_path)
            module = importlib.util.module_from_spec(spec)
            # 注册进 sys.modules：实现文件里的包内全局单例（如 search_tool）才能稳定复用
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            sys.modules.pop(module_name, None)
            print(f"⚠️ 导入工具包 {package} 失败: {e}")
            return None

    @staticmethod
    def _verify_sha256(pkg_dir: Path, impl_path: Path) -> bool:
        """
        校验实现文件哈希。manifest 里有 sha256 字段才校验，没有则跳过
        （本地自带的包无签名；将来云端包应写入此字段防篡改）。
        """
        manifest_path = pkg_dir / "manifest.json"
        try:
            import json
            expected = json.loads(manifest_path.read_text(encoding="utf-8")).get("sha256")
            if not expected:
                return True
            actual = hashlib.sha256(impl_path.read_bytes()).hexdigest()
            if actual != expected:
                print(f"⚠️ {pkg_dir.name} 哈希校验失败，拒绝加载")
                return False
            return True
        except (OSError, ValueError) as e:
            print(f"⚠️ {pkg_dir.name} 哈希校验出错: {e}")
            return False

    @property
    def loaded_packages(self):
        """当前已加载进内存的包（用于验证惰性加载）"""
        return list(self._module_cache.keys())
