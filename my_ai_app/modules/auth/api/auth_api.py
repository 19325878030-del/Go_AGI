# my_ai_app/modules/auth/api/auth_api.py
"""
接口层 —— 登录注册接口入口（Flask Blueprint）。

只做三件事：
    1. 接收前端收集的参数（schemas.py）
    2. 调用 service 层的检测/校验逻辑（auth_service.py）
    3. 返回 JSON；并自动记录每个接口的 入参/出参（log_service.py）

接口清单（与 simple_app.py 前端约定一致）：
    POST /api/auth/register   {username, password}
    POST /api/auth/login      {username, password}
    POST /api/auth/logout
    GET  /api/auth/me         -> {"user": {"id","username"} | null}
"""
import time
from functools import wraps

from flask import Blueprint, request, jsonify, session

from .schemas import RegisterParams, LoginParams
from ..service import auth_service
from ..service import log_service

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def login_required(f):
    """登录保护装饰器：未登录返回 401（前端收到 401 会自动弹登录框）。"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('user_id') is None:
            return jsonify({'error': '请先登录', 'code': 'UNAUTHORIZED'}), 401
        return f(*args, **kwargs)
    return wrapper


def log_api(interface):
    """
    入参/出参记录装饰器。

    每次请求自动记录：是哪一个接口（interface + method）、入参是什么、
    出参是什么、状态码、耗时、登录用户，供前后端联调时定位问题。
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            start = time.time()
            method = request.method

            # 入参：POST 取 JSON 体，GET 取 query 参数
            if method in ('POST', 'PUT', 'PATCH'):
                request_params = request.get_json(silent=True) or {}
            else:
                request_params = dict(request.args)

            result = f(*args, **kwargs)

            # 出参：兼容 jsonify() 与 (jsonify(), status_code) 两种返回
            status_code, resp = 200, result
            if isinstance(result, tuple):
                resp = result[0]
                if len(result) > 1 and isinstance(result[1], int):
                    status_code = result[1]

            response_params = {}
            if hasattr(resp, 'get_json'):
                try:
                    response_params = resp.get_json(silent=True) or {}
                except Exception:
                    pass

            duration_ms = int((time.time() - start) * 1000)
            try:
                log_service.log_request(
                    interface=interface,
                    method=method,
                    request_params=request_params,
                    response_params=response_params,
                    status_code=status_code,
                    user_id=session.get('user_id'),
                    username=session.get('username'),
                    duration_ms=duration_ms,
                )
            except Exception as e:  # 日志失败绝不能影响业务
                print(f"[api_log] 记录日志失败: {e}")

            return result
        return wrapper
    return decorator


@auth_bp.route('/register', methods=['POST'])
@log_api('/api/auth/register')
def register():
    """注册：前端收集 {username, password} -> 检测 -> 保存数据库 -> 注册即登录。"""
    data = request.get_json(silent=True) or {}
    params = RegisterParams.from_dict(data)

    ok, msg, user = auth_service.create_user(params.username, params.password)
    if not ok:
        return jsonify({'error': msg}), 400

    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'message': '注册成功', 'username': user['username']})


@auth_bp.route('/login', methods=['POST'])
@log_api('/api/auth/login')
def login():
    """登录：前端收集 {username, password} -> 检测 -> 校验 -> 写登录态。"""
    data = request.get_json(silent=True) or {}
    params = LoginParams.from_dict(data)

    ok, msg, user = auth_service.login(params.username, params.password)
    if not ok:
        return jsonify({'error': msg}), 401

    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'message': '登录成功', 'username': user['username']})


@auth_bp.route('/logout', methods=['POST'])
@log_api('/api/auth/logout')
def logout():
    """退出登录：清除 session。"""
    session.clear()
    return jsonify({'message': '已退出登录'})


@auth_bp.route('/me', methods=['GET'])
@log_api('/api/auth/me')
def me():
    """前端页面刷新后恢复登录状态：返回当前用户或 null。"""
    uid = session.get('user_id')
    user = auth_service.get_user_by_id(uid) if uid else None
    if uid and user is None:
        session.clear()
    return jsonify({'user': user})
