# controllers/ — 接口层（只做 收请求 → 调services → 返回JSON）
from .api.auth_controller import auth_bp, login_required
from .api.llm_controller import llm_bp
from .api.conversation_controller import conv_bp

__all__ = ['auth_bp', 'llm_bp', 'conv_bp', 'login_required']
