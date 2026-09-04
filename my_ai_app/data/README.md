# data/ — 本地存储目录

本项目所有运行时产生的本地数据统一放在这里。约定：**不要**把存储文件放到其他目录。

## 目录结构

| 内容 | 说明 | 产生方式 |
|---|---|---|
| `tidb/` | TiDB Cloud 连接相关：TLS 证书 `isrgrootx1.pem`、初始化脚本 `setup_tidb.py` | 手动 / 脚本 |
| `chroma_db/` | RAG 向量知识库 | `modules/rag/rag_demo.py` 首次构建 |
| `sample.txt` | RAG 知识库源文档 | 手动维护 |
| `logs/api_requests.jsonl` | 接口入参/出参文件日志（联调时 tail 查看） | `services/log_service.py` 追加 |
| `README.md` | 本说明 | — |

## 当前数据库：TiDB Cloud（Serverless）

- 连接配置在 `my_ai_app/.env`（不提交 git），证书路径 `DB_CA=data/tidb/isrgrootx1.pem`
- 首次初始化：`.venv\Scripts\python.exe my_ai_app\data\tidb\setup_tidb.py`（幂等）
- 新开发者交接只需两样东西：`.env` + `data/tidb/isrgrootx1.pem`

> 历史说明：项目最初用 SQLite（`users.db` / `api_logs.db`），2026-09-03 已全量迁入 TiDB 并删除本地旧库文件，服务层现在只连 TiDB。

### 表结构

```sql
-- users（注册登录，密码只存 werkzeug 哈希）
CREATE TABLE users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- api_logs（每个接口的入参/出参/耗时，联调排查用）
CREATE TABLE api_logs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    interface       VARCHAR(200) NOT NULL,
    method          VARCHAR(10)  NOT NULL,
    request_params  TEXT NOT NULL,
    response_params TEXT NOT NULL,
    status_code     INT,
    user_id         INT,
    username        VARCHAR(50),
    duration_ms     INT,
    created_at      DATETIME
);
```
