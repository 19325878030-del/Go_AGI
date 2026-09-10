# 验证：外部模型接入（直接对话 / Agent / RAG 三模式）—— 不依赖真实 API Key
# （本地 mock OpenAI 端点）。运行: python tests/verify_external_llm.py
#
# 当前设计（三个功能独立，并行模式后续再加）：
#   - llm 直接对话 / agent / rag 生成 -> 均可选本地 Ollama 或外部模型（provider_id）
#   - agent 的工具调用走提示词JSON协议（不依赖原生 function calling），外部模型同一代码路径
# 本脚本起隔离端口 5002 验证（不干扰正在运行的 5001 服务）。
import sys, json, threading
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\Go_AGI\my_ai_app')

import http.server
import requests

BASE = 'http://localhost:5002'   # 隔离端口：脚本自己起服务，不依赖/不干扰 5001
APP_PORT = 5002
MOCK_PORT = 5999
received_log = []  # mock 收到的 body，断言用


class MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        received_log.append(body)
        content = body['messages'][-1].get('content', '')
        # 工具结果以 user 角色回灌（带 "[系统] 工具 xx 已执行" 标注）：
        # mock 据此判断轮次——首问回工具调用JSON，收到结果后给最终自然语言回复
        has_tool_result = any('[系统] 工具' in (m.get('content') or '') for m in body['messages'])
        if '工具' in body['messages'][0].get('content', '') and not has_tool_result:
            reply = '{"tool": "calculator", "parameters": {"expression": "2+3*4"}}'
        else:
            reply = 'Mock回复: ' + content[:30]
        resp = json.dumps({"choices": [{"message": {"role": "assistant", "content": reply}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)


def main():
    # 起被测服务（隔离端口 5002）
    import os
    os.environ['PORT'] = str(APP_PORT)
    os.environ['FLASK_DEBUG'] = 'False'
    import app as app_module
    flask_app = app_module.app
    from werkzeug.serving import make_server
    srv_app = make_server('127.0.0.1', APP_PORT, flask_app)
    threading.Thread(target=srv_app.serve_forever, daemon=True).start()
    print(f'✅ 被测服务已启动 :{APP_PORT}')

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', MOCK_PORT), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print('✅ mock OpenAI端点已启动 :5999')

    s = requests.Session()
    r = s.post(BASE + '/api/auth/login', json={'username': 'llm_test_user', 'password': 'test123456'})
    assert r.status_code == 200, r.text
    print('✅ 登录成功')

    # 保存指向 mock 的配置
    r = s.post(BASE + '/api/llm/providers', json={
        'base_url': f'http://127.0.0.1:{MOCK_PORT}',   # 无 name，应自动用模型名顶上
        'api_key': 'sk-mock-0000', 'model': 'mock-model'})
    assert r.status_code == 200, r.text
    providers_data = s.get(BASE + '/api/llm/providers').json()['data']['providers']
    pid = [p for p in providers_data if p['model'] == 'mock-model'][0]['id']
    prov = [p for p in providers_data if p['id'] == pid][0]
    assert prov['name'] == 'mock-model', f"名称未自动用模型名顶上: {prov}"
    assert prov['api_key'] == 'sk****0000', f"key未脱敏: {prov['api_key']}"
    print(f'✅ 手动填url/key/model新增成功 id={pid}（名称自动=模型名，key脱敏）')

    # 1) 外部模型 + 直接对话 -> 应走外部并正常回复
    r = s.post(BASE + '/api/chat', json={'message': '你好', 'mode': 'llm', 'provider_id': pid})
    d = r.json()['data']
    assert r.status_code == 200 and 'Mock回复' in d.get('reply', ''), d
    print(f'✅ 直聊(外部): "{d["reply"]}"')

    # 2) 外部模型 + Agent -> 应正常走外部模型，返回回复与工具调用轨迹
    received_log.clear()
    r = s.post(BASE + '/api/chat', json={'message': '帮我算 2+3*4', 'mode': 'agent', 'provider_id': pid})
    d = r.json()
    assert r.status_code == 200 and d['code'] == 0, (r.status_code, d)
    # mock 首轮回工具调用JSON → Agent 执行 calculator → 结果喂回 → mock 给最终回复
    assert 'trace' in (d.get('data') or {}), d
    trace = d['data'].get('trace') or []
    assert trace and trace[0]['tool'] == 'calculator', trace
    assert trace[0]['result'] == 14.0, trace  # 工具真的被执行了
    assert 'Mock回复' in d['data'].get('reply', ''), d
    print(f'✅ Agent(外部): 工具轨迹={[{"tool": t["tool"], "result": t["result"]} for t in trace]} 回复="{d["data"]["reply"][:30]}"')

    # 3) 外部模型 + RAG 生成 -> 生成模型可走外部（此处只验证分发不拒绝；
    #    RAG 检索依赖本地嵌入与已建向量库，无库时返回明确错误提示即可接受）
    r = s.post(BASE + '/api/chat', json={'message': 'hi', 'mode': 'rag', 'provider_id': pid,
                                         'collection_name': 'no_such_lib_xyz'})
    d = r.json()
    assert r.status_code == 200 and d['code'] == 0 or (d.get('msg') and '不存在' in d['msg']), d
    print('✅ RAG(外部): 分发正常（无库场景返回明确提示，不再是"外部模型被拒绝"）')

    # 4) mock 收到的请求确为 OpenAI 格式（消息带 user，请求带 model）
    assert received_log, 'mock未收到请求'
    assert all('model' in b and any(m.get('role') == 'user' for m in b['messages']) for b in received_log)
    print(f'✅ mock 收到 {len(received_log)} 次 OpenAI 格式请求')

    # 5) 清理
    s.delete(BASE + f'/api/llm/providers/{pid}')
    srv.shutdown()
    srv_app.shutdown()
    print('✅ 已清理 mock 配置，验证通过')


if __name__ == '__main__':
    main()
