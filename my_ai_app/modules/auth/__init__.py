# my_ai_app/modules/auth/__init__.py
"""
登录注册模块。

目录结构：
    api/      接口层 —— 前端收集的参数（schemas.py）+ Flask 接口入口（auth_api.py）
    service/  服务层 —— 检测/校验逻辑（auth_service.py）+ 入参出参记录（log_service.py）

对外暴露：auth_bp（Flask 蓝图）、login_required（登录保护）、log_api（接口日志装饰器）。
"""
from .api.auth_api import auth_bp, login_required, log_api

__all__ = ['auth_bp', 'login_required', 'log_api']
