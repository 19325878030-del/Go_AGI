# my_ai_app/controllers/api/conversation_controller.py
"""
接口层 —— 会话历史接口（Flask Blueprint）。

接口清单：
    GET    /api/conversation/list            → 当前用户的会话列表（按updated_at倒序）
    GET    /api/conversation/detail?id=<id>  → 会话详情（含title + messages[]）
    POST   /api/conversation/create          → 新建空会话（返回新会话对象）
"""
from flask import Blueprint, request, session

from .auth_controller import login_required, log_api
from .response import ok, err
from services import conversation_service

conv_bp = Blueprint('conversation', __name__, url_prefix='/api/conversation')


@conv_bp.route('/list', methods=['GET'])
@login_required
@log_api('/api/conversation/list')
def list_conversations():
    """当前用户的所有会话（按 updated_at 倒序，最多 50 条）"""
    conversations = conversation_service.list_conversations(session['user_id'])
    return ok({'conversations': conversations})


@conv_bp.route('/detail', methods=['GET'])
@login_required
@log_api('/api/conversation/detail')
def conversation_detail():
    """会话详情：含 title + messages（按时间正序排列）"""
    conv_id = request.args.get('id', type=int)
    if not conv_id:
        return err('缺少会话 ID', 400)

    detail = conversation_service.get_conversation_detail(conv_id, session['user_id'])
    if detail is None:
        return err('会话不存在', 404)

    return ok({
        'id': detail['id'],
        'title': detail['title'],
        'messages': detail['messages'],
        'created_at': detail['created_at'],
        'updated_at': detail['updated_at'],
    })


@conv_bp.route('/create', methods=['POST'])
@login_required
@log_api('/api/conversation/create')
def create_conversation():
    """新建空会话，前端发送首条消息前调用"""
    conv = conversation_service.create_conversation(session['user_id'])
    return ok({'conversation': conv})