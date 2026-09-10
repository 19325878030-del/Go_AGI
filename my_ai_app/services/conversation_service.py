# my_ai_app/services/conversation_service.py
"""会话（Conversation）服务：对话历史记录的业务逻辑层，不依赖 flask

表结构（TiDB）：
    conversations — 会话头（id, user_id, title, created_at, updated_at）
    messages     — 消息明细（id, conversation_id, role, content, created_at）

与聊天流程的关系：
    1. 每次用户发送消息时，前端携带 conversation_id（或留空表示新建）
    2. 后端 /api/chat 自动将用户消息+AI回复写入 messages 表
    3. 首条用户消息自动截取生成会话标题
    4. 前端侧边栏通过 /api/conversation/list 获取概要列表
    5. 点击会话项 → /api/conversation/detail?conversationId=<id> 获取完整消息
"""
import pymysql

from services.db import get_conn


def init_db():
    """建表（幂等），应用启动时调用"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    user_id    INT NOT NULL,
                    title      VARCHAR(100) NOT NULL DEFAULT '新对话',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id INT NOT NULL,
                    role            VARCHAR(20) NOT NULL,
                    content         TEXT NOT NULL,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
        conn.commit()
    finally:
        conn.close()


def create_conversation(user_id: int, title: str = None):
    """创建新会话，返回新行 dict"""
    _title = (title or '').strip() or '新对话'
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
                (user_id, _title),
            )
            conn.commit()
            new_id = cur.lastrowid
            # 回读刚插入的行（拿到 DATETIME 等默认值）
            cur.execute(
                "SELECT id, user_id, title, created_at, updated_at "
                "FROM conversations WHERE id = %s",
                (new_id,),
            )
            row = cur.fetchone()
            return _serialize_conv(row) if row else None
    finally:
        conn.close()


def list_conversations(user_id: int, limit: int = 50):
    """按更新时间倒序取最近会话列表"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, title, created_at, updated_at "
                "FROM conversations WHERE user_id = %s "
                "ORDER BY updated_at DESC LIMIT %s",
                (user_id, limit),
            )
            rows = cur.fetchall()
        return [_serialize_conv(r) for r in rows]
    finally:
        conn.close()


def get_conversation_detail(conversation_id: int, user_id: int):
    """获取会话详情（含消息列表），仅本人可访问，查不到返回 None"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 1. 查会话头
            cur.execute(
                "SELECT id, user_id, title, created_at, updated_at "
                "FROM conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            conv = cur.fetchone()
            if not conv:
                return None

            # 2. 查消息列表（按时间正序）
            cur.execute(
                "SELECT id, role, content, created_at "
                "FROM messages WHERE conversation_id = %s "
                "ORDER BY id ASC",
                (conversation_id,),
            )
            messages = cur.fetchall()

        return {
            **conv,
            "messages": [
                {
                    "id": m["id"],
                    "role": m["role"],
                    "content": m["content"],
                    "created_at": str(m["created_at"]) if m.get("created_at") else None,
                }
                for m in messages
            ],
            "created_at": str(conv["created_at"]) if conv.get("created_at") else None,
            "updated_at": str(conv["updated_at"]) if conv.get("updated_at") else None,
        }
    finally:
        conn.close()


def add_message(conversation_id: int, role: str, content: str):
    """追加一条消息，返回新行 dict"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (%s, %s, %s)",
                (conversation_id, role, content),
            )
            conn.commit()
            new_id = cur.lastrowid
            cur.execute(
                "SELECT id, conversation_id, role, content, created_at "
                "FROM messages WHERE id = %s",
                (new_id,),
            )
            row = cur.fetchone()
            return {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": str(row["created_at"]) if row.get("created_at") else None,
            } if row else None
    finally:
        conn.close()


def auto_title(conversation_id: int, first_message: str):
    """用首条用户消息自动生成标题（截取前 30 字符）"""
    title = first_message.strip()[:30]
    if not title:
        title = "新对话"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET title = %s WHERE id = %s",
                (title, conversation_id),
            )
            conn.commit()
    finally:
        conn.close()


def _serialize_conv(row: dict) -> dict:
    """统一序列化会话行"""
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
        "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
    }