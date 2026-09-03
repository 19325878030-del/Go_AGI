# controllers/ — 接口层（只做 收请求 → 调services → 返回JSON）
from .api.auth_controller import auth_bp, login_required

__all__ = ['auth_bp', 'login_required']
