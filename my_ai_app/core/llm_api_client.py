# my_ai_app/core/llm_api_client.py
import requests
import json
from typing import Dict, List, Optional, Generator


class LLMAPIClient:
    """本地LLM API客户端"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = requests.Session()

    def health_check(self) -> Dict:
        """健康检查"""
        try:
            response = self.session.get(f"{self.base_url}/health")
            return response.json()
        except:
            return {"status": "unavailable"}

    def generate(self, prompt: str, **kwargs) -> Dict:
        """文本生成"""
        payload = {
            "prompt": prompt,
            "max_tokens": kwargs.get('max_tokens', 512),
            "temperature": kwargs.get('temperature', 0.7),
            "top_p": kwargs.get('top_p', 0.9),
            "stream": False
        }

        response = self.session.post(
            f"{self.base_url}/generate",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    def generate_stream(self, prompt: str, **kwargs) -> Generator:
        """流式生成"""
        payload = {
            "prompt": prompt,
            "max_tokens": kwargs.get('max_tokens', 512),
            "temperature": kwargs.get('temperature', 0.7),
            "top_p": kwargs.get('top_p', 0.9),
            "stream": True
        }

        response = self.session.post(
            f"{self.base_url}/generate/stream",
            json=payload,
            stream=True
        )

        for line in response.iter_lines():
            if line:
                data = line.decode('utf-8')
                if data.startswith('data: '):
                    json_str = data[6:]
                    if json_str == '[DONE]':
                        break
                    try:
                        yield json.loads(json_str)
                    except:
                        pass

    def chat(self, messages: List[Dict], **kwargs) -> Dict:
        """对话"""
        payload = {
            "messages": messages,
            "temperature": kwargs.get('temperature', 0.7),
            "max_tokens": kwargs.get('max_tokens', 512),
            "stream": False
        }

        response = self.session.post(
            f"{self.base_url}/chat",
            json=payload
        )
        response.raise_for_status()
        return response.json()

    def list_models(self) -> List[Dict]:
        """列出模型"""
        response = self.session.get(f"{self.base_url}/models")
        response.raise_for_status()
        return response.json()


def test_api():
    """测试API服务"""
    print("=" * 60)
    print("🧪 测试本地LLM API服务")
    print("=" * 60)

    client = LLMAPIClient()

    # 1. 健康检查
    print("\n1️⃣ 健康检查...")
    health = client.health_check()
    print(f"📊 状态: {health}")

    if health.get('status') != 'healthy':
        print("❌ 服务未运行，请先启动:")
        print("   python core/ollama_api_server.py")
        return

    # 2. 测试生成
    print("\n2️⃣ 测试文本生成...")
    result = client.generate("介绍一下人工智能", max_tokens=200)
    print(f"✅ 生成结果:\n{result['text'][:150]}...")

    # 3. 测试流式
    print("\n3️⃣ 测试流式生成...")
    print("🔄 流式输出:")
    for chunk in client.generate_stream("讲个笑话", max_tokens=100):
        if 'text' in chunk:
            print(chunk['text'], end='', flush=True)
    print("\n")

    # 4. 测试对话
    print("\n4️⃣ 测试对话...")
    messages = [
        {"role": "user", "content": "1+1等于几？"}
    ]
    result = client.chat(messages)
    print(f"✅ 对话结果: {result.get('message', '')}")

    # 5. 列出模型
    print("\n5️⃣ 可用模型...")
    models = client.list_models()
    print(f"📦 模型列表: {models}")


if __name__ == "__main__":
    test_api()