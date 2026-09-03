# my_ai_app/modules/auth/service/__init__.py
"""服务层：检测/校验逻辑（auth_service）+ 入参出参记录（log_service）。"""
from . import auth_service
from . import log_service
from .auth_service import (
    init_db, validate_params, create_user, verify_user, login, get_user_by_id,
)
from .log_service import init_log_db, log_request, query_logs

__all__ = [
    'auth_service', 'log_service',
    'init_db', 'validate_params', 'create_user', 'verify_user', 'login', 'get_user_by_id',
    'init_log_db', 'log_request', 'query_logs',
]
