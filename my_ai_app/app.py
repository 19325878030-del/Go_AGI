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
from controllers import auth_bp, llm_bp, conv_bp
from controllers.api.response import ok, err
# TiDB 三张表初始化（users / api_logs / llm_providers）
from services.user_service import init_db as user_init_db
from services.log_service import init_log_db
from services import llm_provider_service
from services import conversation_service


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
# 页面含 Vue 3 的 {{ }} 语法，不能走 Jinja 渲染，只能原样返回。
# 原独立文件 static/chat_index.html 已合并删除：HTML + CSS + JS 都在这一个字符串里。
INDEX_HTML = r'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI 助手</title>
    <script src="https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.prod.js">
    </script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        html, body {
            height: 100%;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }

        /* ==================== 布局 ==================== */
        .app-layout {
            display: flex;
            height: 100vh;
            background: #f0f2f5;
        }

        /* ==================== 侧边栏 ==================== */
        .sidebar {
            width: 280px;
            min-width: 280px;
            background: #fff;
            display: flex;
            flex-direction: column;
            border-right: 1px solid #e1e5e9;
        }
        .sidebar-header {
            padding: 16px 16px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #f0f0f0;
        }
        .sidebar-header h3 {
            font-size: 16px;
            color: #333;
        }
        .new-chat-btn {
            padding: 6px 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
            border: none;
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
            white-space: nowrap;
            transition: opacity 0.2s;
        }
        .new-chat-btn:hover {
            opacity: 0.85;
        }
        .new-chat-btn:disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }
        .conv-list {
            flex: 1;
            overflow-y: auto;
            padding: 8px 0;
        }
        .conv-item {
            padding: 12px 16px;
            cursor: pointer;
            border-left: 3px solid transparent;
            transition: background 0.15s;
            position: relative;
        }
        .conv-item:hover {
            background: #f5f6fa;
        }
        .conv-item.active {
            background: #eef0ff;
            border-left-color: #667eea;
        }
        .conv-item .conv-title {
            font-size: 14px;
            color: #333;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .conv-item.active .conv-title {
            color: #667eea;
            font-weight: 600;
        }
        .conv-item .conv-time {
            font-size: 11px;
            color: #999;
            margin-top: 2px;
        }
        .conv-empty {
            padding: 32px 16px;
            text-align: center;
            color: #999;
            font-size: 14px;
        }
        .conv-empty-hint {
            font-size: 12px;
            margin-top: 6px;
            color: #bbb;
        }
        .conv-loading {
            padding: 24px;
            text-align: center;
            color: #999;
            font-size: 13px;
        }
        .sidebar-footer {
            padding: 12px 16px;
            border-top: 1px solid #f0f0f0;
            font-size: 12px;
            color: #999;
            text-align: center;
        }

        /* ==================== 主区域 ==================== */
        .main-area {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            overflow: hidden;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 30px 36px;
            width: 100%;
            max-width: 820px;
            height: 100%;
            max-height: calc(100vh - 40px);
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            display: flex;
            flex-direction: column;
        }
        .container h1 {
            text-align: center;
            color: #333;
            margin-bottom: 14px;
            font-size: 24px;
        }

        /* ==================== 聊天区 ==================== */
        .chat-box {
            flex: 1;
            overflow-y: auto;
            min-height: 280px;
            border: 1px solid #e1e5e9;
            border-radius: 10px;
            padding: 16px 18px;
            margin-bottom: 12px;
            background: #f8f9fa;
        }
        .message {
            margin-bottom: 12px;
            padding: 10px 15px;
            border-radius: 10px;
            max-width: 82%;
            word-wrap: break-word;
            line-height: 1.55;
            font-size: 14px;
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
        .input-area textarea {
            flex: 1;
            padding: 10px 14px;
            border: 1px solid #ddd;
            border-radius: 10px;
            resize: none;
            font-size: 14px;
            font-family: inherit;
            min-height: 52px;
            max-height: 120px;
            line-height: 1.4;
        }
        .input-area textarea:focus {
            outline: none;
            border-color: #667eea;
        }
        .input-area button {
            padding: 10px 28px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 15px;
            cursor: pointer;
            transition: opacity 0.2s;
            white-space: nowrap;
            align-self: flex-end;
        }
        .input-area button:hover:not(:disabled) {
            opacity: 0.88;
        }
        .input-area button:disabled {
            opacity: 0.55;
            cursor: not-allowed;
        }
        .status {
            text-align: center;
            margin-top: 8px;
            font-size: 13px;
            color: #666;
            min-height: 20px;
        }

        /* ==================== 模式 / 模型控制栏 ==================== */
        .controls {
            display: flex;
            gap: 12px;
            margin-bottom: 8px;
            font-size: 13px;
            color: #666;
            flex-wrap: wrap;
            align-items: center;
        }
        .controls label {
            display: flex;
            align-items: center;
            gap: 4px;
            cursor: pointer;
        }
        .controls select {
            padding: 5px 10px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 13px;
            max-width: 200px;
            background: #fff;
        }
        .controls input[type="range"] {
            width: 80px;
            cursor: pointer;
        }
        .add-llm-btn {
            padding: 3px 10px;
            font-size: 12px;
            border-radius: 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            cursor: pointer;
            margin-left: 2px;
        }
        .mode-hint {
            display: none;
            font-size: 12px;
            color: #e67e22;
            margin-top: 2px;
            margin-bottom: 6px;
        }
        .mode-hint.show {
            display: block;
        }
        label.disabled-mode {
            opacity: 0.45;
            cursor: not-allowed;
        }

        /* ==================== 工具调用轨迹 ==================== */
        .tool-trace {
            margin-bottom: 12px;
            padding: 10px 14px;
            border-radius: 10px;
            max-width: 82%;
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

        /* ==================== 加载动画 ==================== */
        .loading {
            display: inline-block;
            width: 12px;
            height: 12px;
            border: 2px solid #e1e5e9;
            border-top: 2px solid #667eea;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            vertical-align: middle;
            margin-right: 4px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .msg-loading {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            color: #999;
            font-size: 13px;
            padding: 10px 15px;
            margin-bottom: 12px;
            max-width: 82%;
            margin-right: auto;
        }

        /* ==================== 登录注册 ==================== */
        .auth-bar {
            display: flex;
            justify-content: flex-end;
            align-items: center;
            gap: 8px;
            margin-bottom: 10px;
            font-size: 13px;
            color: #666;
        }
        .auth-bar button {
            padding: 4px 12px;
            font-size: 12px;
            border-radius: 8px;
        }
        .auth-bar .auth-login-btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
            border: none;
            cursor: pointer;
        }
        .auth-bar .auth-logout-btn {
            background: #e74c3c;
            color: #fff;
            border: none;
            cursor: pointer;
        }

        /* ==================== 模态弹窗 ==================== */
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
            padding: 28px 30px;
            width: 340px;
            max-width: 90vw;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }
        .modal h2 {
            text-align: center;
            color: #333;
            font-size: 20px;
            margin-bottom: 18px;
        }
        .modal input {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            margin-bottom: 10px;
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
            margin-bottom: 6px;
            text-align: center;
        }
        .modal .btn-row {
            display: flex;
            gap: 10px;
            margin-top: 4px;
        }
        .modal .btn-row button {
            flex: 1;
            padding: 9px 0;
            font-size: 14px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            color: #fff;
            transition: opacity 0.2s;
        }
        .modal .btn-row button:hover {
            opacity: 0.88;
        }
        .modal .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .modal .btn-secondary {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }
        .modal .btn-cancel {
            background: #9aa0a6;
        }
        .modal.wide {
            width: 420px;
        }
        .modal select {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            margin-bottom: 10px;
            box-sizing: border-box;
            background: white;
        }
        .modal .hint {
            font-size: 12px;
            color: #999;
            margin-bottom: 10px;
            line-height: 1.5;
        }
        .modal .success {
            color: #27ae60;
            font-size: 13px;
            min-height: 18px;
            margin-bottom: 6px;
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
            margin-bottom: 6px;
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

        /* ==================== 消息加载占位（detail加载时） ==================== */
        .chat-loading-overlay {
            text-align: center;
            padding: 32px 0;
            color: #999;
        }
    </style>
</head>

<body>
<div id="app" v-cloak>
    <div class="app-layout">

        <!-- ================== 左侧边栏 ================== -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <h3>📋 会话历史</h3>
                <button class="new-chat-btn" @click="newConversation" :disabled="!user">+ 新建</button>
            </div>

            <!-- 未登录提示 -->
            <div v-if="!user" class="conv-empty">
                <p>🔒 <a href="#" @click.prevent="showAuth()" style="color:#667eea;">登录</a> 后查看历史会话</p>
            </div>

            <!-- 加载中 -->
            <div v-else-if="loadingConversations" class="conv-loading">
                <span class="loading"></span> 加载中...
            </div>

            <!-- 会话列表 -->
            <div v-else class="conv-list">
                <div v-for="conv in conversations"
                     :key="conv.id"
                     :class="['conv-item', { active: currentConvId === conv.id }]"
                     @click="loadConversation(conv.id)">
                    <div class="conv-title">{{ conv.title }}</div>
                    <div class="conv-time">{{ formatTime(conv.updated_at) }}</div>
                </div>
                <div v-if="conversations.length === 0" class="conv-empty">
                    <p>暂无会话记录</p>
                    <p class="conv-empty-hint">发送消息将自动创建新会话</p>
                </div>
            </div>

            <div class="sidebar-footer">Go_AGI</div>
        </aside>

        <!-- ================== 主聊天区 ================== -->
        <main class="main-area">
            <div class="container">
                <h1>🤖 AI 助手</h1>

                <!-- 登录注册状态条 -->
                <div class="auth-bar">
                    <span>👤 {{ user ? user.username : '未登录' }}</span>
                    <button v-if="!user" class="auth-login-btn" @click="showAuth()">登录 / 注册</button>
                    <button v-else class="auth-logout-btn" @click="doLogout()">退出登录</button>
                </div>

                <!-- 模式选择 -->
                <div class="controls">
                    <label :class="{ 'disabled-mode': isExternal }">
                        <input type="radio" value="agent" v-model="mode" :disabled="isExternal">
                        🤖 Agent模式
                    </label>
                    <label :class="{ 'disabled-mode': isExternal }">
                        <input type="radio" value="rag" v-model="mode" :disabled="isExternal">
                        📚 RAG模式
                    </label>
                    <label>
                        <input type="radio" value="llm" v-model="mode">
                        💬 直接对话
                    </label>
                </div>
                <div :class="['mode-hint', { show: isExternal }]">
                    ⚠️ 外部大模型目前仅支持「直接对话」，Agent / RAG 使用本地 Ollama 模型。
                </div>

                <!-- 模型选择 & 温度 -->
                <div class="controls">
                    <label>
                        模型：
                        <select v-model="modelSelect" @change="onModelChange">
                            <optgroup label="本地 Ollama">
                                <option v-for="m in localModels" :key="m" :value="m">{{ m }}</option>
                            </optgroup>
                            <optgroup label="外部大模型">
                                <option v-for="p in externalProviders" :key="p.id" :value="'ext:' + p.id">
                                    {{ p.name && p.name !== p.model ? p.name + '（' + p.model + '）' : p.model }}
                                </option>
                                <option v-if="externalProviders.length === 0" value="" disabled>
                                    未添加（点右侧 ➕）
                                </option>
                            </optgroup>
                        </select>
                        <button type="button" class="add-llm-btn" @click="showLlmConfig()">➕ 外部模型</button>
                    </label>
                    <label>
                        温度：
                        <input type="range" v-model.number="temperature" min="0" max="2" step="0.1">
                        <span>{{ temperature.toFixed(1) }}</span>
                    </label>
                </div>

                <!-- 当前会话标题 -->
                <div v-if="currentConvTitle && messages.length > 1" style="margin-bottom:4px;font-size:13px;color:#999;text-align:center;">
                    📌 {{ currentConvTitle }}
                </div>

                <!-- 消息容器 -->
                <div class="chat-box" ref="chatBox">
                    <!-- 加载消息中的占位 -->
                    <div v-if="loadingMessages" class="chat-loading-overlay">
                        <span class="loading"></span> 加载历史消息...
                    </div>

                    <!-- 消息列表 -->
                    <template v-else>
                        <div v-for="(msg, idx) in messages" :key="idx">
                            <div v-if="msg.type === 'trace'" class="tool-trace">
                                <div v-for="(step, si) in msg.steps" :key="si" class="tool-step">
                                    <span class="tool-name">🔧 {{ step.tool }}</span>
                                    ({{ JSON.stringify(step.parameters) }} → {{ JSON.stringify(step.result).slice(0, 120) }})
                                </div>
                            </div>
                            <div v-else :class="['message', msg.role]">
                                {{ msg.content }}
                            </div>
                        </div>

                        <!-- 思考中 -->
                        <div v-if="isProcessing" class="msg-loading">
                            <span class="loading"></span> 思考中...
                        </div>

                        <!-- 初始提示 -->
                        <div v-if="messages.length === 0 && !isProcessing && !loadingMessages"
                             class="message assistant">
                            你好！我是AI助手，有什么可以帮你的吗？
                        </div>
                    </template>
                </div>

                <!-- 输入区 -->
                <div class="input-area">
                    <textarea v-model="userInput"
                              placeholder="输入你的问题..."
                              rows="2"
                              @keydown.enter.prevent="sendMessage"
                              :disabled="isProcessing"></textarea>
                    <button @click="sendMessage" :disabled="isProcessing || !userInput.trim()">
                        发送
                    </button>
                </div>
                <div class="status" v-html="status"></div>
            </div>
        </main>
    </div>

    <!-- ================== 登录/注册弹窗 ================== -->
    <div :class="['modal-mask', { show: showAuthModal }]" @click.self="hideAuth()">
        <div class="modal">
            <h2>账号登录 / 注册</h2>
            <input type="text" v-model="authUsername" placeholder="用户名（至少2个字符）" autocomplete="username" @keydown.enter="doLogin">
            <input type="password" v-model="authPassword" placeholder="密码（至少6位）" autocomplete="current-password" @keydown.enter="doLogin">
            <div class="error">{{ authError }}</div>
            <div class="btn-row">
                <button class="btn-primary" @click="doLogin">登录</button>
                <button class="btn-secondary" @click="doRegister">注册</button>
                <button class="btn-cancel" @click="hideAuth">取消</button>
            </div>
        </div>
    </div>

    <!-- ================== 外部大模型弹窗 ================== -->
    <div :class="['modal-mask', { show: showLlmModal }]" @click.self="hideLlmConfig()">
        <div class="modal wide">
            <h2>🔗 外部大模型</h2>
            <div class="hint">手动填写连接信息（OpenAI兼容接口）。配置保存在你的账号下。</div>
            <input type="text" v-model="llmBaseUrl" placeholder="API地址，如 https://api.deepseek.com">
            <input type="text" v-model="llmModelName" placeholder="模型名称，如 deepseek-chat">
            <input type="password" v-model="llmApiKey" placeholder="API Key（sk-开头，只存你的账号）" autocomplete="off">
            <div class="error">{{ llmError }}</div>
            <div class="success">{{ llmSuccess }}</div>
            <div class="btn-row">
                <button class="btn-cancel" @click="testLlmProvider()">测试连接</button>
                <button class="btn-primary" @click="saveLlmProvider()">保存</button>
            </div>
            <h2 style="font-size:15px; margin-top:18px;">已保存的配置</h2>
            <div class="provider-list" id="providerList">
                <div v-for="p in providerList" :key="p.id" class="provider-item">
                    <div>
                        <strong>{{ p.name || p.model }}</strong><br>
                        <span style="color:#999">{{ p.model }} · {{ p.api_key }}</span>
                    </div>
                    <button class="del-btn" @click="deleteLlmProvider(p.id)">删除</button>
                </div>
                <div v-if="providerList.length === 0" class="hint" style="margin-top:8px;">还没有保存的配置</div>
            </div>
            <div class="btn-row" style="margin-top:10px;">
                <button class="btn-cancel" @click="hideLlmConfig()">关闭</button>
            </div>
        </div>
    </div>
</div>

<script>
    const { createApp, ref, computed, nextTick, onMounted } = Vue;

    const app = createApp({
        setup() {
            // ==================== 响应式状态 ====================
            const conversations = ref([]);
            const currentConvId = ref(null);
            const currentConvTitle = ref('');
            const messages = ref([]);
            const userInput = ref('');
            const isProcessing = ref(false);
            const loadingConversations = ref(false);
            const loadingMessages = ref(false);

            const localModels = ref([]);
            const externalProviders = ref([]);
            const modelSelect = ref('');
            const temperature = ref(0.7);
            const mode = ref('agent');
            const status = ref('✅ 服务运行中');

            const user = ref(null);

            // Auth modal
            const showAuthModal = ref(false);
            const authUsername = ref('');
            const authPassword = ref('');
            const authError = ref('');

            // LLM modal
            const showLlmModal = ref(false);
            const llmBaseUrl = ref('');
            const llmModelName = ref('');
            const llmApiKey = ref('');
            const llmError = ref('');
            const llmSuccess = ref('');
            const providerList = ref([]);

            const chatBox = ref(null);

            // ==================== 计算属性 ====================
            const isExternal = computed(() => {
                return modelSelect.value && String(modelSelect.value).startsWith('ext:');
            });

            // ==================== 工具函数 ====================
            function formatTime(dt) {
                if (!dt) return '';
                const d = new Date(dt);
                if (isNaN(d.getTime())) return dt;
                const now = new Date();
                const pad = (n) => String(n).padStart(2, '0');
                // 今天的只显示 时:分
                if (d.toDateString() === now.toDateString()) {
                    return pad(d.getHours()) + ':' + pad(d.getMinutes());
                }
                // 昨天的显示 "昨天 时:分"
                const yesterday = new Date(now);
                yesterday.setDate(yesterday.getDate() - 1);
                if (d.toDateString() === yesterday.toDateString()) {
                    return '昨天 ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
                }
                // 今年内的显示 月-日
                if (d.getFullYear() === now.getFullYear()) {
                    return (d.getMonth() + 1) + '-' + d.getDate();
                }
                return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
            }

            async function unwrap(resp) {
                let body = null;
                try { body = await resp.json(); } catch (e) {}
                if (body && typeof body === 'object' && !Array.isArray(body) && 'code' in body) {
                    return { code: body.code, msg: body.msg, data: body.data };
                }
                return {
                    code: resp.ok ? 0 : resp.status,
                    msg: (body && (body.msg || body.error || body.message)) || (resp.ok ? '' : '请求失败（HTTP ' + resp.status + '）'),
                    data: body,
                };
            }

            function scrollToBottom() {
                nextTick(() => {
                    if (chatBox.value) {
                        chatBox.value.scrollTop = chatBox.value.scrollHeight;
                    }
                });
            }

            // ==================== 模型相关 ====================
            async function loadModels() {
                try {
                    const resp = await fetch('/api/models');
                    const r = await unwrap(resp);
                    const data = r.data || {};
                    const models = data.models || [];
                    const providers = data.providers || [];

                    localModels.value = models;
                    externalProviders.value = providers;

                    // 恢复之前的选择
                    const hasCurrent = modelSelect.value && (
                        models.includes(modelSelect.value) ||
                        providers.some(p => 'ext:' + p.id === modelSelect.value)
                    );
                    if (!hasCurrent && models.length > 0) {
                        modelSelect.value = models[0];
                    }

                    const info = [];
                    if (models.length > 0) info.push('本地 ' + models.length + ' 个');
                    if (providers.length > 0) info.push('外部 ' + providers.length + ' 个');
                    status.value = info.length > 0
                        ? '✅ 服务运行中：' + info.join(' / ')
                        : '⚠️ 本地Ollama未启动，也暂无外部模型（点"➕ 外部模型"添加）';
                } catch (e) {
                    status.value = '⚠️ 获取模型列表失败: ' + e.message;
                }
            }

            function onModelChange() {
                const ext = isExternal.value;
                if (ext && mode.value !== 'llm') {
                    mode.value = 'llm';
                }
            }

            // ==================== 会话（Conversation）相关 ====================
            async function loadConversations() {
                if (!user.value) {
                    conversations.value = [];
                    return;
                }
                loadingConversations.value = true;
                try {
                    const resp = await fetch('/api/conversation/list');
                    if (resp.status === 401) {
                        user.value = null;
                        conversations.value = [];
                        return;
                    }
                    const r = await unwrap(resp);
                    conversations.value = (r.data && r.data.conversations) || [];
                } catch (e) {
                    console.error('加载会话列表失败:', e);
                } finally {
                    loadingConversations.value = false;
                }
            }

            async function loadConversation(id) {
                if (!user.value) return;
                if (id === currentConvId.value) return;

                loadingMessages.value = true;
                currentConvId.value = id;
                messages.value = [];

                try {
                    const resp = await fetch('/api/conversation/detail?id=' + id);
                    if (resp.status === 401) { user.value = null; return; }
                    const r = await unwrap(resp);
                    if (r.code !== 0) {
                        status.value = '❌ ' + (r.msg || '加载失败');
                        return;
                    }
                    const data = r.data || {};
                    currentConvTitle.value = data.title || '';
                    const msgs = (data.messages || []).map(m => ({
                        role: m.role,
                        content: m.content,
                        type: 'message',
                    }));
                    messages.value = msgs;
                    status.value = '✅ 已加载历史会话';
                } catch (e) {
                    status.value = '❌ 加载失败: ' + e.message;
                } finally {
                    loadingMessages.value = false;
                    scrollToBottom();
                }
            }

            async function newConversation() {
                if (!user.value) {
                    showAuth();
                    return;
                }
                try {
                    const resp = await fetch('/api/conversation/create', { method: 'POST' });
                    const r = await unwrap(resp);
                    if (r.code === 0 && r.data && r.data.conversation) {
                        const conv = r.data.conversation;
                        // 插到列表最前面
                        conversations.value.unshift(conv);
                        currentConvId.value = conv.id;
                        currentConvTitle.value = '';
                        messages.value = [];
                        status.value = '💬 新会话';
                    }
                } catch (e) {
                    status.value = '❌ 创建会话失败: ' + e.message;
                }
            }

            // ==================== 发送消息 ====================
            async function sendMessage() {
                const msg = userInput.value.trim();
                if (!msg || isProcessing.value) return;

                // 未选择模型时提示
                if (!modelSelect.value) {
                    status.value = '⚠️ 请先选择一个模型';
                    return;
                }

                // 显式添加用户消息
                messages.value.push({ role: 'user', content: msg, type: 'message' });
                userInput.value = '';
                isProcessing.value = true;
                status.value = '<span class="loading"></span> 思考中...';
                scrollToBottom();

                try {
                    const sel = modelSelect.value;
                    const ext = sel.startsWith('ext:');
                    const body = {
                        message: msg,
                        mode: mode.value,
                        temperature: parseFloat(temperature.value),
                        model: ext ? null : sel,
                        provider_id: ext ? parseInt(sel.slice(4), 10) : null,
                        conversation_id: currentConvId.value || null,
                    };

                    const resp = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'include',
                        body: JSON.stringify(body),
                    });

                    if (resp.status === 401) {
                        messages.value.push({ role: 'assistant', content: '🔒 请先登录后再对话', type: 'message' });
                        showAuth();
                        return;
                    }

                    const r = await unwrap(resp);
                    if (r.code !== 0) {
                        messages.value.push({ role: 'assistant', content: '❌ ' + (r.msg || '请求失败'), type: 'message' });
                    } else {
                        const data = r.data || {};

                        // 更新会话 ID（自动创建时返回）
                        if (data.conversation_id) {
                            currentConvId.value = data.conversation_id;
                        }

                        // 工具调用轨迹
                        if (data.trace && data.trace.length > 0) {
                            messages.value.push({ type: 'trace', steps: data.trace });
                        }

                        // AI 回复
                        messages.value.push({ role: 'assistant', content: data.reply, type: 'message' });
                        status.value = '✅ 回复完成';
                    }
                } catch (e) {
                    messages.value.push({ role: 'assistant', content: '❌ 网络错误: ' + e.message, type: 'message' });
                    status.value = '❌ 连接失败';
                } finally {
                    isProcessing.value = false;
                    scrollToBottom();
                    // 有 conversation_id 的话刷新列表（标题可能已更新）
                    if (currentConvId.value && user.value) {
                        refreshConvItem(currentConvId.value);
                    }
                }
            }

            // 刷新单条会话标题
            async function refreshConvItem(id) {
                try {
                    const resp = await fetch('/api/conversation/detail?id=' + id);
                    const r = await unwrap(resp);
                    if (r.code === 0 && r.data) {
                        const idx = conversations.value.findIndex(c => c.id === id);
                        if (idx !== -1) {
                            // 更新标题和时间
                            conversations.value[idx].title = r.data.title;
                            conversations.value[idx].updated_at = r.data.updated_at;
                            // 更新当前标题
                            if (id === currentConvId.value) {
                                currentConvTitle.value = r.data.title || '';
                            }
                        }
                    }
                } catch (e) {}
            }

            // ==================== 认证相关 ====================
            function showAuth() {
                authError.value = '';
                authUsername.value = '';
                authPassword.value = '';
                showAuthModal.value = true;
            }

            function hideAuth() {
                showAuthModal.value = false;
            }

            async function doLogin() {
                await submitAuth('/api/auth/login', '登录');
            }

            async function doRegister() {
                await submitAuth('/api/auth/register', '注册');
            }

            async function submitAuth(url, action) {
                const username = authUsername.value.trim();
                const password = authPassword.value;
                if (!username || !password) {
                    authError.value = '请输入用户名和密码';
                    return;
                }
                try {
                    authError.value = '';
                    const resp = await fetch(url, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password }),
                    });
                    const r = await unwrap(resp);
                    if (r.code !== 0) {
                        authError.value = r.msg || (action + '失败');
                        return;
                    }
                    authPassword.value = '';
                    hideAuth();
                    await refreshAuthStatus();
                } catch (e) {
                    authError.value = '请求失败: ' + e.message;
                }
            }

            async function doLogout() {
                try {
                    await fetch('/api/auth/logout', { method: 'POST' });
                } catch (e) {}
                user.value = null;
                conversations.value = [];
                currentConvId.value = null;
                currentConvTitle.value = '';
                status.value = '👋 已退出登录';
            }

            async function refreshAuthStatus() {
                try {
                    const resp = await fetch('/api/auth/me');
                    const r = await unwrap(resp);
                    const u = (r.data && r.data.user) ? r.data.user : null;
                    user.value = u;
                    if (u) {
                        // 登录后启动会话列表加载
                        await loadConversations();
                        await loadModels();
                    } else {
                        conversations.value = [];
                    }
                } catch (e) {
                    user.value = null;
                    conversations.value = [];
                }
            }

            // ==================== 外部模型配置 ====================
            async function showLlmConfig() {
                if (!user.value) {
                    alert('外部模型配置需要先登录（配置保存在你的账号下）');
                    showAuth();
                    return;
                }
                llmError.value = '';
                llmSuccess.value = '';
                llmBaseUrl.value = '';
                llmModelName.value = '';
                llmApiKey.value = '';
                showLlmModal.value = true;
                await loadProviderList();
            }

            function hideLlmConfig() {
                showLlmModal.value = false;
            }

            function collectLlmForm() {
                return {
                    base_url: llmBaseUrl.value.trim(),
                    model: llmModelName.value.trim(),
                    api_key: llmApiKey.value.trim(),
                };
            }

            async function testLlmProvider() {
                const form = collectLlmForm();
                llmError.value = '';
                llmSuccess.value = '⏳ 测试中...';
                try {
                    const resp = await fetch('/api/llm/test', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(form),
                    });
                    const r = await unwrap(resp);
                    if (r.code !== 0) {
                        llmError.value = '❌ ' + (r.msg || '测试失败');
                        llmSuccess.value = '';
                        return;
                    }
                    const data = r.data || {};
                    if (data.ok) {
                        llmSuccess.value = '✅ ' + data.message;
                    } else {
                        llmError.value = '❌ ' + (data.message || '连接失败');
                        llmSuccess.value = '';
                    }
                } catch (e) {
                    llmError.value = '请求失败: ' + e.message;
                    llmSuccess.value = '';
                }
            }

            async function saveLlmProvider() {
                const form = collectLlmForm();
                if (!form.base_url || !form.model || !form.api_key) {
                    llmError.value = 'URL、模型名称、API Key 都要填';
                    llmSuccess.value = '';
                    return;
                }
                llmError.value = '';
                llmSuccess.value = '⏳ 保存中...';
                try {
                    const resp = await fetch('/api/llm/providers', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(form),
                    });
                    const r = await unwrap(resp);
                    if (r.code !== 0) {
                        llmError.value = r.msg || '保存失败';
                        llmSuccess.value = '';
                        return;
                    }
                    llmSuccess.value = '✅ 已保存';
                    llmApiKey.value = '';
                    await loadProviderList();
                    await loadModels();
                } catch (e) {
                    llmError.value = '请求失败: ' + e.message;
                    llmSuccess.value = '';
                }
            }

            async function loadProviderList() {
                try {
                    const resp = await fetch('/api/llm/providers');
                    if (resp.status === 401) {
                        providerList.value = [];
                        return;
                    }
                    const r = await unwrap(resp);
                    providerList.value = (r.data && r.data.providers) || [];
                } catch (e) {
                    providerList.value = [];
                }
            }

            async function deleteLlmProvider(id) {
                if (!confirm('确定删除此配置？')) return;
                await fetch('/api/llm/providers/' + id, { method: 'DELETE' });
                await loadProviderList();
                await loadModels();
            }

            // ==================== 生命周期 ====================
            onMounted(() => {
                loadModels();
                refreshAuthStatus();
            });

            return {
                // State
                conversations, currentConvId, currentConvTitle, messages,
                userInput, isProcessing, loadingConversations, loadingMessages,
                localModels, externalProviders, modelSelect, temperature,
                mode, status, user,
                showAuthModal, authUsername, authPassword, authError,
                showLlmModal, llmBaseUrl, llmModelName, llmApiKey,
                llmError, llmSuccess, providerList,
                chatBox,
                // Computed
                isExternal,
                // Methods
                formatTime, sendMessage, newConversation,
                loadConversations, loadConversation,
                loadModels, onModelChange,
                showAuth, hideAuth, doLogin, doRegister, doLogout,
                showLlmConfig, hideLlmConfig,
                testLlmProvider, saveLlmProvider, deleteLlmProvider,
            };
        },
    });

    app.mount('#app');
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

    # 3. 数据库初始化（TiDB Cloud：users / api_logs / llm_providers / conversations / messages）
    #    失败不阻塞启动：先降级告警，等服务起来后再补（便于离线联调 UI）。
    try:
        user_init_db()
        init_log_db()
        llm_provider_service.init_db()
        conversation_service.init_db()
    except Exception as e:
        app.logger.warning(f"数据库自动初始化跳过或失败: {e}")

    # 4. 注册业务蓝图（auth_bp / llm_bp / conv_bp 自带 url_prefix，这里不再重复传）
    app.register_blueprint(auth_bp)
    app.register_blueprint(llm_bp)
    app.register_blueprint(conv_bp)

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

        会话历史（已登录用户）：
          - 前端传 conversation_id → 消息自动存入该会话
          - 不传 conversation_id → 自动创建新会话
          - 首条用户消息自动截取前 30 字符作为会话标题
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

            # ----- 会话管理（仅登录用户） -----
            conversation_id = data.get('conversation_id')
            uid = session.get('user_id')

            if uid:
                # 未传 conversation_id 时自动创建新会话
                if not conversation_id:
                    conv = conversation_service.create_conversation(uid)
                    conversation_id = conv['id']
                # 保存用户消息
                conversation_service.add_message(conversation_id, 'user', message)

            # 走外部模型：先取本人配置（含完整api_key），取不到说明未登录/配置被删
            provider = None
            if provider_id is not None:
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
            reply = ''
            trace = None

            if mode == 'rag':
                reply = chat_with_rag(message, temperature)
            elif mode == 'agent':
                reply, trace = chat_with_agent(message)
            else:
                # 默认直接对话：本地与外部统一走 chat_openai_compatible()
                if provider:
                    reply = llm_provider_service.chat_openai_compatible(provider, message, temperature)
                else:
                    reply = chat_with_llm(message, temperature)

            # 保存 AI 回复 + 自动标题（首条消息）
            if uid and conversation_id:
                conversation_service.add_message(conversation_id, 'assistant', reply)
                # 消息数量为 2（刚插入的user + assistant）时用首条消息做标题
                conv_detail = conversation_service.get_conversation_detail(conversation_id, uid)
                msg_count = len(conv_detail['messages']) if conv_detail else 0
                if msg_count == 2:
                    conversation_service.auto_title(conversation_id, message)

            result = {'reply': reply, 'conversation_id': conversation_id}
            if trace:
                result['trace'] = trace
            return ok(result)

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
