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
                    password_hash TEXT NOT NULL,          -- 只存哈希，绝不存明文
                    created_at    TEXT DEFAULT (datetime('now','localtime'))
                )
            """)
            conn.commit()
        finally:
            conn.close()


def validate_params(username: str, password: str):
    """检测入参：返回 (是否通过, 错误信息)。注册与登录共用的参数检测逻辑。"""
    if not username or len(username) < USERNAME_MIN:
        return False, f"用户名至少 {USERNAME_MIN} 个字符"
    if any(c.isspace() for c in username):
        return False, "用户名不能包含空格"
    if not password or len(password) < PASSWORD_MIN:
        return False, f"密码至少 {PASSWORD_MIN} 位"
    return True, None


def create_user(username: str, password: str):
    """注册：检测入参 -> 哈希密码 -> 保存数据库。返回 (成功?, 错误信息)"""
    ok, msg = validate_params(username, password)
    if not ok:
        return False, msg

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
    """按 id 查用户，供登录态校验/恢复。"""
    if uid is None:
        return None
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, username FROM users WHERE id = ?", (uid,)
        ).fetchone()
    finally:
        conn.close()
    return {"id": row["id"], "username": row["username"]} if row else None
