# my_ai_app/services/user_service.py
"""用户服务：注册/登录校验的业务逻辑，不依赖flask

存储：TiDB Cloud（配置见 .env，连接见 services/db.py）。
表结构由 init_db() / data/tidb/setup_tidb.py 创建（幂等）。
"""
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash

from services.db import get_conn

USERNAME_MIN, PASSWORD_MIN = 2, 6


def init_db():
    """建表（存在则跳过），应用启动时调用一次"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    username      VARCHAR(50)  UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,   -- 只存哈希，绝不存明文
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
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

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                (username, generate_password_hash(password)),
            )
        conn.commit()
        return True, None
    except pymysql.err.IntegrityError:
        return False, "用户名已被注册"
    finally:
        conn.close()


def verify_user(username: str, password: str):
    """校验用户名密码：成功返回 {'id','username'}，失败返回 None
    （用户不存在与密码错误返回一样，避免泄露用户是否注册过）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None or not check_password_hash(row["password_hash"], password):
        return None
    return {"id": row["id"], "username": row["username"]}


def get_user_by_id(uid: int):
    """按 id 查用户，供登录态校验/恢复。"""
    if uid is None:
        return None
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username FROM users WHERE id = %s", (uid,))
            row = cur.fetchone()
    finally:
        conn.close()
    return {"id": row["id"], "username": row["username"]} if row else None
