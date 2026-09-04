# my_ai_app/data/tidb/setup_tidb.py
"""
TiDB 一次性初始化脚本：建库 + 建 users 表 + 连通性验证

使用方法：
  1. 在 my_ai_app/.env 里把 DB_PASSWORD 填成你设置的密码（其余项已配好）
  2. 在 D:\\Go_AGI 目录下运行：
       .venv\\Scripts\\python.exe my_ai_app\\data\\tidb\\setup_tidb.py
  3. 看到 ✅ 即成功。脚本可重复运行（幂等）。

注意：密码永远不要填进本文件、不要提交 git、不要发到群里。
"""
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

# Windows 控制台默认 GBK 编码，避免中文/emoji 输出报错
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# .env 在 my_ai_app/ 根目录（data/tidb/ 的上上级）
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

HOST = os.environ.get("DB_HOST", "")
PORT = int(os.environ.get("DB_PORT", 4000))
USER = os.environ.get("DB_USER", "")
PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "my_ai_app")
# 证书路径：.env 里写相对 my_ai_app/ 的路径（如 data/tidb/isrgrootx1.pem）
CA_PATH = BASE_DIR / os.environ.get("DB_CA", "data/tidb/isrgrootx1.pem")


def main():
    # ---- 前置检查 ----
    if not PASSWORD or "在这里填" in PASSWORD:
        print("❌ 请先编辑 my_ai_app/.env，把 DB_PASSWORD 填成真实密码")
        sys.exit(1)
    if not CA_PATH.exists():
        print(f"❌ 找不到证书文件: {CA_PATH}")
        print("   请把 TiDB Cloud 下载的证书（isrgrootx1.pem）放到 my_ai_app/data/tidb/ 目录")
        sys.exit(1)

    # ---- 连接（不指定库，因为库还没建）----
    try:
        conn = pymysql.connect(
            host=HOST,
            port=PORT,
            user=USER,
            password=PASSWORD,
            ssl={"ca": str(CA_PATH)},  # Serverless 强制 TLS
        )
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("   排查顺序：① 密码是否正确 ② 用户名必须是带前缀的完整形式"
              "（形如 xxxxx.root，去控制台 Connect 弹窗核对）③ host 是否复制完整")
        sys.exit(1)

    # ---- 建库建表（幂等，重复执行无副作用）----
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4"
            )
            cur.execute(f"USE {DB_NAME}")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INT AUTO_INCREMENT PRIMARY KEY,
                    username      VARCHAR(50)  UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            cur.execute("SHOW TABLES")
            tables = [r[0] for r in cur.fetchall()]
        conn.commit()
        print(f"✅ 连接成功！TiDB 版本: {version}")
        print(f"✅ 数据库 {DB_NAME} 已就绪，当前表: {tables}")
        print("🎉 其他后端开发者拿到 .env 和证书即可用同样方式连接")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
