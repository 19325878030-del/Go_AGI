# my_ai_app/services/llm_provider_service.py
"""外部大模型连接配置：业务逻辑层，不依赖flask

不预设任何具体服务商/模型——连接信息（base_url / api_key / model）
完全由操作者在界面上手动填写，本模块只负责存取与连通性验证。

职责：
    1. llm_providers 表的 CRUD —— 每个用户自己填的 base_url / api_key / model 配置
    2. test_provider —— 保存前先发一条真实请求验证连通
    3. chat_openai_compatible —— 直接对话的统一调用入口（本地Ollama /v1 与外部同用）

存储：TiDB Cloud（配置见 .env，连接见 services/db.py），与 users 表同库。
api_key 明文入库（本项目的取舍），但对外接口一律脱敏返回，完整key只在后端内部取用。
"""
import pymysql

from services.db import get_conn


def init_db():
    """建表（存在则跳过），应用启动时调用一次"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS llm_providers (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    user_id    INT NOT NULL,
                    name       VARCHAR(50)  NOT NULL,
                    base_url   VARCHAR(255) NOT NULL,
                    api_key    VARCHAR(255) NOT NULL,
                    model      VARCHAR(100) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _mask_key(api_key: str) -> str:
    """脱敏：只留末4位，如 sk-ab1c****x9y2"""
    if not api_key or len(api_key) <= 4:
        return "****"
    return api_key[:2] + "****" + api_key[-4:]


def add_provider(user_id: int, name: str, base_url: str, api_key: str, model: str):
    """新增配置：检测入参 -> 入库。返回 (成功?, 错误信息)。

    name（显示名称）可留空，留空时自动用 model 当名称——界面上只要求填 url/key/model。
    """
    name = (name or '').strip()
    base_url = (base_url or '').strip()
    api_key = (api_key or '').strip()
    model = (model or '').strip()
    if not all([base_url, api_key, model]):
        return False, "URL、API Key、模型名称均不能为空"
    if not base_url.startswith(("http://", "https://")):
        return False, "URL 必须以 http:// 或 https:// 开头"
    if not name:
        name = model  # 没填名称就用模型名顶上，下拉框里可读

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO llm_providers (user_id, name, base_url, api_key, model) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, name, base_url, api_key, model),
            )
        conn.commit()
        return True, None
    finally:
        conn.close()


def list_providers(user_id: int):
    """当前用户的全部配置，api_key 已脱敏（给前端展示用）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, base_url, api_key, model, created_at "
                "FROM llm_providers WHERE user_id = %s ORDER BY id",
                (user_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    for row in rows:
        row["api_key"] = _mask_key(row["api_key"])
        # DATETIME 序列化给前端
        if row.get("created_at"):
            row["created_at"] = str(row["created_at"])
    return rows


def get_provider_by_id(provider_id: int, user_id: int):
    """按 id 取本人配置，返回含完整 api_key —— 仅后端内部调用（发请求要用），
    查不到或不是本人的都返回 None（不区分，避免探测他人配置）"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, base_url, api_key, model "
                "FROM llm_providers WHERE id = %s AND user_id = %s",
                (provider_id, user_id),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row


def delete_provider(provider_id: int, user_id: int):
    """删除本人配置。返回 (成功?, 错误信息)"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM llm_providers WHERE id = %s AND user_id = %s",
                (provider_id, user_id),
            )
        conn.commit()
        deleted = cur.rowcount
    finally:
        conn.close()
    return (deleted > 0, None) if deleted > 0 else (False, "配置不存在或已删除")


def test_provider(base_url: str, api_key: str, model: str):
    """连通性测试：发一条最小对话请求，返回 (成功?, 信息)"""
    from core.external_llm_client import ExternalLLMClient

    try:
        client = ExternalLLMClient(base_url=base_url, api_key=api_key, model=model)
        # max_tokens给足一点：推理类模型（deepseek-v4-flash/reasoner等）会先消耗
        # token 做思考，给小了 reply 为空，会误以为连接失败
        reply = client.chat([{"role": "user", "content": "你好"}], max_tokens=256)
        reply = (reply or '').strip()
        if not reply:
            return True, "连接成功（模型未返回可见内容，多为推理模型思考过长，实际对话可用）"
        return True, f"连接成功，模型回复: {reply[:50]}"
    except Exception as e:
        return False, f"连接失败: {e}"


def chat_openai_compatible(provider: dict, message: str, temperature: float = 0.7) -> str:
    """直接对话的「统一调用入口」：一条用户消息 → OpenAI 兼容 /chat/completions。

    provider 是 {base_url, api_key, model}：
      - 外部大模型：DeepSeek/GLM/千问/Kimi 等（base_url = 服务商地址）
      - 本地 Ollama：base_url = http://localhost:11434/v1（Ollama 自带 OpenAI 兼容端点），
        api_key 用占位 "ollama"
    两边走同一套消息格式、同一个客户端，本地与外部无需再区分路径。
    """
    from core.external_llm_client import ExternalLLMClient

    client = ExternalLLMClient(
        base_url=provider["base_url"],
        api_key=provider["api_key"],
        model=provider["model"],
    )
    return client.chat(
        [{"role": "user", "content": message}],
        temperature=temperature,
    )
