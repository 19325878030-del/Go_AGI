# my_ai_app/modules/agent/custom_agent.py
import sys
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Callable
import requests

project_root = Path(__file__).parent.parent.parent.parent  # 仓库根 D:\Go_AGI
sys.path.append(str(project_root))

# Windows控制台默认GBK编码，无法打印emoji，强制stdout使用UTF-8
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# 工具元数据与实现分离：启动只扫 manifest（轻量），实现代码由 loader 按需加载
from my_ai_app.modules.agent.tool_registry import ToolRegistry
from my_ai_app.modules.agent.tool_loader import ToolLoader

# 模型无法回答/无法操作时输出的标记文本，
# chat()检测到它就会自动转入"搜索网络信息"兜底流程
CANNOT_ANSWER_MARKER = "<#我无法操作,你可以->#>"

# ==================== 知识库工具（Agent + RAG 并行模式） ====================
# 该工具不在 data/agent_tools/ 注册表里 —— 它没有本地实现文件，
# 实现由调用方通过 knowledge_getter 注入（并行模式下是 RAG 检索器）。
# 所以它只在传了 knowledge_getter 时才出现在系统提示里。
KNOWLEDGE_TOOL_NAME = "rag_search"
KNOWLEDGE_TOOL_SCHEMA = {
    "description": "从本地知识库（上传的文档/规范）中检索相关段落。"
                   "遇到你不确定、或需要依据文档作答的问题时先调用它，"
                   "它是联网搜索（web_search）之前的第一选择。",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词或问题"}
        },
        "required": ["query"],
    },
}


class FunctionCallAgent:
    """
    基于Function Call的Agent实现

    这个Agent模拟了OpenAI的function calling机制，
    让LLM能够自主决定调用哪些工具

    模型接入与"直接对话"同构：统一走 OpenAI 兼容 /chat/completions（ExternalLLMClient）。
    工具调用是提示词约定的JSON协议（见 _build_system_prompt），不依赖任何一家的
    原生 function calling 接口，所以本地 Ollama 与外部大模型（DeepSeek/GLM/千问/Kimi）
    走完全相同的代码路径，区别只在 provider 配置。

    工具集可按请求过滤：chat(tool_packages=[...]) 由前端按工具包勾选，
    每轮只把启用包里的工具写进系统提示；无法操作标记触发的联网兜底
    流程不受过滤影响（那是 Agent 自身的保底行为，不依赖模型选工具）。
    """

    def __init__(self, model_name: str = "qwen2.5:3b", ollama_url: str = "http://localhost:11434",
                 provider: dict = None):
        """
        Args:
            model_name: 本地 Ollama 模型名（未传 provider 时使用）
            ollama_url: 本地 Ollama 根地址（未传 provider 时使用）
            provider: OpenAI 兼容模型配置 {base_url, api_key, model}。
                      传了它就以该模型运行（外部大模型直传其配置；
                      本地 Ollama 也可注册成 base_url=http://localhost:11434/v1
                      的 provider，同一入口）
        """
        self.model_name = model_name
        self.ollama_url = ollama_url

        if provider:
            # 与 llm_provider_service.chat_openai_compatible 用同一份配置结构
            self.provider = {
                "base_url": provider["base_url"],
                "api_key": provider["api_key"],
                "model": provider["model"],
            }
        else:
            # 本地 Ollama：注册成 OpenAI 兼容 /v1 provider（key 仅占位，Ollama 不校验）
            self.provider = {
                "base_url": ollama_url.rstrip('/') + "/v1",
                "api_key": "ollama",
                "model": model_name,
            }

        # 模型调用客户端（OpenAI兼容），复用 core/ 的现成实现
        from core.external_llm_client import ExternalLLMClient
        self._client = ExternalLLMClient(
            base_url=self.provider["base_url"],
            api_key=self.provider["api_key"],
            model=self.provider["model"],
        )

        # 元数据注册表（只扫 manifest，不碰实现代码）+ 按需加载器
        self.registry = ToolRegistry()
        self.loader = ToolLoader(self.registry)
        # 全量工具Schema（系统提示按请求过滤后引用它；模型只感知Schema，不感知实现）
        self.tool_descriptions = self.registry.get_schemas()

        # web_search 包在 manifest 里声明的判空辅助函数（空结果兜底流程用），
        # 首次用到才加载；未声明时兜底流程自动退化为"照常把结果喂回模型"
        self._fallback_helper_info = self.registry.get_fallback_helper()
        self._has_real_results_func = None

        print(f"✅ Agent初始化完成（{self.provider['base_url']} / {self.provider['model']}），"
              f"已注册 {len(self.tool_descriptions)} 个工具")

    @property
    def tools(self):
        """兼容旧属性：已注册的工具名集合（现在工具按需加载，不再持有函数对象）"""
        return self.registry.tool_names

    def _call_model(self, messages: List[Dict], system_prompt: str = None) -> str:
        """调用模型（OpenAI兼容 /chat/completions，本地/外部同一入口）。

        返回回答文本；system_prompt 可传入覆盖（兜底流程用它禁用工具直接回答）。
        """
        if system_prompt is None:
            system_prompt = self._build_system_prompt()

        # max_tokens 给足：Agent 需要先输出工具调用JSON再停下，给小了会被截断
        return self._client.chat(
            [{"role": "system", "content": system_prompt}] + messages,
            temperature=0.3,
            max_tokens=2048,
        )

    # 旧名保留别名：standalone 调试等旧调用点不至于直接 AttributeError
    _call_ollama = _call_model

    def _build_system_prompt(self, with_knowledge_tool: bool = False,
                             tool_packages: List[str] = None) -> str:
        """构建系统提示，描述可用工具。

        tool_packages 非空时只列出这些包里的工具（前端按工具包勾选）；
        None/空列表 = 全部注册的工具。传入的包名应先经
        registry.resolve_package_names 归一化，未知包查不到工具、自然不会出现。

        with_knowledge_tool=True（Agent + RAG 并行模式）时额外声明 rag_search，
        并把"不了解先查知识库、知识库没有再联网"写成明确规则。
        """
        schemas = self.registry.get_schemas(tool_packages)

        tools_desc = []
        if with_knowledge_tool:
            tools_desc.append(f"- {KNOWLEDGE_TOOL_NAME}: {KNOWLEDGE_TOOL_SCHEMA['description']}")
            tools_desc.append(f"  参数: {json.dumps(KNOWLEDGE_TOOL_SCHEMA['parameters'], ensure_ascii=False)}")
        for name, info in schemas.items():
            tools_desc.append(f"- {name}: {info['description']}")
            tools_desc.append(f"  参数: {json.dumps(info['parameters'], ensure_ascii=False)}")

        # 并行模式追加的两条规则：知识库是第一顺位，联网搜索是第二顺位
        kb_rules = ""
        if with_knowledge_tool:
            kb_rules = f"""
6. 【知识库优先】遇到你不确定、或需要依据文档/规范作答的问题，先调用
   {KNOWLEDGE_TOOL_NAME} 查本地知识库，不要直接跳到 web_search；
   知识库确实没有相关内容时，再联网搜索。
7. 知识库返回的内容是权威依据，请据此作答，不要编造库里没有的条款或数字。"""

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

重要规则：
1. 输出工具调用JSON后立即停止，不要输出任何其他内容
2. 绝对不要自己编造工具的返回结果，结果由系统执行工具后提供
3. 如果不需要工具，直接用自然语言回答，不要输出JSON
4. 当你无法回答用户的问题，或者无法执行用户要求的操作时，不要编造答案，
   先输出标记 <#我无法操作,你可以->#>，然后调用 web_search 工具
   去Google或百度上搜索解决方法
5. 先用你已有的知识回答问题，只有知识确实不够时才调用工具；
   不要只回复搜索链接而不给出实质内容{kb_rules}

如果需要多个工具，可以分步调用。"""

    def _fallback_reply(self, user_input: str, result: Any) -> str:
        """
        组装兜底回复：联网搜索已执行但无真实命中时的最终输出。

        搜索没有真实命中时，模型下一轮只会复述兜底链接、给不出实质内容，
        所以这里不再把结果喂回模型，而是确定性地拼出最终回复：
        说明性头部（固定生成，不让模型自由发挥）+ 基于已有知识的回答 + 自查链接。
        内部协议标记 CANNOT_ANSWER_MARKER 只用于循环内检测模型输出，不进用户可见文本。
        """
        ai_answer = self._answer_without_tools(user_input)

        links = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and item.get('link'):
                    links.append(f"- {item.get('title', '链接')}: {item['link']}")

        return (
            "以下回答基于模型已有知识（未联网检索），仅供参考：\n\n"
            f"{ai_answer}\n\n"
            "🔎 点击链接可在浏览器打开该问题的搜索页：\n"
            + "\n".join(links)
        )

    def _answer_without_tools(self, user_input: str) -> str:
        """
        绕过工具直接让AI回答。

        兜底场景使用：web_search 只生成搜索链接、无检索结果可喂回，
        于是换一个不带工具说明的系统提示，让模型凭已有知识尽力回答，
        并附上各引擎的搜索链接供用户自行查阅。
        """
        messages = [{"role": "user", "content": user_input}]
        answer = self._call_model(
            messages,
            system_prompt=(
                "你是一个智能助手。请直接基于你已有的知识回答问题或给出解决思路。"
                "直接给实质内容：不要声明自己无法联网或建议用户去搜索"
                "（系统会自动附上搜索链接），不要输出任何JSON或工具调用。"
            )
        )
        answer = (answer or '').strip()
        return answer if answer else "抱歉，我暂时无法回答这个问题。"

    def _parse_tool_call(self, response: str) -> Dict:
        """
        解析工具调用请求

        逐个扫描文本中的JSON对象，返回第一个含"tool"字段的对象。
        小模型常在工具调用JSON后自行编造"工具返回结果"等其他内容，
        首尾大包围式的提取会整体解析失败，这里必须逐块解析。
        """
        decoder = json.JSONDecoder()
        idx = 0
        while idx < len(response):
            start = response.find('{', idx)
            if start == -1:
                break
            try:
                obj, end = decoder.raw_decode(response[start:])
                if isinstance(obj, dict) and "tool" in obj:
                    return obj
                idx = start + end
            except json.JSONDecodeError:
                idx = start + 1
        return None

    @staticmethod
    def _format_knowledge(kb: Dict) -> str:
        """把知识库检索结果整理成回灌给模型的文本；未命中返回空串"""
        if not kb or not kb.get("found") or not kb.get("context"):
            return ""
        source = kb.get("collection") or "知识库"
        return f"【来源库：{source}】\n{kb['context']}"

    @staticmethod
    def _knowledge_brief(kb: Dict) -> Dict:
        """知识库检索结果的精简版（进 trace 给前端展示，不含整段上下文）"""
        if not kb:
            return {"found": False, "error": "知识库不可用"}
        return {
            "collection": kb.get("collection"),
            "found": bool(kb.get("found")),
            "sources": kb.get("sources", []),
        }

    def _get_has_real_results(self):
        """惰性取"搜索结果判空"辅助函数（manifest 的 fallback_helper 声明）"""
        if self._has_real_results_func is None and self._fallback_helper_info:
            self._has_real_results_func = self.loader.get_helper_function(self._fallback_helper_info)
        return self._has_real_results_func

    def _execute_tool(self, tool_name: str, parameters: Dict) -> Any:
        """执行工具（按需加载实现后调用）"""
        func = self.loader.get_function(tool_name)
        if func is None:
            return f"错误：未知工具 '{tool_name}'"

        try:
            result = func(**parameters)
            return result
        except Exception as e:
            return f"工具执行错误: {str(e)}"

    def chat(self, user_input: str, max_iterations: int = 3, trace: List[Dict] = None,
             knowledge_getter: Callable = None, tool_packages: List[str] = None) -> str:
        """
        与Agent对话

        Args:
            user_input: 用户输入
            max_iterations: 最大迭代次数
            trace: 可选列表，每次工具调用会以
                {"tool": 名称, "parameters": 参数, "result": 结果} 追加进来；
                并行模式下的知识库检索记为 tool="rag_search"、type="rag"
            knowledge_getter: 可选的知识库检索回调 get(query) -> dict | None
                （由 modules/rag/knowledge_bridge.PrefetchKnowledgeSource 提供）。
                不传 = 普通 Agent 模式，行为与原来完全一致
            tool_packages: 本次启用的工具包名列表（前端勾选；display_name 也可）。
                None/空 = 全部包。空列表归一化后一个包都不剩 = 系统提示不列任何
                工具（此时模型不该调工具；真调了会被"未启用"回灌拦下）

        Returns:
            Agent的回答
        """
        # 前端勾选的包名归一化（display_name/包名均可）；None = 不过滤（全部包）
        enabled_packages = self.registry.resolve_package_names(tool_packages)

        use_kb = callable(knowledge_getter)
        messages = [{"role": "user", "content": user_input}]
        iteration = 0
        kb_injected = False   # 本轮是否已回灌过知识库内容（web_search 拦截只做一次）
        asked_queries = set()  # 已问过知识库的关键词，避免同一问题反复检索
        injected_fps = set()   # 已回灌的知识片段指纹，避免重复占用上下文

        def ask_knowledge(query: str):
            """查本地知识库，返回 (kb 结果, 可回灌给模型的文本)。

            文本为空串 = 没有新的可回灌内容（库不可用 / 没命中 / 同一段已灌过），
            此时 kb 仍可能非空（表示"查过了，库里没有"），供调用方决定下一步。
            无论命中与否都记进 trace —— 前端要能看见"先去 rag 了解"这一步。
            """
            nonlocal kb_injected
            if not use_kb:
                return None, ""

            query = (query or "").strip() or user_input
            key = query.lower()
            if key in asked_queries:
                return None, ""
            asked_queries.add(key)

            kb = knowledge_getter(query)
            if trace is not None:
                trace.append({
                    "tool": KNOWLEDGE_TOOL_NAME,
                    "type": "rag",
                    "parameters": {"query": query},
                    "result": self._knowledge_brief(kb),
                })
            if not kb or not kb.get("found") or not kb.get("context"):
                return kb, ""

            fp = hashlib.md5(kb["context"].encode("utf-8")).hexdigest()
            if fp in injected_fps:
                return kb, ""
            injected_fps.add(fp)
            kb_injected = True
            return kb, self._format_knowledge(kb)

        print(f"\n👤 用户: {user_input}")
        if enabled_packages is not None:
            print(f"🧰 工具包: {', '.join(enabled_packages) or '（未启用任何工具包）'}")

        while iteration < max_iterations:
            # 调用模型（OpenAI兼容接口，返回回答文本）
            content = self._call_model(
                messages,
                system_prompt=self._build_system_prompt(
                    with_knowledge_tool=use_kb, tool_packages=enabled_packages),
            ) or ""

            # 检查是否包含工具调用
            tool_call = self._parse_tool_call(content)

            if tool_call and "tool" in tool_call:
                # 执行工具
                tool_name = tool_call["tool"]
                parameters = tool_call.get("parameters", {}) or {}

                # 【并行模式】知识库工具：没有本地实现包，直接走注入的检索器
                if tool_name == KNOWLEDGE_TOOL_NAME:
                    _, inject_text = ask_knowledge(parameters.get("query"))
                    messages.append({"role": "assistant",
                                     "content": json.dumps(tool_call, ensure_ascii=False)})
                    if inject_text:
                        messages.append({
                            "role": "user",
                            "content": (f"[系统] 以下是本地知识库的检索结果：\n\n{inject_text}\n\n"
                                        "（请优先基于这些内容回答，不要再说无法获取）")
                        })
                    else:
                        messages.append({
                            "role": "user",
                            "content": "[系统] 本地知识库中没有检索到相关内容，"
                                       "请改用其它工具，或基于你已有的知识回答。"
                        })
                    iteration += 1
                    continue

                # 模型调了本轮未启用的工具（前端没勾对应包/包不存在）：不加载实现，
                # 把事实回灌，让它改用系统提示里列出的工具或凭已有知识回答。
                # 注意：web_search 拦截与无法操作兜底在后面，不受这里影响。
                if enabled_packages is not None and tool_name not in \
                        self.registry.get_schemas(enabled_packages):
                    messages.append({"role": "assistant",
                                     "content": json.dumps(tool_call, ensure_ascii=False)})
                    messages.append({
                        "role": "user",
                        "content": (f"[系统] 工具 {tool_name} 未启用（本次可用工具"
                                    "以系统提示中列出的为准），请改用列出的工具，"
                                    "或基于你已有的知识回答。")
                    })
                    iteration += 1
                    continue

                # 【并行模式】模型要走联网搜索，说明它不了解 —— 先替它查本地知识库，
                # 命中就用知识库内容作答（"不了解的先去 rag 里了解"），没命中才真去搜
                if tool_name == "web_search" and use_kb and not kb_injected:
                    _, inject_text = ask_knowledge(user_input)
                    if inject_text:
                        print("📚 模型想联网搜索，先改走本地知识库（命中）")
                        messages.append({"role": "assistant",
                                         "content": json.dumps(tool_call, ensure_ascii=False)})
                        messages.append({
                            "role": "user",
                            "content": (f"[系统] 先不用联网 —— 本地知识库里有相关内容：\n\n"
                                        f"{inject_text}\n\n"
                                        "（请优先基于这些内容回答；确实不够再调用 web_search）")
                        })
                        iteration += 1
                        continue

                print(f"🔧 调用工具: {tool_name}")
                print(f"📋 参数: {json.dumps(parameters, ensure_ascii=False)}")

                result = self._execute_tool(tool_name, parameters)
                print(f"📊 结果: {json.dumps(result, ensure_ascii=False)[:200]}...")

                # 记录工具调用轨迹，供Web端展示
                if trace is not None:
                    trace.append({
                        "tool": tool_name,
                        "parameters": parameters,
                        "result": result
                    })

                # 搜索没有真实命中（只剩Google/百度兜底链接或失败提示）时，
                # 不把结果喂回模型——小模型面对空结果只会复述链接，
                # 改为确定性地输出：AI回答在前 + 链接在后
                has_real_results = self._get_has_real_results()
                if tool_name == "web_search" and has_real_results and not has_real_results(result):
                    final_reply = self._fallback_reply(user_input, result)
                    print(f"🤖 Agent: {final_reply}")
                    return final_reply

                # 将工具结果添加到对话历史
                # 注意：存入的是解析出的干净JSON指令，而不是模型原文——
                # 小模型原文里常夹带它自己编造的"工具结果"，混入历史会误导后续轮次
                messages.append({"role": "assistant", "content": json.dumps(tool_call, ensure_ascii=False)})
                # 工具结果用 user 角色回灌并明确标注"系统注入"：
                # OpenAI 兼容接口要求 role=tool 必须带 tool_call_id、assistant 带
                # tool_calls 数组，裸 tool 消息会被外部服务商静默丢弃（本地 Ollama
                # 原生 API 才宽容）——模型收不到结果，只能凭空说"无法获取"。
                messages.append({
                    "role": "user",
                    "content": (f"[系统] 工具 {tool_name} 已执行，返回结果如下"
                                f"（请基于此结果回答，不要再说无法获取）：\n"
                                + json.dumps(result, ensure_ascii=False))
                })

                iteration += 1
                continue

            # 没有工具调用，但模型声明了无法回答/无法操作——
            # 【并行模式】先去 rag 里了解：知识库命中就据其作答；
            # 没命中再走原来的兜底流程（AI 已有知识 + 搜索链接）
            if CANNOT_ANSWER_MARKER in content:
                _, inject_text = ask_knowledge(user_input)
                if inject_text:
                    print("📚 Agent表示无法操作，改由本地知识库作答（命中）")
                    messages.append({
                        "role": "assistant",
                        # 把标记从历史里去掉：否则模型下一轮可能复述它，又触发一次兜底
                        "content": content.replace(CANNOT_ANSWER_MARKER, "").strip()
                                   or "我不确定这个问题的答案。",
                    })
                    messages.append({
                        "role": "user",
                        "content": (f"[系统] 以下是本地知识库的检索结果：\n\n{inject_text}\n\n"
                                    "（请基于这些内容回答，不要再说无法获取）")
                    })
                    iteration += 1
                    continue

                print("🤔 Agent表示无法操作，先用AI直接回答，再附上搜索链接")

                search_query = user_input  # 用原始问题作为搜索词最贴近用户意图
                result = self._execute_tool("web_search", {"query": search_query})
                print(f"📊 搜索结果: {json.dumps(result, ensure_ascii=False)[:200]}...")

                if trace is not None:
                    trace.append({
                        "tool": "web_search",
                        "parameters": {"query": search_query},
                        "result": result
                    })

                final_reply = self._fallback_reply(user_input, result)
                print(f"🤖 Agent: {final_reply}")
                return final_reply

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


def demo_with_knowledge():
    """Agent + RAG 并行模式的自测入口（需本机已建知识库 + Ollama 在跑）。

    用法：python -m my_ai_app.modules.agent.custom_agent "你们公司的报销标准是多少"
    不传问题时进入交互模式。没有调用方注入检索器时走普通 Agent 模式。
    """
    agent = FunctionCallAgent()

    question = " ".join(sys.argv[1:]) or "你好"
    trace = []

    try:
        from my_ai_app.modules.rag.rag_service import RAGService
        from my_ai_app.modules.rag.knowledge_bridge import PrefetchKnowledgeSource

        source = PrefetchKnowledgeSource(RAGService()).start(question)
        getter = source.get
    except Exception as e:
        print(f"⚠️ 知识库不可用，降级为普通 Agent 模式: {e}")
        getter = None

    reply = agent.chat(question, trace=trace, knowledge_getter=getter)
    print(f"\n🤖 回答: {reply}")
    print(f"🔧 轨迹: {json.dumps(trace, ensure_ascii=False, indent=2)}")
    if getter:
        print(f"📚 检索: {json.dumps(source.summary(), ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    # --kb：带知识库的并行模式自测；否则是原来的普通 Agent 交互/单问模式
    if "--kb" in sys.argv:
        sys.argv.remove("--kb")
        demo_with_knowledge()
    else:
        agent = FunctionCallAgent()

        # 命令行参数带问题时逐个提问，否则进入交互模式
        questions = sys.argv[1:]
        if questions:
            for q in questions:
                agent.chat(q)
        else:
            agent.interactive_chat()