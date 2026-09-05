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
from flask import Flask, request, session
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
from controllers.api.response import ok, err
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


# ==================== 简单测试前端页面（前端代码已全部内联于此） ====================
# 页面含 Vue 风格 {{ }} 语法，不能走 render_template_string，只能原样返回避免被 Jinja 解析。
# 原独立文件 static/chat_index.html 已合并删除：HTML + CSS + JS 都在这一个字符串里。
INDEX_HTML = '''
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
            select{
                padding: 6px 10px;
                border:1px solid #ddd;
                border-radius:8px;
                font-size:14px;
                max-width:220px;
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

            /* ==================== 登录注册 ==================== */
            .auth-bar {
                display: flex;
                justify-content: flex-end;
                align-items: center;
                gap: 10px;
                margin-bottom: 15px;
                font-size: 14px;
                color: #666;
            }
            .auth-bar button {
                padding: 6px 14px;
                font-size: 13px;
                border-radius: 8px;
            }
            .modal-mask {
                display: none;
                position: fixed;
                inset: 0;
                background: rgba(0, 0, 0, 0.45);
                justify-content: center;
                align-items: center;
                z-index: 100;
            }
            .modal-mask.show {
                display: flex;
            }
            .modal {
                background: white;
                border-radius: 16px;
                padding: 30px;
                width: 340px;
                max-width: 90vw;
                box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            }
            .modal h2 {
                text-align: center;
                color: #333;
                font-size: 22px;
                margin-bottom: 20px;
            }
            .modal input {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid #ddd;
                border-radius: 8px;
                font-size: 14px;
                margin-bottom: 12px;
                box-sizing: border-box;
            }
            .modal input:focus {
                outline: none;
                border-color: #667eea;
            }
            .modal .error {
                color: #e74c3c;
                font-size: 13px;
                min-height: 18px;
                margin-bottom: 8px;
                text-align: center;
            }
            .modal .btn-row {
                display: flex;
                gap: 10px;
            }
            .modal .btn-row button {
                flex: 1;
                padding: 10px;
                font-size: 14px;
            }
            .modal .btn-row .btn-secondary {
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            }
            .modal .btn-row .btn-cancel {
                background: #9aa0a6;
            }
            /* 外部模型管理弹窗：比登录弹窗宽一点，容纳更多输入框 */
            .modal.wide {
                width: 420px;
            }
            .modal select {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid #ddd;
                border-radius: 8px;
                font-size: 14px;
                margin-bottom: 12px;
                box-sizing: border-box;
                background: white;
            }
            .modal .hint {
                font-size: 12px;
                color: #999;
                margin-bottom: 12px;
                line-height: 1.5;
            }
            .modal .success {
                color: #27ae60;
                font-size: 13px;
                min-height: 18px;
                margin-bottom: 8px;
                text-align: center;
                word-break: break-all;
            }
            .provider-list .provider-item {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px 10px;
                border: 1px solid #eee;
                border-radius: 8px;
                margin-bottom: 8px;
                font-size: 13px;
            }
            .provider-list .provider-item .del-btn {
                background: #e74c3c;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
                cursor: pointer;
            }
            .add-llm-btn {
                padding: 4px 10px;
                font-size: 12px;
                border-radius: 8px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                cursor: pointer;
                margin-left: 6px;
            }
            .mode-hint {
                display: none;
                font-size: 12px;
                color: #e67e22;
                margin-top: 4px;
            }
            label.disabled-mode {
                opacity: 0.45;
                cursor: not-allowed;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 AI 助手</h1>

            <!-- 登录注册：状态栏，登录后显示用户名 -->
            <div class="auth-bar">
                <span id="authStatus">👤 未登录</span>
                <button id="authToggleBtn" onclick="showAuthModal()">登录 / 注册</button>
            </div>

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
            <div class="mode-hint" id="modeHint">⚠️ 外部大模型目前仅支持「直接对话」，Agent / RAG 使用本地 Ollama 模型。</div>
            <div class="controls">
                <label>
                    模型：<select id="modelSelect"><option value="">加载中。。。</option></select>
                    <button type="button" class="add-llm-btn" onclick="showLlmModal()">➕ 外部模型</button>
                </label>
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

        <!-- 登录/注册弹窗（放在script之前，保证脚本执行时能取到DOM） -->
        <div class="modal-mask" id="authModal">
            <div class="modal">
                <h2>账号登录 / 注册</h2>
                <input type="text" id="authUsername" placeholder="用户名（至少2个字符）" autocomplete="username">
                <input type="password" id="authPassword" placeholder="密码（至少6位）" autocomplete="current-password">
                <div class="error" id="authError"></div>
                <div class="btn-row">
                    <button onclick="doLogin()">登录</button>
                    <button class="btn-secondary" onclick="doRegister()">注册</button>
                    <button class="btn-cancel" onclick="hideAuthModal()">取消</button>
                </div>
            </div>
        </div>

        <!-- 外部大模型配置弹窗（需登录，配置存TiDB当前用户名下） -->
        <div class="modal-mask" id="llmModal">
            <div class="modal wide">
                <h2>🔗 外部大模型</h2>
                <div class="hint">手动填写连接信息（OpenAI兼容接口）。配置保存在你的账号下（TiDB）。</div>
                <input type="text" id="llmBaseUrl" placeholder="API地址，如 https://api.deepseek.com">
                <input type="text" id="llmModel" placeholder="模型名称，如 deepseek-chat">
                <input type="password" id="llmApiKey" placeholder="API Key（sk-开头，只存你的账号）" autocomplete="off">
                <div class="error" id="llmError"></div>
                <div class="success" id="llmSuccess"></div>
                <div class="btn-row">
                    <button class="btn-cancel" onclick="testLlmProvider()">测试连接</button>
                    <button onclick="saveLlmProvider()">保存</button>
                </div>
                <h2 style="font-size:16px; margin-top:20px;">已保存的配置</h2>
                <div class="provider-list" id="providerList"></div>
                <div class="btn-row" style="margin-top:10px;">
                    <button class="btn-cancel" onclick="hideLlmModal()">关闭</button>
                </div>
            </div>
        </div>

        <script>
            const chatBox = document.getElementById('chatBox');
            const userInput = document.getElementById('userInput');
            const sendBtn = document.getElementById('sendBtn');
            const temperature = document.getElementById('temperature');
            const tempDisplay = document.getElementById('tempDisplay');
            const status = document.getElementById('status');
            const modelSelect = document.getElementById('modelSelect');

            // 统一响应信封：所有数据接口返回 {code,msg,data}；code===0 成功，否则 data=null、msg=错误文本。
            // HTTP 状态码保留（401 触发登录弹窗）。unwrap 把响应解包成 {code,msg,data} 便于取用。
            async function unwrap(resp) {
                let body = null;
                try { body = await resp.json(); } catch (e) { /* 非 JSON 响应，如 HTML 404 */ }
                if (body && typeof body === 'object' && !Array.isArray(body) && 'code' in body) {
                    return { code: body.code, msg: body.msg, data: body.data };
                }
                // 兜底：理论不会命中（本应用数据接口均已信封化）
                return {
                    code: resp.ok ? 0 : resp.status,
                    msg: (body && (body.msg || body.error || body.message)) || (resp.ok ? '' : '请求失败（HTTP ' + resp.status + '）'),
                    data: body,
                };
            }

            //页面加载时获取模型列表（本地Ollama + 已登录用户的外部模型配置）
            async function loadModels(){
                try{
                    const response = await fetch('/api/models');
                    const r = await unwrap(response);
                    const data = r.data || {};
                    renderModelSelect(data.models || [], data.providers || []);
                    // 恢复/改变选择后同步一次模式可选项
                    updateModeByModel();
                    const localCount = (data.models || []).length;
                    const extCount = (data.providers || []).length;
                    if (localCount === 0 && extCount === 0) {
                        status.textContent = '⚠️ 本地Ollama未启动，也暂无外部模型（点"➕ 外部模型"添加）';
                    } else {
                        status.textContent = '✅ 服务运行中：本地 ' + localCount + ' 个 / 外部 ' + extCount + ' 个模型';
                    }
                } catch (e) {
                    status.textContent = '⚠️ 获取模型列表失败: ' + e.message;
                }
            }

            // 渲染模型下拉框：本地一组、外部一组（外部value用 ext:{id} 标识）
            function renderModelSelect(localModels, providers){
                // 记住当前选择，重渲染后尽量恢复
                const prev = modelSelect.value;
                modelSelect.innerHTML = '';

                const localGroup = document.createElement('optgroup');
                localGroup.label = '本地 Ollama';
                localModels.forEach(name =>{
                    const option =document.createElement('option');
                    option.value =name;
                    option.textContent = name;
                    localGroup.appendChild(option);
                });
                modelSelect.appendChild(localGroup);

                const extGroup = document.createElement('optgroup');
                extGroup.label = '外部大模型';
                providers.forEach(p =>{
                    const option = document.createElement('option');
                    option.value = 'ext:' + p.id;
                    // 名称与模型名相同（未单独命名）时只显示模型名，避免重复
                    option.textContent = (p.name && p.name !== p.model)
                        ? p.name + '（' + p.model + '）'
                        : p.model;
                    extGroup.appendChild(option);
                });
                if (providers.length === 0) {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = '未添加（点右侧➕）';
                    option.disabled = true;
                    extGroup.appendChild(option);
                }
                modelSelect.appendChild(extGroup);

                // 恢复之前的选择（选项还在时）
                if (prev && modelSelect.querySelector('option[value="' + prev + '"]')) {
                    modelSelect.value = prev;
                }
            }

            // 登录状态变化后刷新（外部模型配置跟登录用户绑定）
            function refreshModelsAfterAuth(){
                loadModels();
            }
            loadModels();

            function getMode() {
                const checked = document.querySelector('input[name="mode"]:checked');
                return checked ? checked.value : 'agent';
            }

            // 模式与模型的边界：外部大模型只接「直接对话」，Agent/RAG 仅用本地模型
            const modeAgentRadio = document.getElementById('modeAgent');
            const modeRagRadio = document.getElementById('modeRag');
            const modeLlmRadio = document.getElementById('modeLlm');
            const modeHintEl = document.getElementById('modeHint');

            function updateModeByModel() {
                const isExternal = (modelSelect.value || '').startsWith('ext:');
                modeAgentRadio.disabled = isExternal;
                modeRagRadio.disabled = isExternal;
                modeHintEl.style.display = isExternal ? 'block' : 'none';
                // 选了外部模型时强制切到「直接对话」
                if (isExternal && !modeLlmRadio.checked) modeLlmRadio.checked = true;
            }

            modelSelect.addEventListener('change', updateModeByModel);

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
                    // 选中 ext:<id> 时走外部模型（带provider_id），否则走本地Ollama（带model）
                    const sel = modelSelect.value;
                    const isExternal = sel.startsWith('ext:');
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            message: message,
                            mode: getMode(),
                            temperature: parseFloat(temperature.value),
                            model: isExternal ? null : sel,
                            provider_id: isExternal ? parseInt(sel.slice(4), 10) : null
                        })
                    });

                    // 后端启用登录保护后，未登录会返回401
                    if (response.status === 401) {
                        addMessage('assistant', '🔒 请先登录后再对话');
                        showAuthModal();
                        return;
                    }

                    const r = await unwrap(response);

                    if (r.code !== 0) {
                        addMessage('assistant', '❌ ' + (r.msg || '请求失败'));
                    } else {
                        const data = r.data || {};
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

            // ==================== 登录注册 ====================
            // 依赖后端 controllers/auth_controller.py 的四个接口：
            //   POST /api/auth/register  {username, password}
            //   POST /api/auth/login     {username, password}
            //   POST /api/auth/logout
            //   GET  /api/auth/me        → {"user": {"id","username"} | null}
            // 后端未实现时这里会静默降级为"未登录"，不影响聊天功能
            const authModal = document.getElementById('authModal');
            const authUsername = document.getElementById('authUsername');
            const authPassword = document.getElementById('authPassword');
            const authError = document.getElementById('authError');
            const authStatusEl = document.getElementById('authStatus');
            const authToggleBtn = document.getElementById('authToggleBtn');

            function showAuthModal() {
                authError.textContent = '';
                authModal.classList.add('show');
                authUsername.focus();
            }

            function hideAuthModal() {
                authModal.classList.remove('show');
            }

            // 点击遮罩空白处关闭弹窗
            authModal.addEventListener('click', function (e) {
                if (e.target === authModal) hideAuthModal();
            });

            // 密码框内按回车 = 登录
            authPassword.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') doLogin();
            });

            async function doLogin() {
                await submitAuth('/api/auth/login', '登录');
            }

            async function doRegister() {
                await submitAuth('/api/auth/register', '注册');
            }

            async function submitAuth(url, actionName) {
                const username = authUsername.value.trim();
                const password = authPassword.value;
                if (!username || !password) {
                    authError.textContent = '请输入用户名和密码';
                    return;
                }
                try {
                    authError.textContent = '';
                    const response = await fetch(url, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username: username, password: password })
                    });
                    const r = await unwrap(response);
                    if (r.code !== 0) {
                        authError.textContent = r.msg || (actionName + '失败');
                        return;
                    }
                    authPassword.value = '';
                    hideAuthModal();
                    refreshAuthStatus();
                } catch (e) {
                    // 接口返回非JSON（如404页面）会走到这里，多半是后端还没实现
                    authError.textContent = '请求失败（后端接口未实现?）: ' + e.message;
                }
            }

            async function doLogout() {
                try {
                    await fetch('/api/auth/logout', { method: 'POST' });
                } catch (e) { /* 忽略网络错误 */ }
                refreshAuthStatus();
            }

            async function refreshAuthStatus() {
                // 查询当前登录用户并刷新状态栏；接口不存在/未实现时按未登录处理
                try {
                    const response = await fetch('/api/auth/me');
                    const r = await unwrap(response);
                    updateAuthUI(r.data ? r.data.user : null);
                } catch (e) {
                    updateAuthUI(null);
                }
            }

            function updateAuthUI(user) {
                if (user) {
                    authStatusEl.textContent = '👤 ' + user.username;
                    authToggleBtn.textContent = '退出登录';
                    authToggleBtn.onclick = doLogout;
                } else {
                    authStatusEl.textContent = '👤 未登录';
                    authToggleBtn.textContent = '登录 / 注册';
                    authToggleBtn.onclick = showAuthModal;
                }
                // 登录态变了，外部模型配置也变了（跟登录用户绑定），刷新下拉框
                refreshModelsAfterAuth();
            }

            // ==================== 外部大模型配置 ====================
            // 依赖后端 controllers/api/llm_controller.py：
            //   连接信息（url/模型名/密钥）由操作者手动填写，不预设服务商
            //   GET  /api/llm/providers      → 当前用户已存配置（key脱敏）
            //   POST /api/llm/providers      → 新增 {base_url, api_key, model}
            //   DELETE /api/llm/providers/id → 删除
            //   POST /api/llm/test           → 连通性测试
            const llmModal = document.getElementById('llmModal');
            const llmBaseUrl = document.getElementById('llmBaseUrl');
            const llmModel = document.getElementById('llmModel');
            const llmApiKey = document.getElementById('llmApiKey');
            const llmError = document.getElementById('llmError');
            const llmSuccess = document.getElementById('llmSuccess');
            const providerList = document.getElementById('providerList');

            async function showLlmModal() {
                // 配置存登录用户名下，未登录先去登录
                try {
                    const me = await unwrap(await fetch('/api/auth/me'));
                    if (!me.data || !me.data.user) {
                        alert('外部模型配置需要先登录（配置保存在你的账号下）');
                        showAuthModal();
                        return;
                    }
                } catch (e) { /* 查询失败也允许打开弹窗，保存时后端会再拦 */ }

                llmError.textContent = '';
                llmSuccess.textContent = '';
                // 打开时清空输入框，避免沿用上一次填的连接信息
                llmBaseUrl.value = '';
                llmModel.value = '';
                llmApiKey.value = '';
                llmModal.classList.add('show');
                await loadProviderList();
            }

            function hideLlmModal() {
                llmModal.classList.remove('show');
            }

            llmModal.addEventListener('click', function (e) {
                if (e.target === llmModal) hideLlmModal();
            });

            // 采集表单：url + 模型名 + api key，名称留空由后端用模型名顶上
            function collectLlmForm() {
                return {
                    base_url: llmBaseUrl.value.trim(),
                    model: llmModel.value.trim(),
                    api_key: llmApiKey.value.trim()
                };
            }

            async function testLlmProvider() {
                const form = collectLlmForm();
                llmError.textContent = '';
                llmSuccess.textContent = '⏳ 测试中...';
                try {
                    const response = await fetch('/api/llm/test', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(form)
                    });
                    const r = await unwrap(response);
                    if (r.code !== 0) {
                        llmError.textContent = '❌ ' + (r.msg || '测试失败');
                        llmSuccess.textContent = '';
                        return;
                    }
                    const data = r.data || {};
                    if (data.ok) {
                        llmSuccess.textContent = '✅ ' + data.message;
                    } else {
                        llmError.textContent = '❌ ' + (data.message || '连接失败');
                        llmSuccess.textContent = '';
                    }
                } catch (e) {
                    llmError.textContent = '请求失败: ' + e.message;
                    llmSuccess.textContent = '';
                }
            }

            async function saveLlmProvider() {
                const form = collectLlmForm();
                if (!form.base_url || !form.model || !form.api_key) {
                    llmError.textContent = 'URL、模型名称、API Key 都要填';
                    llmSuccess.textContent = '';
                    return;
                }
                llmError.textContent = '';
                llmSuccess.textContent = '⏳ 保存中...';
                try {
                    const response = await fetch('/api/llm/providers', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(form)
                    });
                    const r = await unwrap(response);
                    if (r.code !== 0) {
                        llmError.textContent = r.msg || '保存失败';
                        llmSuccess.textContent = '';
                        return;
                    }
                    llmSuccess.textContent = '✅ 已保存';
                    llmApiKey.value = '';
                    await Promise.all([loadProviderList(), loadModels()]);
                } catch (e) {
                    llmError.textContent = '请求失败: ' + e.message;
                    llmSuccess.textContent = '';
                }
            }

            async function loadProviderList() {
                try {
                    const response = await fetch('/api/llm/providers');
                    if (response.status === 401) {
                        providerList.innerHTML = '<div class="hint">未登录，暂无配置</div>';
                        return;
                    }
                    const data = (await unwrap(response)).data || {};
                    providerList.innerHTML = '';
                    (data.providers || []).forEach(p => {
                        const item = document.createElement('div');
                        item.className = 'provider-item';

                        const info = document.createElement('div');
                        const title = (p.name && p.name !== p.model) ? p.name : p.model;
                        info.innerHTML = '<strong>' + title + '</strong><br>' +
                            '<span style="color:#999">' + p.model + ' · ' + p.api_key + '</span>';

                        const delBtn = document.createElement('button');
                        delBtn.className = 'del-btn';
                        delBtn.textContent = '删除';
                        delBtn.onclick = async () => {
                            if (!confirm('删除配置「' + title + '」？')) return;
                            await fetch('/api/llm/providers/' + p.id, { method: 'DELETE' });
                            await Promise.all([loadProviderList(), loadModels()]);
                        };

                        item.appendChild(info);
                        item.appendChild(delBtn);
                        providerList.appendChild(item);
                    });
                    if ((data.providers || []).length === 0) {
                        providerList.innerHTML = '<div class="hint">还没有保存的配置</div>';
                    }
                } catch (e) {
                    providerList.innerHTML = '<div class="hint">加载失败: ' + e.message + '</div>';
                }
            }

            // 页面加载完成后恢复登录状态（放在末尾，确保上面的DOM引用已初始化）
            refreshAuthStatus();
        </script>
    </body>
    </html>
'''



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
        return INDEX_HTML

    # ==================== 健康检查（新增，供负载均衡 / 监控探活） ====================
    @app.route('/api/health', methods=['GET'])
    def health_check():
        return ok({
            "status": "ok",
            "environment": app.config.get("ENV", "development"),
            "service": "Go_AGI Backend",
        })

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

        return ok({
            'models': local_models,
            'current': _current_model,
            'providers': providers,          # [{id,name,base_url,api_key(脱敏),model}]
            'error': ollama_error,           # 可为 null：Ollama 拉取失败时的信息，不影响整体成功
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
                    return err('使用外部模型需要先登录', 401)
                provider = llm_provider_service.get_provider_by_id(provider_id, uid)
                if provider is None:
                    return err('外部模型配置不存在，请重新选择或添加', 400)

                # 外部模型目前只接"直接对话"，不接 Agent/RAG（等并行模式再做编排）
                if mode in ('rag', 'agent'):
                    return err('外部模型目前仅支持「直接对话」模式；'
                               'Agent / RAG 请先把模型切回本地再使用', 400)

            # 本地模型变化时丢弃旧例，rag和agent下次调用会用新模型重建。
            # （外部直接对话无状态，不影响这里的单例）
            if model != _current_model:
                _rag_system = None
                _agent_instance = None
                _current_model = model
                print(f"🔄 切换模型:{model}")

            if not message:
                return err('请输入问题', 400)

            # 根据前端选择的模式分发
            if mode == 'rag':
                reply = chat_with_rag(message, temperature)
                return ok({'reply': reply})

            if mode == 'agent':
                reply, trace = chat_with_agent(message)
                return ok({'reply': reply, 'trace': trace})

            # 默认直接对话：本地与外部统一走 chat_openai_compatible()
            #   - 选了外部模型(provider) -> 直接用其 base_url/api_key/model
            #   - 没选(本地) -> chat_with_llm 内部把 Ollama 也注册成 /v1 的 provider
            if provider:
                reply = llm_provider_service.chat_openai_compatible(provider, message, temperature)
            else:
                reply = chat_with_llm(message, temperature)
            return ok({'reply': reply})

        except Exception as e:
            return err(str(e), 500)

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
