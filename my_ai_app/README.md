# my_ai_app — 极简AI应用（Flask + Ollama）

> **当前状态：可运行。** 主服务为单文件 `simple_app.py`（含内嵌前端页面），支持 Agent / RAG / 直接对话三种模式；登录注册已接入 TiDB Cloud。
>
> 职责边界：本目录是应用根。代码分层走 `controllers/（接口层）→ services/（业务层）→ modules/（AI能力）`，运行时产生的数据统一放 `data/`，不放其他目录。

## 目录规划

| 文件 / 目录 | 职责 | 状态 |
|---|---|---|
| `simple_app.py` | 主服务：Flask 应用 + 内嵌页面 + `/api/chat`、`/api/models` 路由（端口 5001） | ✅ |
| `requirements.txt` | Python 依赖清单 | ✅ |
| `.env` | TiDB 连接配置（不提交 git，向前任维护者索取） | ✅ |
| `controllers/` | 接口层：auth 登录注册接口（契约见其 README） | ✅ |
| `services/` | 业务层：`db` / `user_service` / `log_service`（契约见其 README） | ✅ |
| `modules/agent/` | FunctionCallAgent + 工具（天气 / 计算器 / 搜索） | ✅ |
| `modules/rag/` | RAG 系统（文档加载 / 向量库 / 问答链） | ✅ |
| `core/` | LLM API 客户端、Ollama API server 等实验代码 | ✅ |
| `data/` | 运行时数据：`sample.txt`、`chroma_db/`、`logs/`、TiDB 证书（说明见其 README） | ✅ |
| `tests/subprocess.run.py` | Pinggy 内网穿透隧道脚本（本机 5001 → 公网 HTTPS） | ✅ |
| `controllers/api/chat_controller.py`（将来） | 把 `/api/chat`、`/api/models` 从 `simple_app.py` 迁入接口层 | 规划中 |
| `services/chat_history_service.py`（将来） | 对话历史存储 | 规划中 |

## 环境要求

| 依赖 | 说明 |
|---|---|
| Python 3.10+ | 开发环境为 3.13 |
| Ollama | 已启动（默认 `http://localhost:11434`），至少 pull 一个对话模型 |
| ssh 客户端 | 仅内网穿透需要（Windows 10+ 自带） |

拉取模型：

```bash
ollama pull llama3.2:1b          # 对话模型，约1GB；内存充足可换 qwen2.5:3b
ollama pull nomic-embed-text     # RAG 嵌入模型（用 RAG 模式才需要）
```

## 快速开始

① 安装依赖（在项目根目录 `D:\Go_AGI`）：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r my_ai_app/requirements.txt
```

> 网络慢可加镜像：`pip install -r my_ai_app/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
> `sentence-transformers` 会连带装 PyTorch，体积大，首次安装慢属正常。

② 配置数据库（新开发者交接只需两样东西，均不提交 git）：

- `my_ai_app/.env` — TiDB 连接配置，向维护者索取，格式：

```ini
DB_HOST=gateway01.ap-northeast-1.prod.aws.tidbcloud.com
DB_PORT=4000
DB_USER=xxxx.root
DB_PASSWORD=xxxx
DB_NAME=my_ai_app
DB_CA=data/tidb/isrgrootx1.pem
```

- `my_ai_app/data/tidb/isrgrootx1.pem` — TLS 证书

建表在应用启动时自动完成；如需手动初始化（幂等）：

```bash
.venv\Scripts\python.exe my_ai_app\data\tidb\setup_tidb.py
```

③ 启动服务：

```bash
python my_ai_app\simple_app.py
```

访问 **http://localhost:5001**（端口固定 5001，5000 被本机其他项目占用）。

## 接口契约

| 方法 | 路径 | 请求体 | 成功响应 | 说明 |
|---|---|---|---|---|
| POST | `/api/chat` | `{"message", "mode": "agent\|rag\|llm", "temperature", "model"}` | `{"reply", "trace?"}` | 按模式分发；agent 模式额外返回工具调用轨迹 |
| GET | `/api/models` | — | `{"models", "current"}` | Ollama 已装对话模型列表（自动过滤嵌入模型） |
| POST | `/api/auth/register` | `{"username","password"}` | `200 {"message","username"}` | 注册即登录；用户名 ≥2 字符、密码 ≥6 位 |
| POST | `/api/auth/login` | `{"username","password"}` | `200 {"message","username"}` | 失败 401 |
| POST | `/api/auth/logout` | — | `200 {"message"}` | 清空 session |
| GET | `/api/auth/me` | — | `200 {"user": {...}\|null}` | 页面刷新后恢复登录态 |

> 跨域：`flask-cors` 全局开启且 `supports_credentials=True`，前端 fetch 必须写 `credentials: 'include'`。此为联调专用写法，上线前改成明确白名单。

## 前后端联调（内网穿透）

前端不在同一局域网时，把本机 5001 映射成公网地址：

```bash
python my_ai_app\tests\subprocess.run.py
```

测试隧道通否：
python my_ai_app\tests\subprocess.run.py


- 运行后打印公网 URL，前端 `API_BASE` 用 `.run.pinggy-free.link` 结尾那个
- ⚠️ 免费版 60 分钟过期；断线/过期后重跑脚本，会分配**新地址**，前端 `API_BASE` 要跟着换

## 验收标准

1. `python my_ai_app\simple_app.py` 启动无报错，页面打开且模型下拉框有值（说明 Ollama 正常）
2. 直接对话模式发一条消息能收到回复；Agent 模式能看到工具调用轨迹
3. RAG 模式首次提问慢（建向量库）属正常，之后明显变快
4. 注册 `tom / 123456` → 弹窗关闭，状态栏显示 `👤 tom`
5. `data/logs/api_requests.jsonl` 能看到每个接口的入参/出参记录（联调时 tail 查看）
6. 跑通隧道脚本后，用打印出的公网 URL 在另一台设备打开页面可正常对话
