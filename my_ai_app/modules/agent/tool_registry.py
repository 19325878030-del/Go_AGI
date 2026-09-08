# my_ai_app/modules/agent/tool_registry.py
# 工具元数据注册表：只读 manifest.json，不 import 任何实现代码。
# 大模型感知的只有这里的 Schema；实现代码由 tool_loader 按需加载。
#
# manifest.json 契约（以 weather 包为例）：
# {
#   "package": "weather",          # 包名（=目录名）
#   "version": "1.0.0",            # 语义化版本，加载器据此判断缓存是否过期
#   "entry_module": "implementation.py",   # 实现文件（相对包目录）
#   "tools": [
#     {
#       "name": "get_weather",      # 暴露给模型的工具名（全局唯一）
#       "description": "获取当前天气信息",
#       "entry_function": "get_current_weather",  # 实现文件里的函数名
#       "parameters": { ...JSON Schema... }      # 与模型约定的一致
#     }
#   ],
#   "fallback_helper": {           # 可选：包内辅助函数（如搜索结果判空）
#     "tool": "web_search",
#     "entry_function": "has_real_results"
#   },
#   "sha256": "..."                # 可选：implementation.py 的哈希，防篡改校验
# }
import json
from pathlib import Path
from typing import Dict, Optional

# 工具包根目录：my_ai_app/data/agent_tools/
# （本文件位于 my_ai_app/modules/agent/ 下，向上三级到应用根）
TOOL_PACKAGES_DIR = Path(__file__).parent.parent.parent / "data" / "agent_tools"

# manifest 必填字段
REQUIRED_FIELDS = ("package", "version", "entry_module", "tools")


class ToolRegistry:
    """
    工具元数据注册表。

    启动时扫描 TOOL_PACKAGES_DIR 下所有包的 manifest.json，
    构建工具名 -> 元数据的索引。坏包跳过并告警，不影响其他包。
    """

    def __init__(self, packages_dir: Path = None):
        self.packages_dir = Path(packages_dir) if packages_dir else TOOL_PACKAGES_DIR
        # {工具名: {package, version, entry_module, entry_function, description, parameters}}
        self._tools: Dict[str, Dict] = {}
        # {包名: manifest原始内容}
        self._packages: Dict[str, Dict] = {}
        self.reload()

    def reload(self):
        """重新扫描所有 manifest（为将来热更新/云端下载后刷新留口）"""
        self._tools.clear()
        self._packages.clear()

        if not self.packages_dir.is_dir():
            print(f"⚠️ 工具包目录不存在: {self.packages_dir}")
            return

        for pkg_dir in sorted(self.packages_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            manifest_path = pkg_dir / "manifest.json"
            if not manifest_path.is_file():
                continue

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                print(f"⚠️ 跳过坏包 {pkg_dir.name}: manifest 解析失败 ({e})")
                continue

            missing = [f for f in REQUIRED_FIELDS if f not in manifest]
            if missing:
                print(f"⚠️ 跳过坏包 {pkg_dir.name}: manifest 缺少字段 {missing}")
                continue
            if not isinstance(manifest["tools"], list) or not manifest["tools"]:
                print(f"⚠️ 跳过坏包 {pkg_dir.name}: tools 为空")
                continue

            for tool in manifest["tools"]:
                name = tool.get("name")
                if not name:
                    print(f"⚠️ 跳过 {pkg_dir.name} 中无名工具")
                    continue
                if name in self._tools:
                    print(f"⚠️ 工具名冲突，后者被忽略: {name} "
                          f"({self._tools[name]['package']} -> {pkg_dir.name})")
                    continue

                self._tools[name] = {
                    "package": pkg_dir.name,
                    "package_dir": str(pkg_dir),
                    "version": manifest["version"],
                    "entry_module": manifest["entry_module"],
                    "entry_function": tool.get("entry_function", name),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                }

            self._packages[pkg_dir.name] = manifest

    def get_schemas(self) -> Dict[str, Dict]:
        """
        返回全部工具的 Schema，供构建系统提示：
        {工具名: {"description": ..., "parameters": ...}}
        """
        return {
            name: {"description": info["description"], "parameters": info["parameters"]}
            for name, info in self._tools.items()
        }

    def get_tool_info(self, tool_name: str) -> Optional[Dict]:
        """查某个工具由哪个包/入口函数提供；未知工具返回 None"""
        return self._tools.get(tool_name)

    def get_fallback_helper(self) -> Optional[Dict]:
        """
        取"搜索结果判空"辅助函数的定位信息（web_search 包在 manifest 里声明）。
        Agent 用它决定空结果兜底流程，避免硬编码依赖具体包。
        """
        for manifest in self._packages.values():
            helper = manifest.get("fallback_helper")
            if helper and helper.get("tool") in self._tools:
                info = dict(self._tools[helper["tool"]])
                info["entry_function"] = helper["entry_function"]
                return info
        return None

    @property
    def tool_names(self):
        return list(self._tools.keys())
