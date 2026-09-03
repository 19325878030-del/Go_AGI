# my_ai_app/modules/auth/service/auth_service.py
"""
服务层 —— 登录注册的「检测/校验逻辑」+ 数据库读写。

职责：
    * 检测入参（用户名/密码格式）            validate_params()
    * 注册：检测通过后哈希密码入库（保存数据库）create_user()
    * 登录：校验用户名密码（登录逻辑）        verify_user() / login()
    * 查询：按 id 查用户（登录态恢复用）      get_user_by_id()

说明：本层不依赖 flask（不 import request/session），保证可复用、可单独测试。
"""
import sqlite3
import threading
from pathlib import Path

from werkzeug.security import generate_password_hash, check_password_hash

# my_ai_app/ 目录（本文件位于 my_ai_app/modules/auth/service/）
BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "users.db"

USERNAME_MIN = 2   # 与前端约定：用户名至少 2 个字符
PASSWORD_MIN = 6   # 与前端约定：密码至少 6 位

_lock = threading.Lock()  # Flask debug 多线程并发写保护


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建 users 表（存在则跳过），应用启动时调用一次。"""
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
    """注册：检测入参 -> 哈希密码 -> 保存数据库。返回 (成功?, 错误信息, 用户dict)。"""
    ok, msg = validate_params(username, password)
    if not ok:
        return False, msg, None

    try:
        with _lock:
            conn = _conn()
            try:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)),
                )
                conn.commit()
                uid = cur.lastrowid
            finally:
                conn.close()
        return True, None, {"id": uid, "username": username}
    except sqlite3.IntegrityError:
        return False, "用户名已被注册", None


def verify_user(username: str, password: str):
    """登录检测：校验用户名密码。成功返回 {'id','username'}，失败返回 None。
    （用户不存在与密码错误统一返回 None，避免泄露用户是否注册过）"""
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


def login(username: str, password: str):
    """登录逻辑：先检测入参，再校验用户名密码。返回 (成功?, 错误信息, 用户dict)。"""
    ok, msg = validate_params(username, password)
    if not ok:
        return False, msg, None
    user = verify_user(username, password)
    if user is None:
        return False, "用户名或密码错误", None
    return True, None, user


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
