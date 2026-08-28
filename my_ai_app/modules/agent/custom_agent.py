# my_ai_app/modules/agent/custom_agent.py
import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Callable
import requests

project_root = Path(__file__).parent.parent.parent.parent  # 仓库根 D:\Go_AGI
sys.path.append(str(project_root))

# Windows控制台默认GBK编码，无法打印emoji，强制stdout使用UTF-8
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from my_ai_app.modules.agent.tools import (
    get_current_weather,
    get_weather_forecast,
    calculator,
    convert_units,
    web_search
)


class FunctionCallAgent:
    """
    基于Function Call的Agent实现

    这个Agent模拟了OpenAI的function calling机制，
    让LLM能够自主决定调用哪些工具
    """

    def __init__(self, model_name: str = "qwen2.5:3b", ollama_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.ollama_url = ollama_url
        self.tools = {}  # 工具注册表
        self.tool_descriptions = {}  # 工具描述

        # 注册工具
        self._register_tools()

        print(f"✅ Agent初始化完成，已注册 {len(self.tools)} 个工具")

    def _register_tools(self):
        """注册所有可用工具"""
        tools = {
            "get_weather": {
                "function": get_current_weather,
                "description": "获取当前天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称"
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"],
                            "description": "温度单位",
                            "default": "celsius"
                        }
                    },
                    "required": ["city"]
                }
            },
            "get_forecast": {
                "function": get_weather_forecast,
                "description": "获取天气预报",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称"
                        },
                        "days": {
                            "type": "integer",
                            "description": "预报天数",
                            "minimum": 1,
                            "maximum": 7,
                            "default": 3
                        }
                    },
                    "required": ["city"]
                }
            },
            "calculator": {
                "function": calculator,
                "description": "计算数学表达式",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "数学表达式，如 '2+3*4' 或 'sqrt(16)'"
                        }
                    },
                    "required": ["expression"]
                }
            },
            "convert_units": {
                "function": convert_units,
                "description": "单位转换（长度、温度等）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {
                            "type": "number",
                            "description": "要转换的数值"
                        },
                        "from_unit": {
                            "type": "string",
                            "description": "源单位"
                        },
                        "to_unit": {
                            "type": "string",
                            "description": "目标单位"
                        }
                    },
                    "required": ["value", "from_unit", "to_unit"]
                }
            },
            "web_search": {
                "function": web_search,
                "description": "搜索网络信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "最大结果数",
                            "default": 3
                        }
                    },
                    "required": ["query"]
                }
            }
        }

        self.tools = {name: info["function"] for name, info in tools.items()}
        self.tool_descriptions = {
            name: {
                "description": info["description"],
                "parameters": info["parameters"]
            }
            for name, info in tools.items()
        }

    def _call_ollama(self, messages: List[Dict]) -> Dict:
        """调用Ollama API"""
        url = f"{self.ollama_url}/api/chat"

        # 构建系统提示，告知模型可以使用工具
        system_prompt = self._build_system_prompt()

        payload = {
            "model": self.model_name,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": False,
            "temperature": 0.3
        }

        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def _build_system_prompt(self) -> str:
        """构建系统提示，描述可用工具"""
        tools_desc = []
        for name, info in self.tool_descriptions.items():
            tools_desc.append(f"- {name}: {info['description']}")
            tools_desc.append(f"  参数: {json.dumps(info['parameters'], ensure_ascii=False)}")

        return f"""你是一个智能助手，可以调用工具来帮助回答问题。
你可以使用以下工具：

{chr(10).join(tools_desc)}

当用户的问题需要特定信息时，你应该调用相应的工具。
如果不需要工具，就直接回答用户的问题。

调用工具时，请按以下JSON格式输出：
{{
    "tool": "工具名称",
    "parameters": {{"参数名": "参数值"}}
}}

如果需要多个工具，可以分步调用。"""

    def _parse_tool_call(self, response: str) -> Dict:
        """解析工具调用请求"""
        try:
            # 尝试提取JSON
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                return json.loads(json_str)
        except:
            pass
        return None

    def _execute_tool(self, tool_name: str, parameters: Dict) -> Any:
        """执行工具"""
        if tool_name not in self.tools:
            return f"错误：未知工具 '{tool_name}'"

        try:
            result = self.tools[tool_name](**parameters)
            return result
        except Exception as e:
            return f"工具执行错误: {str(e)}"

    def chat(self, user_input: str, max_iterations: int = 3) -> str:
        """
        与Agent对话

        Args:
            user_input: 用户输入
            max_iterations: 最大迭代次数

        Returns:
            Agent的回答
        """
        messages = [{"role": "user", "content": user_input}]
        iteration = 0

        print(f"\n👤 用户: {user_input}")

        while iteration < max_iterations:
            # 调用模型
            response = self._call_ollama(messages)
            assistant_message = response.get("message", {})
            content = assistant_message.get("content", "")

            # 检查是否包含工具调用
            tool_call = self._parse_tool_call(content)

            if tool_call and "tool" in tool_call:
                # 执行工具
                tool_name = tool_call["tool"]
                parameters = tool_call.get("parameters", {})

                print(f"🔧 调用工具: {tool_name}")
                print(f"📋 参数: {json.dumps(parameters, ensure_ascii=False)}")

                result = self._execute_tool(tool_name, parameters)
                print(f"📊 结果: {json.dumps(result, ensure_ascii=False)[:200]}...")

                # 将工具结果添加到对话历史
                messages.append(assistant_message)
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result, ensure_ascii=False)
                })

                iteration += 1
                continue

            # 没有工具调用，直接回答
            print(f"🤖 Agent: {content}")
            return content

        return "达到最大迭代次数，请简化您的问题。"

    def interactive_chat(self):
        """交互式对话模式"""
        print("\n" + "=" * 60)
        print("🤖 Agent 交互模式")
        print("=" * 60)
        print("可用工具: 天气查询、计算器、单位转换、网络搜索")
        print("输入 'quit' 退出")
        print("=" * 60 + "\n")

        while True:
            try:
                user_input = input("👤 请输入问题: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n👋 再见！")
                break

            if user_input.lower() in ['quit', 'exit', 'q']:
                print("👋 再见！")
                break

            if not user_input:
                continue

            try:
                self.chat(user_input)
            except Exception as e:
                print(f"❌ 错误: {e}")


if __name__ == "__main__":
    agent = FunctionCallAgent()

    # 命令行参数带问题时逐个提问，否则进入交互模式
    questions = sys.argv[1:]
    if questions:
        for q in questions:
            agent.chat(q)
    else:
        agent.interactive_chat()