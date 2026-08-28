# my_ai_app/simple_app.py
"""
极简AI应用 - 单文件版本
"""
import sys
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify
import requests

# 添加项目路径
project_root = Path(__file__).parent
sys.path.append(str(project_root))

app = Flask(__name__)

# 配置
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.2:1b"  # 内存紧张时的小模型（约1GB）；内存充足可换回 "qwen2.5:3b"


@app.route('/')
def index():
    """返回简单HTML页面"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI 助手</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .container {
                background: white;
                border-radius: 20px;
                padding: 40px;
                width: 90%;
                max-width: 800px;
                max-height: 90vh;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                display: flex;
                flex-direction: column;
            }
            h1 {
                text-align: center;
                color: #333;
                margin-bottom: 20px;
                font-size: 28px;
            }
            .chat-box {
                flex: 1;
                overflow-y: auto;
                min-height: 400px;
                max-height: 500px;
                border: 1px solid #e1e5e9;
                border-radius: 10px;
                padding: 20px;
                margin-bottom: 20px;
                background: #f8f9fa;
            }
            .message {
                margin-bottom: 15px;
                padding: 10px 15px;
                border-radius: 10px;
                max-width: 80%;
                word-wrap: break-word;
                line-height: 1.5;
            }
            .user {
                background: #667eea;
                color: white;
                margin-left: auto;
            }
            .assistant {
                background: white;
                border: 1px solid #e1e5e9;
                margin-right: auto;
            }
            .input-area {
                display: flex;
                gap: 10px;
            }
            textarea {
                flex: 1;
                padding: 12px;
                border: 1px solid #ddd;
                border-radius: 10px;
                resize: vertical;
                font-size: 14px;
                font-family: inherit;
                min-height: 60px;
            }
            textarea:focus {
                outline: none;
                border-color: #667eea;
            }
            button {
                padding: 12px 30px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 16px;
                cursor: pointer;
                transition: transform 0.2s;
                white-space: nowrap;
            }
            button:hover {
                transform: scale(1.05);
            }
            button:disabled {
                opacity: 0.6;
                cursor: not-allowed;
            }
            .status {
                text-align: center;
                margin-top: 10px;
                font-size: 14px;
                color: #666;
            }
            .controls {
                display: flex;
                gap: 15px;
                margin-bottom: 10px;
                font-size: 14px;
                color: #666;
            }
            .controls label {
                display: flex;
                align-items: center;
                gap: 5px;
                cursor: pointer;
            }
            .tool-trace {
                margin-bottom: 15px;
                padding: 10px 15px;
                border-radius: 10px;
                max-width: 80%;
                margin-right: auto;
                background: #f0f4ff;
                border: 1px dashed #667eea;
                font-size: 13px;
                color: #555;
                line-height: 1.6;
            }
            .tool-trace .tool-step {
                margin: 2px 0;
            }
            .tool-trace .tool-name {
                color: #667eea;
                font-weight: bold;
            }
            .loading {
                display: inline-block;
                width: 12px;
                height: 12px;
                border: 2px solid #f3f3f3;
                border-top: 2px solid #667eea;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 AI 助手</h1>

            <div class="controls">
                <label>
                    <input type="radio" name="mode" id="modeAgent" value="agent" checked>
                    🤖 Agent模式（工具调用）
                </label>
                <label>
                    <input type="radio" name="mode" id="modeRag" value="rag">
                    📚 RAG模式（知识库）
                </label>
                <label>
                    <input type="radio" name="mode" id="modeLlm" value="llm">
                    💬 直接对话
                </label>
            </div>
            <div class="controls">
                <label>
                    温度: <input type="range" id="temperature" min="0" max="2" step="0.1" value="0.7" style="width:100px">
                    <span id="tempDisplay">0.7</span>
                </label>
            </div>

            <div class="chat-box" id="chatBox">
                <div class="message assistant">你好！我是AI助手，有什么可以帮你的吗？</div>
            </div>

            <div class="input-area">
                <textarea id="userInput" placeholder="输入你的问题..." rows="2"></textarea>
                <button id="sendBtn" onclick="sendMessage()">发送</button>
            </div>
            <div class="status" id="status">✅ 服务运行中</div>
        </div>

        <script>
            const chatBox = document.getElementById('chatBox');
            const userInput = document.getElementById('userInput');
            const sendBtn = document.getElementById('sendBtn');
            const temperature = document.getElementById('temperature');
            const tempDisplay = document.getElementById('tempDisplay');
            const status = document.getElementById('status');

            function getMode() {
                const checked = document.querySelector('input[name="mode"]:checked');
                return checked ? checked.value : 'agent';
            }

            let isProcessing = false;

            // 温度显示
            temperature.addEventListener('input', () => {
                tempDisplay.textContent = temperature.value;
            });

            // 回车发送
            userInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });

            async function sendMessage() {
                if (isProcessing) return;

                const message = userInput.value.trim();
                if (!message) return;

                // 显示用户消息
                addMessage('user', message);
                userInput.value = '';

                // 显示加载状态
                isProcessing = true;
                sendBtn.disabled = true;
                status.innerHTML = '<span class="loading"></span> 思考中...';

                try {
                    // 调用后端API
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            message: message,
                            mode: getMode(),
                            temperature: parseFloat(temperature.value)
                        })
                    });

                    const data = await response.json();

                    if (data.error) {
                        addMessage('assistant', '❌ ' + data.error);
                    } else {
                        // Agent模式下先展示工具调用轨迹，再展示最终回答
                        if (data.trace && data.trace.length > 0) {
                            addToolTrace(data.trace);
                        }
                        addMessage('assistant', data.reply);
                    }

                    status.textContent = '✅ 回复完成';
                } catch (error) {
                    addMessage('assistant', '❌ 网络错误: ' + error.message);
                    status.textContent = '❌ 连接失败';
                } finally {
                    isProcessing = false;
                    sendBtn.disabled = false;
                    userInput.focus();
                }
            }

            function addMessage(role, content) {
                const div = document.createElement('div');
                div.className = 'message ' + role;
                div.textContent = content;
                chatBox.appendChild(div);
                chatBox.scrollTop = chatBox.scrollHeight;
            }

            function addToolTrace(trace) {
                const div = document.createElement('div');
                div.className = 'tool-trace';
                trace.forEach(step => {
                    const p = document.createElement('div');
                    p.className = 'tool-step';
                    const name = document.createElement('span');
                    name.className = 'tool-name';
                    name.textContent = '🔧 ' + step.tool;
                    p.appendChild(name);
                    p.appendChild(document.createTextNode(
                        ' (' + JSON.stringify(step.parameters) + ') → ' +
                        JSON.stringify(step.result).slice(0, 120)
                    ));
                    div.appendChild(p);
                });
                chatBox.appendChild(div);
                chatBox.scrollTop = chatBox.scrollHeight;
            }
        </script>
    </body>
    </html>
    '''


@app.route('/api/chat', methods=['POST'])
def chat():
    """聊天API"""
    try:
        data = request.json
        message = data.get('message', '')
        mode = data.get('mode', 'agent')  # agent / rag / llm
        temperature = data.get('temperature', 0.7)

        if not message:
            return jsonify({'error': '请输入问题'})

        # 根据前端选择的模式分发
        if mode == 'rag':
            reply = chat_with_rag(message, temperature)
            return jsonify({'reply': reply})

        if mode == 'agent':
            reply, trace = chat_with_agent(message)
            return jsonify({'reply': reply, 'trace': trace})

        # 默认直接调用LLM
        reply = chat_with_llm(message, temperature)
        return jsonify({'reply': reply})

    except Exception as e:
        return jsonify({'error': str(e)})


def chat_with_llm(message, temperature):
    """直接调用LLM"""
    payload = {
        "model": MODEL_NAME,
        "prompt": message,
        "stream": False,
        "options": {
            "temperature": temperature
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result.get('response', '抱歉，我没有理解你的问题')
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

        rag = RAGSystem(model_name=MODEL_NAME)
        sample_path = project_root / "data" / "sample.txt"

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
            model_name=MODEL_NAME,
            ollama_url="http://localhost:11434"
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


if __name__ == '__main__':
    print("=" * 50)
    print("🚀 启动AI助手 (极简版)")
    print("📍 http://localhost:5000")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=5000)