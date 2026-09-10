# 验证：Agent + RAG 并行模式（不依赖 Ollama / Chroma / 网络）
# 运行: python my_ai_app/tests/verify_parallel_mode.py
#
# 验证五件事：
#   1. 预取真的和 Agent 首轮模型调用并发跑（模型已在跑时检索还没结束）
#   2. Agent 想联网搜索时，先改走本地知识库（命中就不搜），"不了解先去 rag 了解"
#   3. 知识库没命中时才真的联网搜索（原有兜底流程不受影响）
#   4. 模型直接调用 rag_search / 输出无法操作标记时，都先查知识库
#   5. 不传 knowledge_getter 时 = 普通 Agent 模式，行为与改造前一致
#   6. 跨库检索取"最优库"（谁的最佳距离最小用谁）
#   7. tool_packages 勾选过滤：系统提示只列启用包的工具，未启用工具被拦下
import sys
import threading
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\Go_AGI')
# agent 内部按 "from core.xxx import" 引包（app.py 启动时会把 my_ai_app/ 加进 path），
# 脚本单独跑时也要补上，否则 import core 失败
sys.path.insert(0, r'D:\Go_AGI\my_ai_app')

from my_ai_app.modules.rag.knowledge_bridge import PrefetchKnowledgeSource
from my_ai_app.modules.agent.custom_agent import FunctionCallAgent, CANNOT_ANSWER_MARKER


# ==================== 测试替身 ====================
class StubDoc:
    """假文档：只带 _retrieve/_format_knowledge 用到的两个属性"""

    def __init__(self, text, source="制度.txt"):
        self.page_content = text
        self.metadata = {"source_file": source}


class FakeRAG:
    """假向量库：不碰 Ollama / Chroma，按预设返回命中或未命中"""

    def __init__(self, found=True, text="公司差旅报销标准为每人每天300元。",
                 delay=0.0, timeline=None, lock=None):
        self.found = found
        self.text = text
        self.delay = delay
        self.timeline = timeline if timeline is not None else []
        self.lock = lock or threading.Lock()
        self.retrieve_calls = []   # 记录每次 retrieve_multi 的入参（验证缓存/去重）

    def _mark(self, event):
        with self.lock:
            self.timeline.append((event, time.monotonic()))

    def list_collections(self):
        return [{"name": "kb-1", "display_name": "公司制度", "count": 3}]

    def retrieve_multi(self, names, query, k=3):
        self._mark("rag_start")
        self.retrieve_calls.append(query)
        if self.delay:
            time.sleep(self.delay)      # 模拟慢检索，用来观察并发
        self._mark("rag_end")
        if not self.found:
            return False, [], None
        return True, [StubDoc(self.text)], "kb-1"


class ScriptedAgent(FunctionCallAgent):
    """按脚本逐轮返回模型输出，并记录每轮收到的消息（不连任何模型服务）"""

    def __init__(self, replies, timeline=None, lock=None):
        super().__init__(model_name="stub-model")   # 只构造客户端，不发请求
        self._replies = list(replies)
        self.calls = []
        self.timeline = timeline if timeline is not None else []
        self.lock = lock or threading.Lock()

    def _call_model(self, messages, system_prompt=None):
        with self.lock:
            self.timeline.append(("model_call", time.monotonic()))
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "system_prompt": system_prompt or "",
        })
        return self._replies.pop(0) if self._replies else "（脚本回复已用尽）"

    # ---- 断言辅助 ----
    def tools_in_trace(self, trace):
        return [s["tool"] for s in trace]

    def last_messages_text(self):
        return "\n".join(m["content"] for m in self.calls[-1]["messages"])


def check(cond, msg):
    assert cond, f"❌ {msg}"
    print(f"   ✓ {msg}")


def first_at(timeline, event):
    """取事件首次发生的时间戳（timeline 可能含重复事件名，不能直接 dict()）"""
    for name, ts in timeline:
        if name == event:
            return ts
    raise AssertionError(f"事件未发生: {event}")


def wait_for(timeline, event, timeout=5.0):
    """等某个事件出现（预取在后台线程里，主线程可能先跑完）"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(name == event for name, _ in timeline):
            return
        time.sleep(0.01)
    raise AssertionError(f"等待事件超时: {event}")


def main():
    print("=" * 70)
    print("🧪 Agent + RAG 并行模式验证（离线，不连 Ollama/Chroma）")
    print("=" * 70)

    # ---------- 1) 预取与首轮模型调用并发 ----------
    print("\n1️⃣ 预取与 Agent 首轮模型调用并发（不串行等待）")
    timeline, lock = [], threading.Lock()
    rag = FakeRAG(found=True, delay=0.4, timeline=timeline, lock=lock)
    source = PrefetchKnowledgeSource(rag, collection_names=["公司制度"]).start("报销标准是多少")
    agent = ScriptedAgent(["直接回答即可"], timeline=timeline, lock=lock)
    agent.chat("报销标准是多少", trace=[], knowledge_getter=source.get)
    wait_for(timeline, "rag_end")   # 预取在后台线程，等它收尾再断言时序

    rag_start = first_at(timeline, "rag_start")
    rag_end = first_at(timeline, "rag_end")
    model_call = first_at(timeline, "model_call")
    check(rag_end - rag_start > 0.3,
          f"检索确实耗时约0.4s（实测 {rag_end - rag_start:.3f}s）")
    check(model_call < rag_end,
          f"模型首轮调用({model_call - rag_start:.3f}s)早于检索结束"
          f"({rag_end - rag_start:.3f}s) —— 模型没有等检索，两者并发")

    # 预取结果被复用：Agent 用到时不再重复检索
    rag2 = FakeRAG(found=True)
    src2 = PrefetchKnowledgeSource(rag2, collection_names=["公司制度"]).start("同一个问题")
    for _ in range(3):
        kb = src2.get("同一个问题")
    check(len(rag2.retrieve_calls) == 1 and kb["found"],
          f"同一问题重复取用只真正检索了一次（实际 {len(rag2.retrieve_calls)} 次）")

    # ---------- 2) 想联网搜索 → 先走知识库 ----------
    print("\n2️⃣ Agent 想联网搜索时，先改走本地知识库（命中即不搜）")
    agent = ScriptedAgent([
        '{"tool": "web_search", "parameters": {"query": "报销标准"}}',
        "根据公司制度，差旅报销标准为每人每天300元。",
    ])
    trace = []
    rag = FakeRAG(found=True, text="公司差旅报销标准为每人每天300元。")
    source = PrefetchKnowledgeSource(rag, collection_names=["公司制度"]).start("报销标准是多少")
    reply = agent.chat("报销标准是多少", trace=trace, knowledge_getter=source.get)

    check(reply == "根据公司制度，差旅报销标准为每人每天300元。", "用知识库内容作答")
    check(agent.tools_in_trace(trace) == ["rag_search"],
          f"轨迹里只有知识库检索、没有联网搜索: {agent.tools_in_trace(trace)}")
    check(trace[0]["type"] == "rag" and trace[0]["result"]["found"] is True,
          "知识库检索轨迹标记 type=rag 且 found=True")
    check("公司差旅报销标准为每人每天300元" in agent.last_messages_text(),
          "知识库原文已回灌进对话历史")
    check("先不用联网" in agent.last_messages_text(), "并明确告知模型不必联网")

    # ---------- 3) 知识库没命中 → 真的联网搜索 ----------
    print("\n3️⃣ 知识库未命中时才真的联网搜索（原兜底流程不变）")
    agent = ScriptedAgent([
        '{"tool": "web_search", "parameters": {"query": "报销标准"}}',
        "凭已有知识给出的回答",
    ])
    trace = []
    rag = FakeRAG(found=False)
    source = PrefetchKnowledgeSource(rag, collection_names=["公司制度"]).start("报销标准是多少")
    reply = agent.chat("报销标准是多少", trace=trace, knowledge_getter=source.get)
    tools = agent.tools_in_trace(trace)

    check(tools == ["rag_search", "web_search"], f"先查知识库再联网: {tools}")
    check(trace[0]["result"]["found"] is False, "知识库这一步如实记录未命中")
    # web_search 本实现只产出兜底链接 → 走 _fallback_reply（AI回答 + 链接）
    check("凭已有知识给出的回答" in reply and "google.com/search" in reply,
          "未命中时走原有兜底回复（已有知识 + 搜索链接）")

    # ---------- 4) 模型主动调 rag_search / 声明无法操作 ----------
    print("\n4️⃣ 模型直接调 rag_search、或声明无法操作时，都先查知识库")
    agent = ScriptedAgent([
        '{"tool": "rag_search", "parameters": {"query": "报销标准"}}',
        "制度里写的是每人每天300元。",
    ])
    trace = []
    rag = FakeRAG(found=True, text="差旅报销标准：每人每天300元。")
    source = PrefetchKnowledgeSource(rag, collection_names=["公司制度"]).start("报销多少")
    reply = agent.chat("报销多少", trace=trace, knowledge_getter=source.get)
    check(reply == "制度里写的是每人每天300元。", "模型主动查库后据其作答")
    check("【来源库：kb-1】" in agent.last_messages_text(), "回灌内容带来源库标注")
    check("rag_search" in agent.calls[0]["system_prompt"],
          "系统提示里声明了 rag_search 工具")

    agent = ScriptedAgent([
        f"{CANNOT_ANSWER_MARKER}",
        "按制度，每人每天300元。",
    ])
    trace = []
    rag = FakeRAG(found=True, text="差旅报销标准：每人每天300元。")
    source = PrefetchKnowledgeSource(rag, collection_names=["公司制度"]).start("报销多少")
    reply = agent.chat("报销多少", trace=trace, knowledge_getter=source.get)
    check(reply == "按制度，每人每天300元。", "声明无法操作后改用知识库作答")
    check(agent.tools_in_trace(trace) == ["rag_search"],
          "没有直接跳到联网搜索兜底")
    check(CANNOT_ANSWER_MARKER not in agent.calls[-1]["messages"][0]["content"],
          "重灌历史时剥离了无法操作标记（防止再次触发兜底）")

    # ---------- 5) 不传检索器 = 普通 Agent 模式 ----------
    print("\n5️⃣ 不传 knowledge_getter 时行为与改造前一致")
    agent = ScriptedAgent([
        '{"tool": "web_search", "parameters": {"query": "天气"}}',
        "已给出回答",
    ])
    trace = []
    agent.chat("查一下天气", trace=trace)
    check("rag_search" not in agent.calls[0]["system_prompt"],
          "系统提示里没有 rag_search（不声明不存在的工具）")
    check("知识库优先" not in agent.calls[0]["system_prompt"],
          "系统提示里没有知识库优先规则")
    check(agent.tools_in_trace(trace) == ["web_search"],
          "web_search 未被拦截，照常执行")

    # ---------- 6) 跨库检索取最优库 ----------
    print("\n6️⃣ 跨库检索：取最佳距离最小的那个库")
    from my_ai_app.modules.rag.rag_service import RAGService

    rag = RAGService.__new__(RAGService)     # 跳过 __init__：不初始化嵌入模型
    rag.distance_threshold = 1.0

    def fake_scored(name, query, k=3):
        """a 库距离 0.9（勉强），b 库距离 0.2（更贴题）"""
        return {"a": [(StubDoc("a的内容"), 0.9)],
                "b": [(StubDoc("b的内容"), 0.2)],
                "c": []}[name]

    rag.retrieve_scored = fake_scored
    found, docs, used = rag.retrieve_multi(["a", "b", "c"], "问题")
    check(found and used == "b", f"命中距离最小的库: {used}")
    check(docs[0].page_content == "b的内容", "返回该库的原文（不混拼多库片段）")

    rag.retrieve_scored = lambda name, query, k=3: []
    check(rag.retrieve_multi(["a", "b"], "问题") == (False, [], None),
          "全部库都没命中时返回 (False, [], None)")

    # ---------- 7) tool_packages 勾选过滤 ----------
    print("\n7️⃣ 工具包勾选：系统提示只列启用包，未启用工具调用被拦下")
    agent = ScriptedAgent([
        '{"tool": "calculator", "parameters": {"expression": "1+1"}}',
        "好的，我直接回答。",
    ])
    trace = []
    # 只勾 weather（display_name 也可），calculator 不在系统提示里
    agent.chat("算一下1+1，顺便查天气", trace=trace, tool_packages=["天气查询"])
    check("calculator" not in agent.calls[0]["system_prompt"],
          "未勾选包的工具没进系统提示")
    check("get_weather" in agent.calls[0]["system_prompt"],
          "勾选包的工具在系统提示里")
    check(agent.tools_in_trace(trace) == [],
          f"未启用工具未被执行（轨迹为空）: {agent.tools_in_trace(trace)}")
    check("工具 calculator 未启用" in agent.last_messages_text(),
          "模型收到'工具未启用'回灌")
    check("calculator" not in agent.calls[1]["system_prompt"],
          "下一轮系统提示仍保持过滤")

    # 不传 tool_packages = 全部包可用（老调用方行为不变）
    agent = ScriptedAgent(["不需要工具，直接答。"])
    agent.chat("随便问问", trace=[])
    check("calculator" in agent.calls[0]["system_prompt"],
          "不传 tool_packages 时全部工具照常声明")

    print("\n" + "=" * 70)
    print("✅ 全部通过：并行预取、知识库优先、未命中回落、普通模式兼容、跨库选优、工具包过滤")
    print("=" * 70)


if __name__ == "__main__":
    main()
