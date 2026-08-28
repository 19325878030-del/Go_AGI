# my_ai_app/test_ollama.py
import requests
import json

# Ollama API 端点
OLLAMA_URL = "http://localhost:11434/api/generate"


def test_ollama_basic():
    """测试Ollama基础调用"""
    payload = {
        "model": "qwen2.5:3b",  # 替换成你下载的模型名
        "prompt": "你好，请介绍一下你自己",
        "stream": False  # 非流式输出
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        result = response.json()
        print("✅ 调用成功！")
        print(f"回答: {result['response']}")
        print(f"耗时: {result.get('total_duration', 0)} 纳秒")
    except Exception as e:
        print(f"❌ 调用失败: {e}")


def test_ollama_stream():
    """测试流式输出"""
    payload = {
        "model": "qwen2.5:3b",
        "prompt": "写一首关于春天的诗",
        "stream": True
    }

    print("🔄 流式输出:")
    try:
        response = requests.post(OLLAMA_URL, json=payload, stream=True)
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                print(data.get('response', ''), end='', flush=True)
                if data.get('done', False):
                    print("\n✅ 完成！")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print("测试1: 基础调用")
    print("=" * 50)
    test_ollama_basic()

    print("\n" + "=" * 50)
    print("测试2: 流式调用")
    print("=" * 50)
    test_ollama_stream()