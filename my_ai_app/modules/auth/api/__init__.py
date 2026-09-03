# my_ai_app/modules/auth/api/__init__.py
"""接口层：前端收集的参数模型 + Flask 接口入口。"""
from .schemas import RegisterParams, LoginParams
from .auth_api import auth_bp, login_required, log_api

__all__ = ['RegisterParams', 'LoginParams', 'auth_bp', 'login_required', 'log_api']
