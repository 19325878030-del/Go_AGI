# my_ai_app/services/db.py
"""数据库连接模块：读取 .env 配置，提供 TiDB Cloud 连接。

所有服务（user_service / log_service / ...）统一从这里拿连接，
配置只在这一处维护。连接为「按需创建、用完即关」，简单可靠；
TiDB Serverless 按请求计费，不适合常驻连接池。
"""
import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

# .env 在 my_ai_app/ 根目录（services/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

HOST = os.environ.get("DB_HOST", "")
PORT = int(os.environ.get("DB_PORT", 4000))
USER = os.environ.get("DB_USER", "")
PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "my_ai_app")
# 证书路径：.env 里写相对 my_ai_app/ 的路径（如 data/tidb/isrgrootx1.pem）
CA_PATH = BASE_DIR / os.environ.get("DB_CA", "data/tidb/isrgrootx1.pem")


def get_conn() -> pymysql.connections.Connection:
    """返回一个连到 TiDB（已选中 DB_NAME 库）的连接，调用方负责 close。

    row_factory 用 DictCursor —— 查询结果可按列名取值（对应原 sqlite3.Row 的用法）。
    utf8mb4 保证中文与 emoji 不丢。
    """
    return pymysql.connect(
        host=HOST,
        port=PORT,
        user=USER,
        password=PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        ssl={"ca": str(CA_PATH)},  # Serverless 强制 TLS
    )
