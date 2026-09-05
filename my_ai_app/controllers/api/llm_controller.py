# my_ai_app/controllers/api/llm_controller.py
"""
接口层 —— 外部大模型连接配置接口（Flask Blueprint）。

不预设任何服务商/模型，连接信息（base_url / api_key / model）由操作者手动填写。

只做三件事（与 auth_controller 相同的分层约定）：
    1. 接收前端参数
    2. 调用 services 层（llm_provider_service.py）
    3. 返回 JSON；@log_api 自动记录入参/出参

接口清单：
    GET    /api/llm/providers        -> 当前用户已保存配置（api_key脱敏）
    POST   /api/llm/providers        -> 新增配置 {name?, base_url, api_key, model}
    DELETE /api/llm/providers/<id>   -> 删除配置
    POST   /api/llm/test             -> 连通性测试 {base_url, api_key, model}

/api/llm/test 的入参日志会记到 api_logs —— log_service 记录的是前端提交的原文，
所以测试通过后建议尽快保存；日志文件在本地+TiDB，不要把它分享给别人。
"""
from flask import Blueprint, request, session

from .auth_controller import login_required, log_api
from .response import ok, err
from services import llm_provider_service

llm_bp = Blueprint('llm', __name__, url_prefix='/api/llm')


@llm_bp.route('/providers', methods=['GET'])
@login_required
@log_api('/api/llm/providers')
def list_providers():
    """当前用户的配置列表（api_key 已脱敏，如 sk****x9y2）"""
    providers = llm_provider_service.list_providers(session['user_id'])
    return ok({'providers': providers})


@llm_bp.route('/providers', methods=['POST'])
@login_required
@log_api('/api/llm/providers')
def add_provider():
    """新增配置。前端一般会先调 /test 验证再保存，但后端不强制。"""
    data = request.get_json(silent=True) or {}
    success, msg = llm_provider_service.add_provider(
        user_id=session['user_id'],
        name=data.get('name', ''),
        base_url=data.get('base_url', ''),
        api_key=data.get('api_key', ''),
        model=data.get('model', ''),
    )
    if not success:
        return err(msg, 400)
    return ok({})


@llm_bp.route('/providers/<int:provider_id>', methods=['DELETE'])
@login_required
@log_api('/api/llm/providers/<id>')
def delete_provider(provider_id):
    """删除配置（只能删本人的，service 层带 user_id 条件）"""
    success, msg = llm_provider_service.delete_provider(provider_id, session['user_id'])
    if not success:
        return err(msg, 404)
    return ok({})


@llm_bp.route('/test', methods=['POST'])
@login_required
@log_api('/api/llm/test')
def test_provider():
    """连通性测试：发一条最小对话请求验证 base_url + api_key + model 是否可用"""
    data = request.get_json(silent=True) or {}
    base_url = data.get('base_url', '')
    api_key = data.get('api_key', '')
    model = data.get('model', '')

    if not all([base_url, api_key, model]):
        return err('URL、API Key、模型均不能为空', 400)

    success, msg = llm_provider_service.test_provider(base_url, api_key, model)
    # 连通性结果是"结果载荷"而非请求错误：即使连不上也返回 200 code:0，前端看 data.ok
    return ok({'ok': success, 'message': msg})
