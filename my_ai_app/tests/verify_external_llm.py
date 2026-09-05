# 验证：外部模型接入（仅「直接对话」模式）+ 与 Agent/RAG 的边界隔离
# 不依赖真实 API Key（本地 mock OpenAI 端点）。运行: python tests/verify_external_llm.py
#
# 当前设计（三个功能独立，并行模式后续再加）：
#   - rag / agent      -> 只走本地 Ollama（外部 provider_id 会被拒绝）
#   - llm 直接对话     -> 可选本地 Ollama 或外部模型（provider_id）
import sys, json, threading
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\Go_AGI\my_ai_app')

import http.server
import requests

BASE = 'http://localhost:5001'
MOCK_PORT = 5999
received_log = []  # mock 收到的 body，断言用


class MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length))
        received_log.append(body)
        content = body['messages'][-1].get('content', '')
        reply = 'Mock回复: ' + content[:30]
        resp = json.dumps({"choices": [{"message": {"role": "assistant", "content": reply}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)


def main():
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

    # 2) 外部模型 + Agent / RAG -> 应被边界隔离拒绝（400，提示切回本地）
    for mode in ('agent', 'rag'):
        r = s.post(BASE + '/api/chat', json={'message': 'hi', 'mode': mode, 'provider_id': pid})
        assert r.status_code == 400 and '直接对话' in r.json().get('msg', ''), (mode, r.status_code, r.json())
        print(f'✅ 外部模型 + {mode} 模式被正确拒绝: {r.json()["msg"]}')

    # 3) mock 收到的请求确为 OpenAI 格式（消息带 user，请求带 model）
    assert received_log, 'mock未收到请求'
    assert all('model' in b and any(m.get('role') == 'user' for m in b['messages']) for b in received_log)
    print(f'✅ mock 收到 {len(received_log)} 次 OpenAI 格式请求')

    # 4) 清理
    s.delete(BASE + f'/api/llm/providers/{pid}')
    srv.shutdown()
    print('✅ 已清理 mock 配置，验证通过')


if __name__ == '__main__':
    main()
