# controllers/ — 接口层（Controller）

> **当前状态：待实现。** 本目录暂无 Python 代码，只有本说明文档。
> 请后续开发者按本文档实现 `auth_controller.py`（可参考文末的参考实现）。
>
> 职责边界：只做「接收 HTTP 请求 → 调用 services 层 → 返回 JSON」。
> 不写业务规则、不直接操作数据库、不依赖前端。

## 目录规划

| 文件 | 职责 | 状态 |
|---|---|---|
| `__init__.py` | 导出 `auth_bp` 与 `login_required` | 待实现 |
| `auth_controller.py` | 登录注册接口（Flask Blueprint） | 待实现 |
| `chat_controller.py`（将来） | 把 `simple_app.py` 中的 `/api/chat`、`/api/models` 迁入 | 规划中 |

## auth_controller.py 接口契约

蓝图：`auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')`

| 方法 | 路径 | 请求体 | 成功响应 | 失败响应 |
|---|---|---|---|---|
| POST | `/api/auth/register` | `{"username","password"}` | `200 {"message":"注册成功","username":...}`（同时写入 session，注册即登录） | `400 {"error":"用户名已被注册"}` 等校验错误 |
| POST | `/api/auth/login` | `{"username","password"}` | `200 {"message":"登录成功","username":...}` | `401 {"error":"用户名或密码错误"}` |
| POST | `/api/auth/logout` | 无 | `200 {"message":"已退出登录"}` | — |
| GET | `/api/auth/me` | 无 | `200 {"user": {"id","username"}}`；未登录返回 `{"user": null}` | — |

### 登录态约定

- 用 Flask session：登录/注册成功写入 `session['user_id']`、`session['username']`；退出用 `session.clear()`
- `simple_app.py` 已配置好 `app.secret_key`，无需重复设置

### login_required 装饰器（必须提供）

其他接口（如 `/api/chat`）用它做登录保护。前端约定：**收到 401 会自动弹出登录框**，
所以未登录必须返回 401 状态码：

```python
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('user_id') is None:
            return jsonify({'error': '请先登录', 'code': 'UNAUTHORIZED'}), 401
        return f(*args, **kwargs)
    return wrapper
```

## 实现完成后接入 simple_app.py

前端部分（状态栏 + 登录/注册弹窗 + 401 自动弹窗）**已完成**，并已在调用上述四个接口。
后端实现完成后只需两步：

① 在 `app = Flask(__name__)` / `app.secret_key` 之后添加：

```python
from controllers import auth_bp
from services.user_service import init_db

app.register_blueprint(auth_bp)
init_db()
```

②（可选，建议）给聊天接口加登录保护：

```python
from controllers.auth_controller import login_required

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    ...
```

## 参考实现（可直接使用，或按上述契约自行实现）

```python
# my_ai_app/controllers/auth_controller.py
"""认证控制器：登录/注册接口。只做 收请求→调service→返回JSON"""
from functools import wraps
from flask import Blueprint, request, jsonify, session

from services.user_service import create_user, verify_user, get_user_by_id

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def login_required(f):
    """装饰器：未登录返回401，其他接口（如/api/chat）可直接复用"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('user_id') is None:
            return jsonify({'error': '请先登录', 'code': 'UNAUTHORIZED'}), 401
        return f(*args, **kwargs)
    return wrapper


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    ok, msg = create_user(username, password)
    if not ok:
        return jsonify({'error': msg}), 400

    user = verify_user(username, password)   # 注册成功直接登录
    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'message': '注册成功', 'username': user['username']})


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    user = verify_user(username, password)
    if user is None:
        return jsonify({'error': '用户名或密码错误'}), 401

    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'message': '登录成功', 'username': user['username']})


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': '已退出登录'})


@auth_bp.route('/me', methods=['GET'])
def me():
    """前端页面刷新后用它恢复登录状态"""
    uid = session.get('user_id')
    user = get_user_by_id(uid) if uid else None
    if uid and user is None:
        session.clear()
    return jsonify({'user': user})
```

`__init__.py` 内容：

```python
from .auth_controller import auth_bp, login_required
__all__ = ['auth_bp', 'login_required']
```

## 验收标准

1. `python simple_app.py` 启动无报错，页面右上角出现「登录 / 注册」按钮
2. 注册 `tom / 123456` → 弹窗关闭，状态栏显示 `👤 tom`
3. 重复注册同用户名 → 弹窗红字提示「用户名已被注册」
4. 错误密码登录 → 提示「用户名或密码错误」
5. （启用 login_required 后）未登录 `curl -X POST http://localhost:5000/api/chat` 返回 401
