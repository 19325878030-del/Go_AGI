# services/ — 应用服务层

职责边界：只写"纯业务逻辑"，**不依赖 flask**（不 import request/session），保证可复用、可单独测试。

## 目录规划

| 文件 | 职责 | 状态 |
|---|---|---|
| `__init__.py` | 空文件，把目录标记为包 | ✅ |
| `db.py` | TiDB Cloud 连接模块（读 `.env`，全项目唯一连接配置入口） | ✅ |
| `user_service.py` | 用户注册 / 登录校验 / 查询 | ✅ |
| `log_service.py` | 接口入参/出参日志（文件 + TiDB 双写） | ✅ |
| `chat_history_service.py`（将来） | 对话历史存储 | 规划中 |

## 数据库约定：TiDB Cloud

- 连接配置：`my_ai_app/.env`（`DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME/DB_CA`，不提交 git）
- 统一从 `services/db.py` 的 `get_conn()` 拿连接：已选库、utf8mb4、DictCursor（按列名取值）、TLS
- 占位符用 `%s`（PyMySQL），不是 SQLite 的 `?`
- 连接用完必须 `conn.close()`（写在 `finally` 里）
- 并发写由 TiDB 服务端保证，不再需要本地 `threading.Lock`（仅文件日志追加仍需要）
- 依赖：`pymysql` + `python-dotenv`（见 `requirements.txt`）
- TLS 证书位置：`data/tidb/isrgrootx1.pem`；首次建库建表：`data/tidb/setup_tidb.py`

> 历史：2026-09-03 前用本地 SQLite（`data/users.db` / `data/api_logs.db`），已全量迁入 TiDB 并删除本地旧库。

## user_service.py 函数契约

| 函数 | 行为 |
|---|---|
| `init_db()` | 建 `users` 表（`CREATE TABLE IF NOT EXISTS`），应用启动时调用一次 |
| `create_user(username, password) -> (ok, msg)` | 校验：用户名 ≥2 字符且不含空格、密码 ≥6 位；密码用 `werkzeug.security.generate_password_hash` 哈希后入库；用户名重复（`pymysql.err.IntegrityError`）返回 `(False, "用户名已被注册")` |
| `verify_user(username, password) -> dict \| None` | 校验成功返回 `{"id", "username"}`；用户不存在与密码错误**统一返回 None**（不泄露用户是否注册过） |
| `get_user_by_id(uid) -> dict \| None` | 按 id 查用户，供登录态校验 |

## 验收标准

1. `python -c "from services.user_service import init_db; init_db()"`（在 `my_ai_app/` 目录下）连接 TiDB 成功、表存在
2. `create_user('tom', '123456')` 第一次返回 `(True, None)`；同用户名再调返回 `(False, '用户名已被注册')`
3. `verify_user('tom', '123456')` 返回 dict；错误密码返回 `None`
4. 数据库中查不到明文密码
