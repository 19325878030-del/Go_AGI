# data/ — 本地存储目录

本项目所有运行时产生的本地数据统一放在这里。约定：**不要**把存储文件放到其他目录。

| 内容 | 说明 | 产生方式 |
|---|---|---|
| `chroma_db/` | RAG 向量知识库 | `modules/rag/rag_demo.py` 首次构建 |
| `sample.txt` | RAG 知识库源文档 | 手动维护 |
| `users.db` | 登录注册用户库（SQLite） | 当前为空占位文件；`services/user_service.py` 实现后由其 `init_db()` 自动建表 |
| `README.md` | 本说明 | — |

## users.db 表结构（规划，由 services/user_service.py 的 init_db() 创建）

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,   -- PBKDF2 哈希（werkzeug），不存明文
    created_at    TEXT DEFAULT (datetime('now','localtime'))
);
```

> 说明：0 字节的 `.db` 文件是合法的空 SQLite 库，首次连接时会自动初始化，可直接使用。
