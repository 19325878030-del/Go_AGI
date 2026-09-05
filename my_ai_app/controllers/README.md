# controllers/ — 接口层（Controller）

> **当前状态：已实现。** 代码位于 `controllers/api/`（`auth_controller.py`、`llm_controller.py`、
> `response.py`、`schemas.py`），`controllers/__init__.py` 导出两个自带前缀的蓝图。
>
> 职责边界：只做「接收 HTTP 请求 → 调用 services 层 → 返回统一信封 JSON」。
> 不写业务规则、不直接操作数据库、不依赖前端。
>
> 应用工厂 `app.py` 的 `create_app()` 里已 `register_blueprint(auth_bp)`、`register_blueprint(llm_bp)`，
> 无需再手工接入。

## 目录结构

| 文件 | 职责 | 状态 |
|---|---|---|
| `__init__.py` | 导出 `auth_bp`、`llm_bp`、`login_required` | 已实现 |
| `response.py` | 统一响应信封 `ok()` / `err()` | 已实现 |
| `auth_controller.py` | 登录注册接口（`/api/auth/*`） | 已实现 |
| `llm_controller.py` | 外部大模型配置接口（`/api/llm/*`） | 已实现 |
| `schemas.py` | 前端入参模型（`RegisterParams` / `LoginParams`） | 已实现 |
| `chat_controller.py`（将来） | 把 `app.py` 中内联的 `/api/chat`、`/api/models` 迁入 | 规划中 |

## 统一响应信封（所有接口）

```jsonc
// 成功：HTTP 200
{ "code": 0, "msg": "success", "data": { /* 业务载荷 */ } }
// 错误：保留 HTTP 状态码（401/400/404/500），body.code 与状态码同数值
{ "code": 401, "msg": "具体错误描述", "data": null }
```

- 一律走 `controllers/api/response.py`：`ok(data)` / `err(msg, code)`，二者都返回 `(flask.Response, int)`。
- 前端按 `code === 0` 判断成功；`login_required` 的 401 会让前端自动弹登录框。
- 注意：`@log_api` 依赖返回体是 Flask `Response`（能 `get_json()`），所以 `ok`/`err` 不能改成返回裸 dict。

## auth_controller.py 接口契约

蓝图：`auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')`

| 方法 | 路径 | 请求体 | 成功（HTTP 200, data） | 失败（保留状态码） |
|---|---|---|---|---|
| POST | `/api/auth/register` | `{"username","password"}` | `{"username": ...}`（同时写入 session，注册即登录） | `400 {code:400,msg:"用户名已被注册"} 等` |
| POST | `/api/auth/login` | `{"username","password"}` | `{"username": ...}` | `401 {code:401,msg:"用户名或密码错误"}` |
| POST | `/api/auth/logout` | 无 | `{}` | — |
| GET | `/api/auth/me` | 无 | `{"user": {"id","username"}\|null}`（未登录仍返回 200） | — |

### 登录态约定

- 用 Flask session：登录/注册成功写入 `session['user_id']`、`session['username']`；退出用 `session.clear()`
- session 签名密钥在 `app.py` 工厂的 `create_app()` 里配置（`SECRET_KEY`，默认 dev 值，部署前换成随机串）

### login_required 装饰器

其他接口（如 `/api/llm/*`）用它做登录保护。前端约定：**收到 401 会自动弹出登录框**，
所以未登录必须返回 HTTP 401：

```python
from .response import err

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('user_id') is None:
            return err('请先登录', 401)
        return f(*args, **kwargs)
    return wrapper
```

## llm_controller.py 接口契约（简）

蓝图：`llm_bp = Blueprint('llm', __name__, url_prefix='/api/llm')`，全部端点挂 `@login_required`。

| 方法 | 路径 | 成功（data） | 失败 |
|---|---|---|---|
| GET | `/api/llm/providers` | `{"providers": [...]}`（api_key 脱敏） | 401 未登录 |
| POST | `/api/llm/providers` | `{}` | 400 缺参/URL 不合法 |
| DELETE | `/api/llm/providers/<id>` | `{}` | 404 不存在/非本人 |
| POST | `/api/llm/test` | `{"ok": bool, "message": ...}`（连不上也 200，看 `data.ok`） | 400 缺参 |

## 参考实现已过时 ⚠️

本文档下方原「参考实现」对应的旧路径（`controllers/auth_controller.py`）与旧返回格式（`{"message":...}`/`{"error":...}`）
**已被真实代码取代**：真源是 `controllers/api/auth_controller.py`（含 `@log_api`、`schemas.py`、统一信封），
**不要再照旧实现**，以免产生第三份漂移。llm 端点的逐接口说明见 `llm_controller.py` 模块头注释。
