# my_ai_app/modules/rag/knowledge_bridge.py
"""
并发知识库桥 —— Agent + RAG 并行模式的粘合层。

Agent 侧只认一个契约：retriever(query) -> dict | None，其中 dict 形如
    {"query", "collection", "found", "context", "sources"}
found=False 表示查到了但库里没有相关内容；返回 None 表示知识库不可用（检索失败）。

本模块解决的是「时序」，不是「检索」（检索本身仍走 RAGService）：
    1. 请求一进来就在后台线程用原始问题预取，与 Agent 的首轮模型调用并发跑 ——
       Agent 中途真要用时结果通常已经就绪，零等待；
    2. Agent 换关键词再问时按需补检索，结果按 query 缓存去重；
    3. 记下每次检索的轨迹（含预取），供接口返回给前端看"并行预取"的效果。

之所以"先预取、后按需取"而不是"先取好再启动 Agent"：检索是本地嵌入（毫秒级），
但真正常见的慢源是模型首轮调用，让两者同时跑才拿得到并行的收益；预取没命中
也只是白算一次嵌入，代价远小于串行等待。
"""
import threading
import time
from concurrent.futures import Future
from typing import Dict, List, Optional

from .rag_service import DEFAULT_K, RAGService

# 预取结果最长等待秒数：超了就当这次预取没赶上，当场再检索一次（不无限拖住 Agent）
DEFAULT_PREFETCH_TIMEOUT = 10.0


def _norm_query(query: str) -> str:
    """查询词归一化：只用于缓存/去重的键，不影响真正发给检索的原词"""
    return " ".join((query or "").split()).lower()


class PrefetchKnowledgeSource:
    """带后台预取的知识库检索源（Agent + RAG 并行模式专用）。

    Args:
        rag_service: 已初始化的 RAGService
        collection_names: 要查的知识库名列表；空/None = 跨本机全部知识库
        k: 每个库检索的 top-k
        timeout: 预取结果最长等待秒数

    用法：
        source = PrefetchKnowledgeSource(rag, names).start(user_message)
        reply = agent.chat(msg, knowledge_getter=source.get)
        source.summary()   # 检索轨迹，回给前端
    """

    def __init__(self, rag_service: RAGService, collection_names=None,
                 k: int = DEFAULT_K, timeout: float = DEFAULT_PREFETCH_TIMEOUT):
        self.rag = rag_service
        # 过滤空串：前端下拉没选中时会传 ""，按"未指定"处理（跨全部库）
        self.collection_names = [c for c in (collection_names or []) if c] or None
        self.k = k
        self.timeout = timeout

        self._prefetch_query = None
        self._future: Optional[Future] = None
        self._cache: Dict[str, Optional[dict]] = {}
        self._lock = threading.Lock()
        # 检索轨迹（含未被用到的预取），供 summary() 返回
        self.retrievals: List[Dict] = []
        # 跨全部库检索时实际扫过的库名（summary 展示用）
        self.scanned_names: Optional[List[str]] = None

    # ==================== 预取 ====================
    def start(self, query: str) -> "PrefetchKnowledgeSource":
        """请求入口调用：开后台线程预取，立刻返回，不阻塞主流程"""
        query = (query or "").strip()
        if not query:
            return self

        self._prefetch_query = query
        self._future = Future()
        threading.Thread(target=self._prefetch_worker, args=(query,),
                         name="rag-prefetch", daemon=True).start()
        return self

    def _prefetch_worker(self, query: str):
        try:
            self._future.set_result(self._retrieve(query, phase="prefetch"))
        except Exception as e:
            # _retrieve 内部已兜住检索异常，这里是最后一道保险（如线程被强杀之外的情况）
            self._future.set_exception(e)

    # ==================== 供 Agent 调用的入口 ====================
    def get(self, query: str = None) -> Optional[dict]:
        """取知识库内容（Agent 的 knowledge_getter 契约入口）。

        query 省略或与预取问题一致 -> 取预取结果（多数情况下已跑完，零等待）；
        换了关键词 -> 当场补一次检索。同一 query 只真正检索一次。
        """
        q = (query or self._prefetch_query or "").strip()
        if not q:
            return None

        key = _norm_query(q)
        with self._lock:
            if key in self._cache:
                return self._cache[key]

        if self._future is not None and key == _norm_query(self._prefetch_query):
            kb = self._await_prefetch()
            if kb is None:
                # 预取超时/失败：不把这次失败缓存下来，当场重试一次
                kb = self._retrieve(q, phase="ondemand")
        else:
            kb = self._retrieve(q, phase="ondemand")

        with self._lock:
            self._cache[key] = kb
        return kb

    def _await_prefetch(self) -> Optional[dict]:
        """等预取结果；超时或异常返回 None（由调用方决定是否当场重试）"""
        try:
            return self._future.result(timeout=self.timeout)
        except Exception as e:
            print(f"⚠️ [并行模式] 知识库预取未取到结果: {e}")
            return None

    # ==================== 实际检索 ====================
    def _retrieve(self, query: str, phase: str = "ondemand") -> Optional[dict]:
        """真正检索一次并记入轨迹；检索失败返回 None，库里无内容返回 found=False"""
        started = time.monotonic()
        try:
            if self.collection_names:
                found, docs, used = self.rag.retrieve_multi(self.collection_names, query, k=self.k)
            else:
                # 未指定库：跨全部库扫一遍（扫过哪些库记下来，summary 里展示）
                self.scanned_names = self.rag.list_collections()
                found, docs, used = self.rag.retrieve_multi(self.scanned_names, query, k=self.k)
        except Exception as e:
            print(f"⚠️ [并行模式] 检索知识库失败: {e}")
            return None

        elapsed_ms = int((time.monotonic() - started) * 1000)
        sources = [
            {
                "content": doc.page_content[:200] + ("..." if len(doc.page_content) > 200 else ""),
                "metadata": doc.metadata,
            }
            for doc in docs
        ]
        kb = {
            "query": query,
            "collection": used,
            "found": bool(docs),
            "context": "\n\n".join(doc.page_content for doc in docs),
            "sources": sources,
        }
        self.retrievals.append({
            "phase": phase,            # prefetch（预取）/ ondemand（Agent 中途再查）
            "query": query,
            "collection": used,
            "found": bool(docs),
            "chunks": len(docs),
            "elapsed_ms": elapsed_ms,
        })
        hit_desc = f"命中 {len(docs)} 段（{used}）" if docs else "无命中"
        print(f"📚 [并行模式/{phase}] 检索「{query}」→ {hit_desc}，耗时 {elapsed_ms}ms")
        return kb

    # ==================== 汇总 ====================
    def summary(self) -> Dict:
        """接口返回用的检索概况。

        含未被 Agent 用到的预取轨迹 —— 预取本就是"先算好、可能用不上"，
        如实返回，前端才能看出并行的实际效果。
        """
        return {
            "collections": self.collection_names or self.scanned_names or [],
            "retrievals": list(self.retrievals),
        }


if __name__ == "__main__":
    print("knowledge_bridge：本模块作为库使用，不提供命令行演示。")
    print("由 app.py 在 Agent+RAG 并行模式下创建 PrefetchKnowledgeSource 并注入 Agent。")
