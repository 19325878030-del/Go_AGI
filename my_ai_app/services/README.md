# services/ — 应用服务层

> **当前状态：待实现。** 本目录暂无 Python 代码，只有本说明文档。
> 请后续开发者按本文档实现 `user_service.py`（可参考文末的参考实现）。
>
> 职责边界：只写"纯业务逻辑"，**不依赖 flask**（不 import request/session），保证可复用、可单独测试。

## 目录规划

| 文件 | 职责 | 状态 |
|---|---|---|
| `__init__.py` | 空文件，把目录标记为包 | 待实现 |
| `user_service.py` | 用户注册 / 登录校验 / 查询（本项目第一个服务） | 待实现 |
| `chat_history_service.py`（将来） | 对话历史存储 | 规划中 |

## user_service.py 实现要求

### 必须提供的函数

| 函数 | 行为 |
|---|---|
| `init_db()` | 建 `users` 表（`CREATE TABLE IF NOT EXISTS`），应用启动时调用一次 |
| `create_user(username, password) -> (ok, msg)` | 校验：用户名 ≥2 字符且不含空格、密码 ≥6 位；密码用 `werkzeug.security.generate_password_hash` 哈希后入库；用户名重复（`sqlite3.IntegrityError`）返回 `(False, "用户名已被注册")` |
| `verify_user(username, password) -> dict \| None` | 校验成功返回 `{"id", "username"}`；用户不存在与密码错误**统一返回 None**（不泄露用户是否注册过） |
| `get_user_by_id(uid) -> dict \| None` | 按 id 查用户，供登录态校验 |

### 数据库约定

- 库文件：`data/users.db`（SQLite，Python 标准库，零依赖）
- 路径写法：`DB_PATH = Path(__file__).resolve().parent.parent / "data" / "users.db"`
- 表结构（DDL）：

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,          -- 只存哈希，绝不存明文
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
```

### 其他约定

- 连接设 `conn.row_factory = sqlite3.Row`（按列名取值），用完关闭连接
- Flask debug 模式多线程并发写，建议加 `threading.Lock()` 保护写操作
- 依赖：仅标准库 + werkzeug（Flask 自带，**无需新装依赖**）

## 参考实现（可直接使用，或按上述契约自行实现）

```python
# my_ai_app/services/user_service.py
"""用户服务：注册/登录校验的业务逻辑，不依赖flask"""
import sqlite3
import threading
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "users.db"
USERNAME_MIN, PASSWORD_MIN = 2, 6
_lock = threading.Lock()  # 保证并发写安全


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表（存在则跳过），应用启动时调用一次"""
    with _lock:
        conn = _conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at    TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            conn.commit()
        finally:
            conn.close()


def create_user(username: str, password: str):
    """注册。返回 (成功?, 错误信息)"""
    if not username or len(username) < USERNAME_MIN:
        return False, f"用户名至少 {USERNAME_MIN} 个字符"
    if any(c.isspace() for c in username):
        return False, "用户名不能包含空格"
    if not password or len(password) < PASSWORD_MIN:
        return False, f"密码至少 {PASSWORD_MIN} 位"

    try:
        with _lock:
            conn = _conn()
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                conn.commit()
            finally:
                conn.close()
        return True, None
    except sqlite3.IntegrityError:
        return False, "用户名已被注册"


def verify_user(username: str, password: str):
    """校验用户名密码：成功返回 {'id','username'}，失败返回 None
    （用户不存在与密码错误返回一样，避免泄露用户是否注册过）"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not check_password_hash(row["password_hash"], password):
        return None
    return {"id": row["id"], "username": row["username"]}


def get_user_by_id(uid: int):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, username FROM users WHERE id = ?", (uid,)
        ).fetchone()
    finally:
        conn.close()
    return {"id": row["id"], "username": row["username"]} if row else None
```

## 验收标准

1. 在 `my_ai_app/` 目录下执行 `python -c "from services.user_service import init_db; init_db()"`，`data/` 下生成含 `users` 表的 `users.db`
2. `create_user('tom', '123456')` 第一次返回 `(True, None)`；同用户名再调返回 `(False, '用户名已被注册')`
3. `verify_user('tom', '123456')` 返回 dict；错误密码返回 `None`
4. 数据库文件中查不到明文密码
