# my_ai_app/app.py
"""
AI 助手后端 —— 应用工厂（Application Factory）入口。

把原来 simple_app.py 里的单体启动改造成 create_app() 工厂：
    * 每次调用 create_app() 返回一个全新、已配置好的 Flask 实例；
    * 配置 / 跨域 / 数据库初始化 / 蓝图注册 都在工厂内完成；
    * 入口统一：命令行、gunicorn、调试器都从本模块拿 app 实例。

与 simple_app.py 的关系：simple_app.py 现只保留 3 行兼容层，转发到这里。
"""
import os
import sys
from pathlib import Path

import requests
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from dotenv import load_dotenv

# Windows 控制台默认 GBK 编码，print emoji（🚀🔄等）会抛 UnicodeEncodeError 直接崩，
# 这里强制标准输出为 UTF-8，保证任何终端/后台运行都安全
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent          # my_ai_app/
# 保证从任意目录 import controllers / services 都能找到包
sys.path.insert(0, str(BASE_DIR))
# 加载 my_ai_app/.env（DB 连接、密钥等）
load_dotenv(BASE_DIR / ".env")


# ==================== 接口层 / 服务层 组件（工厂内注册） ====================
# 登录注册蓝图 auth_bp、外部模型配置蓝图 llm_bp（自带上 /api/auth、/api/llm 前缀）
from controllers import auth_bp, llm_bp
# TiDB 三张表初始化（users / api_logs / llm_providers）
from services.user_service import init_db as user_init_db
from services.log_service import init_log_db
from services import llm_provider_service


# ==================== 配置 ====================
OLLAMA_BASE = "http://localhost:11434"  # ollama 根地址，用于查询模型列表
# Ollama 自带 OpenAI 兼容端点 /v1/chat/completions（返回结构与 DeepSeek 等一致）。
# 直接对话统一走它 —— 本地 Ollama 也当成一个"provider"，和外部模型共用同一调用函数。
OLLAMA_V1 = OLLAMA_BASE + "/v1"
OLLAMA_API_KEY = "ollama"  # Ollama 不校验 key，仅占位（客户端要求非空）
MODEL_NAME = "llama3.2:1b"  # 内存紧张时的小模型（约1GB）；内存充足可换回 "qwen2.5:3b"

# 当前使用的模型，运行时由 /api/chat 按前端选择更新
_current_model = MODEL_NAME


# ==================== 简单测试前端页面（原 simple_app 内嵌 HTML） ====================
# 845 行前端 HTML 已抽到 static/chat_index.html，这里启动时读入并原样返回
# （页面含 Vue 风格 {{ }} 语法，不能走 render_template_string，只能原样返回避免被 Jinja 解析）
try:
    INDEX_HTML = (BASE_DIR / "static" / "chat_index.html").read_text(encoding="utf-8")
except Exception as e:
    print(f"⚠️ 读取 chat_index.html 失败，/ 将返回降级信息: {e}")
    INDEX_HTML = None


# ==================== LLM / RAG / Agent 辅助函数 ====================
def chat_with_llm(message, temperature, model=None):
    """直接对话（本地 Ollama）—— 与外部模型走同一个 OpenAI 兼容调用函数。

    把本地 Ollama 也注册成一个 provider：
        {base_url: http://localhost:11434/v1, api_key: "ollama", model: 本地模型}
    然后调 llm_provider_service.chat_openai_compatible() —— 和外部 DeepSeek 走同一入口。
    """
    model = model or _current_model  # 未显式传入时用当前选中模型
    local_provider = {
        "base_url": OLLAMA_V1,
        "api_key": OLLAMA_API_KEY,
        "model": model,
    }
    try:
        return llm_provider_service.chat_openai_compatible(local_provider, message, temperature)
    except Exception as e:
        return f'调用LLM失败: {str(e)}'


# ==================== RAG支持 ====================
# 懒加载的全局RAG实例：首次调用时初始化（加载嵌入模型+建向量库耗时），
# 后续请求复用，避免每个请求重建
_rag_system = None


def get_rag_system():
    """获取（必要时初始化）RAG系统单例"""
    global _rag_system
    if _rag_system is None:
        from modules.rag.rag_demo import RAGSystem

        rag = RAGSystem(model_name=_current_model)
        sample_path = BASE_DIR / "data" / "sample.txt"

        if not sample_path.exists():
            raise FileNotFoundError(f"知识库文档不存在: {sample_path}")

        # 优先加载已有向量库；没有或损坏则从文档重建
        try:
            rag.load_vectorstore()
        except Exception:
            documents = rag.load_documents(str(sample_path))
            rag.create_vectorstore(documents)

        rag.setup_qa_chain(k=3)
        _rag_system = rag
    return _rag_system


def chat_with_rag(message, temperature):
    """使用RAG系统回答（基于data/sample.txt知识库）"""
    try:
        rag = get_rag_system()
        result = rag.ask(message)
        return result.get('answer', '抱歉，没有找到答案')

    except Exception as e:
        print(f"RAG错误: {e}")
        # 降级到普通LLM，保证前端始终有回复
        return chat_with_llm(message, temperature)


# ==================== Agent支持 ====================
# 同样采用懒加载单例：Agent初始化只需注册工具（快），
# 但保持与RAG一致的模式，首次调用时创建，后续复用
_agent_instance = None


def get_agent():
    """获取（必要时初始化）FunctionCallAgent单例"""
    global _agent_instance
    if _agent_instance is None:
        from modules.agent.custom_agent import FunctionCallAgent

        _agent_instance = FunctionCallAgent(
            model_name=_current_model,
            ollama_url=OLLAMA_BASE
        )
    return _agent_instance


def chat_with_agent(message):
    """
    使用Agent回答（支持天气/计算器/单位转换/搜索等工具调用）

    Returns:
        (回答文本, 工具调用轨迹列表)
    """
    trace = []
    try:
        agent = get_agent()
        reply = agent.chat(message, trace=trace)
        return reply, trace

    except Exception as e:
        print(f"Agent错误: {e}")
        # Agent失败时降级到普通LLM，保证前端始终有回复
        return chat_with_llm(message, 0.7), trace


# ==================== 应用工厂 ====================
def create_app(config_name=None):
    """
    应用工厂：负责创建 Flask 实例、基础配置、跨域、数据库初始化与蓝图注册。

    用法：
        app = create_app()
        app.run(host="0.0.0.0", port=5001)
    """
    app = Flask(__name__)

    # 1. 基础配置
    app.config["ENV"] = os.getenv("FLASK_ENV", "development")
    app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    # 登录 session 签名密钥（配合 controllers/ 登录注册功能，部署前请换随机值）
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    # 2. 跨域支持 —— 保持 supports_credentials=True：
    #    登录态靠 session Cookie，前端 fetch 带 credentials:'include'，缺这个登录接口调不通。
    CORS(app, supports_credentials=True)

    # 3. 数据库初始化（TiDB Cloud：users / api_logs / llm_providers 三张表）
    #    失败不阻塞启动：先降级告警，等服务起来后再补（便于离线联调 UI）。
    try:
        user_init_db()
        init_log_db()
        llm_provider_service.init_db()
    except Exception as e:
        app.logger.warning(f"数据库自动初始化跳过或失败: {e}")

    # 4. 注册业务蓝图（auth_bp / llm_bp 自带 url_prefix，这里不再重复传）
    app.register_blueprint(auth_bp)
    app.register_blueprint(llm_bp)

    # 5. 注册应用内路由（原 simple_app 中直接挂在 app 上的接口）
    _register_inline_routes(app)

    return app


def _register_inline_routes(app):
    """注册不依赖蓝图的内联路由（原 simple_app.py 里 @app.route 的部分）。"""

    # ==================== 极简测试前端页面 ====================
    @app.route('/')
    def index():
        """原 simple_app 内嵌的 AI 助手调试页（原样返回，不做 Jinja 渲染）"""
        if INDEX_HTML is None:
            return jsonify({"message": "测试页面文件缺失: static/chat_index.html"}), 500
        return INDEX_HTML

    # ==================== 健康检查（新增，供负载均衡 / 监控探活） ====================
    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({
            "status": "ok",
            "environment": app.config.get("ENV", "development"),
            "service": "Go_AGI Backend",
        }), 200

    # ==================== 模型列表 /api/models ====================
    @app.route('/api/models', methods=['GET'])
    def list_models():
        """返回可选模型列表：本地Ollama已安装的 + 当前用户保存的外部模型配置"""
        # 本地Ollama部分
        local_models = []
        ollama_error = None
        try:
            response = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()
            # 过滤嵌入模型（如nomic-embed-text）：family是bert类或名字带embed的
            # 只能算向量不能对话，选它调generate会被Ollama拒绝(400)
            local_models = [
                m['name'] for m in data.get('models', [])
                if 'embed' not in m['name'] and 'bert' not in m.get('details', {}).get('family', '')
            ]
        except Exception as e:
            ollama_error = str(e)

        # 外部模型部分：登录用户自己在 /api/llm 保存的配置（api_key已脱敏）
        providers = []
        uid = session.get('user_id')
        if uid:
            try:
                providers = llm_provider_service.list_providers(uid)
            except Exception as e:
                print(f"⚠️ 读取外部模型配置失败: {e}")

        return jsonify({
            'models': local_models,
            'current': _current_model,
            'providers': providers,          # [{id,name,base_url,api_key(脱敏),model}]
            'error': ollama_error
        })

    # ==================== 聊天 /api/chat ====================
    @app.route('/api/chat', methods=['POST'])
    def chat():
        """聊天API

        当前三种模式相互独立（后续要加的"并行模式"再统一编排）：
          - rag / agent：只能走本地 Ollama（单例模型与工具调用基于本地模型）
          - llm 直接对话：可选本地 Ollama，或外部大模型（provider_id）
        """
        global _rag_system, _agent_instance, _current_model
        try:
            data = request.json
            message = data.get('message', '')
            mode = data.get('mode', 'agent')  # agent / rag / llm
            temperature = data.get('temperature', 0.7)
            model = data.get('model') or MODEL_NAME
            # 外部模型：前端选了 "ext:<id>" 时携带 provider_id，优先级高于本地model
            provider_id = data.get('provider_id')

            # 走外部模型：先取本人配置（含完整api_key），取不到说明未登录/配置被删
            provider = None
            if provider_id is not None:
                uid = session.get('user_id')
                if uid is None:
                    return jsonify({'error': '使用外部模型需要先登录', 'code': 'UNAUTHORIZED'}), 401
                provider = llm_provider_service.get_provider_by_id(provider_id, uid)
                if provider is None:
                    return jsonify({'error': '外部模型配置不存在，请重新选择或添加'}), 400

                # 外部模型目前只接"直接对话"，不接 Agent/RAG（等并行模式再做编排）
                if mode in ('rag', 'agent'):
                    return jsonify({'error': '外部模型目前仅支持「直接对话」模式；'
                                            'Agent / RAG 请先把模型切回本地再使用'}), 400

            # 本地模型变化时丢弃旧例，rag和agent下次调用会用新模型重建。
            # （外部直接对话无状态，不影响这里的单例）
            if model != _current_model:
                _rag_system = None
                _agent_instance = None
                _current_model = model
                print(f"🔄 切换模型:{model}")

            if not message:
                return jsonify({'error': '请输入问题'})

            # 根据前端选择的模式分发
            if mode == 'rag':
                reply = chat_with_rag(message, temperature)
                return jsonify({'reply': reply})

            if mode == 'agent':
                reply, trace = chat_with_agent(message)
                return jsonify({'reply': reply, 'trace': trace})

            # 默认直接对话：本地与外部统一走 chat_openai_compatible()
            #   - 选了外部模型(provider) -> 直接用其 base_url/api_key/model
            #   - 没选(本地) -> chat_with_llm 内部把 Ollama 也注册成 /v1 的 provider
            if provider:
                reply = llm_provider_service.chat_openai_compatible(provider, message, temperature)
            else:
                reply = chat_with_llm(message, temperature)
            return jsonify({'reply': reply})

        except Exception as e:
            return jsonify({'error': str(e)})

    return app


# 暴露全局 app 实例（供 gunicorn / 调试器 / simple_app 兼容层引用）
app = create_app()

if __name__ == '__main__':
    # 5000 被本机其他项目（Harness）占用，固定默认用 5001；可用环境变量 PORT 覆盖
    port = int(os.getenv("PORT", "5001"))
    print("=" * 50)
    print("🚀 启动AI助手 (应用工厂模式 app.py)")
    print(f"📍 http://localhost:{port}")
    print(f"💚 健康检查: http://localhost:{port}/api/health")
    print("=" * 50)
    app.run(debug=app.config.get("DEBUG", True), host='0.0.0.0', port=port)
