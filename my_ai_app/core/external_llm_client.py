# my_ai_app/core/external_llm_client.py
"""
外部大模型API客户端（OpenAI兼容格式）
适用于DeepSeek / 智谱GLM / 通义千问 / Kimi 等兼容OpenAI接口的服务商
"""
import os
import sys
import requests
from typing import Dict, List

# Windows控制台默认GBK编码，无法打印emoji，强制stdout使用UTF-8
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


class ExternalLLMClient:
    """OpenAI兼容格式的外部大模型客户端"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip('/')  # 去掉末尾斜杠，防止拼出 //chat/completions
        self.model = model

        # 复用同一个Session：多次请求共用TCP连接，不用反复握手
        self.session = requests.Session()

        # 鉴权头：OpenAI兼容接口统一用 "Bearer <key>" 方式
        # 设置进session后，之后每个请求都自动带上，不用每次手写
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        })

    def chat(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 1024) -> str:
        """
        对话接口，返回模型回答的纯文本

        Args:
            messages: OpenAI格式消息列表，如 [{"role": "user", "content": "你好"}]
        """
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,   # 限制输出长度，外部按token计费，别让它写起来没完
            "stream": False
        }

        response = self.session.post(url, json=payload, timeout=60)

        # 常见错误码单独给提示，比裸抛异常好排查
        if response.status_code == 401:
            raise RuntimeError("API Key无效，请检查Key是否复制完整")
        if response.status_code == 429:
            raise RuntimeError("请求过快或余额不足，请稍后重试或检查账户余额")
        response.raise_for_status()  # 其余错误码统一抛HTTPError

        data = response.json()

        # OpenAI兼容格式的取值路径：choices[0].message.content
        # 和Ollama的 result["response"] 完全不同，这是最容易搞错的地方
        content = data["choices"][0]["message"]["content"]

        # usage记录了token消耗，打出来对花了多少钱心里有数
        usage = data.get("usage", {})
        print(f"💰 本次消耗: 输入{usage.get('prompt_tokens', '?')} + "
              f"输出{usage.get('completion_tokens', '?')} tokens")

        return content


def test_client():
    """测试外部模型API"""
    print("=" * 60)
    print("🧪 测试外部大模型API（DeepSeek）")
    print("=" * 60)

    # 从环境变量读Key，绝不硬编码——写死的key一旦提交到git就泄露了
    api_key =os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("❌ 未找到API Key，请先设置环境变量 DEEPSEEK_API_KEY")
        return

    client = ExternalLLMClient(
        base_url="https://api.deepseek.com",
        api_key=api_key,
        model="deepseek-chat"
    )

    print("\n1️⃣ 测试对话...")
    messages = [{"role": "user", "content": "用一句话介绍你自己"}]
    answer = client.chat(messages)
    print(f"✅ 回答: {answer}")


if __name__ == "__main__":
    test_client()
