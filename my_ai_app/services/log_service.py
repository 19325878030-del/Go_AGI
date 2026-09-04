# my_ai_app/services/log_service.py
"""
服务层 —— 入参/出参记录（联调日志）。

联调时用来定位问题，每个接口请求都记录：
    * 是哪一个接口（interface + method）
    * 入参是什么（request）
    * 出参是什么（response）
    * 状态码、耗时、登录用户

同时写两处：
    1. data/logs/api_requests.jsonl —— 追加式 JSON 行，联调时 tail 直接看
    2. TiDB Cloud 的 api_logs 表 —— 结构化保存，方便 SQL 查询
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from services.db import get_conn

BASE_DIR = Path(__file__).resolve().parent.parent   # my_ai_app/
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "api_requests.jsonl"

_lock = threading.Lock()  # 保护文件日志的并发追加


def init_log_db():
    """建 api_logs 表 + logs 目录，应用启动时调用一次。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS api_logs (
                    id              INT AUTO_INCREMENT PRIMARY KEY,
                    interface       VARCHAR(200) NOT NULL,  -- 接口路径，如 /api/auth/login
                    method          VARCHAR(10)  NOT NULL,  -- HTTP 方法
                    request_params  TEXT NOT NULL,          -- 入参(JSON)
                    response_params TEXT NOT NULL,          -- 出参(JSON)
                    status_code     INT,
                    user_id         INT,
                    username        VARCHAR(50),
                    duration_ms     INT,
                    created_at      DATETIME
                )
            """)
        conn.commit()
    finally:
        conn.close()


def log_request(interface, method, request_params, response_params,
                status_code=200, user_id=None, username=None, duration_ms=0):
    """记录一次接口调用的入参/出参。request/response 会做 JSON 序列化。

    文件日志失败会抛出（调用方 log_api 装饰器已捕获）；
    数据库写失败不影响文件日志。
    """
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "interface": interface,
        "method": method,
        "request": request_params,
        "response": response_params,
        "status_code": status_code,
        "user_id": user_id,
        "username": username,
        "duration_ms": duration_ms,
    }

    req_json = _dumps(request_params)
    resp_json = _dumps(response_params)

    with _lock:
        # 1) 追加文件日志（联调时 tail 查看最方便）
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 2) 写数据库（结构化，方便 SQL 查询）
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO api_logs
                       (interface, method, request_params, response_params,
                        status_code, user_id, username, duration_ms)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (interface, method, req_json, resp_json,
                     status_code, user_id, username, duration_ms),
                )
            conn.commit()
        finally:
            conn.close()


def _dumps(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps({"__serialize_error__": str(obj)}, ensure_ascii=False)


def query_logs(interface=None, limit=50):
    """查询最近日志（联调排查用），可按接口过滤。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if interface:
                cur.execute(
                    "SELECT * FROM api_logs WHERE interface = %s ORDER BY id DESC LIMIT %s",
                    (interface, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM api_logs ORDER BY id DESC LIMIT %s", (limit,)
                )
            return cur.fetchall()
    finally:
        conn.close()
