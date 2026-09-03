# my_ai_app/controllers/api/schemas.py
"""
接口层 —— 前端收集的参数模型（入参）。

这里只描述「前端会传哪些参数」，不做业务校验；
业务校验逻辑（用户名/密码检测）统一放在 services/user_service.py。

前后端约定（以 simple_app.py 前端为准）：
    注册 / 登录 前端都只提交两个字段：
        username  用户名（至少 2 个字符）
        password  密码  （至少 6 位）
"""
from dataclasses import dataclass, asdict


@dataclass
class RegisterParams:
    """POST /api/auth/register —— 前端注册接口收集的参数。"""
    username: str = ""
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "RegisterParams":
        """从前端 JSON 体构造参数对象（缺失字段给默认空串）。"""
        data = data or {}
        return cls(
            username=(data.get("username") or "").strip(),
            password=data.get("password") or "",
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LoginParams:
    """POST /api/auth/login —— 前端登录接口收集的参数。"""
    username: str = ""
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "LoginParams":
        """从前端 JSON 体构造参数对象（缺失字段给默认空串）。"""
        data = data or {}
        return cls(
            username=(data.get("username") or "").strip(),
            password=data.get("password") or "",
        )

    def to_dict(self) -> dict:
        return asdict(self)
