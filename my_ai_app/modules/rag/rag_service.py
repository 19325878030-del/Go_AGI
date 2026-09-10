# my_ai_app/modules/rag/rag_service.py
"""
模型无关的 RAG 服务。

向量库（知识库）按名字管理（Chroma collection），由前端通过 collection_name 参数指定；
问答生成所用的模型由调用方注入 `generate(prompt) -> str` 回调（本地 Ollama 或外部大模型均可，
统一走 app 层 llm_provider_service.chat_openai_compatible），本模块不持有任何 LLM。

向量库检索仍依赖本地 Ollama 嵌入模型（默认 nomic-embed-text）。
"""
import sys
from pathlib import Path

import chromadb
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings

# 向量库生成工具（rag_ingest.py）的库名规范化：中文等库名建库时会被 slug 化
from .rag_ingest import slug_collection_name

# Windows控制台默认GBK编码，无法打印emoji，强制stdout使用UTF-8
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 知识库中未检索到相关内容时，直接回答前加的标注
NOT_FOUND_TAG = "<#未能在标准中找到#>"

# Ollama 嵌入服务（仅检索用；生成模型由调用方决定，不在此配置）
OLLAMA_BASE = "http://localhost:11434"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
# my_ai_app/data/chroma_db（模块位于 my_ai_app/modules/rag/）
DEFAULT_PERSIST_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "chroma_db")

DEFAULT_DISTANCE_THRESHOLD = 1.0  # L2距离阈值，最佳结果距离超过它即视为库中无相关内容
DEFAULT_K = 3                     # 默认检索 top-k

# 检索命中后拼接给生成模型的提示模板（沿用原 demo 模板）
QA_TEMPLATE = """你是一个专业的问答助手。请回答用户的问题。

如果下面的上下文信息中有相关内容，请基于上下文回答。
如果上下文中没有相关信息，请用你自己的知识正常回答，不要说"我不知道"。

上下文信息：
{context}

问题：{question}

请用中文回答，回答要准确、简洁、有帮助："""


class RAGService:
    """命名向量库检索 + 注入式生成的 RAG 服务。

    Args:
        persist_dir: Chroma 持久化目录；缺省 my_ai_app/data/chroma_db
        embedding_model: 本地 Ollama 嵌入模型名（建库/检索共用，需一致）
        distance_threshold: L2 距离阈值；最佳检索结果距离超过该值视为库中无相关内容
    """

    def __init__(self,
                 persist_dir: str = None,
                 embedding_model: str = DEFAULT_EMBEDDING_MODEL,
                 distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD):
        self.persist_dir = persist_dir or DEFAULT_PERSIST_DIR
        self.embedding_model = embedding_model
        self.distance_threshold = distance_threshold

        # trust_env=False：绕开系统代理，否则 httpx 会把 localhost 请求发给代理导致连接被拒
        self.embeddings = OllamaEmbeddings(
            model=embedding_model,
            base_url=OLLAMA_BASE,
            client_kwargs={'trust_env': False}
        )

    # ==================== 向量库（命名集合）管理 ====================
    def _client(self) -> chromadb.PersistentClient:
        return chromadb.PersistentClient(path=self.persist_dir)

    def list_collections(self) -> list:
        """本机已有知识库名列表（按名排序）；读取失败返回空列表"""
        try:
            return sorted(c.name for c in self._client().list_collections())
        except Exception as e:
            print(f"⚠️ 列出向量库失败: {e}")
            return []

    def collection_exists(self, collection_name: str) -> bool:
        """指定名称的知识库是否存在。

        入参可以是原始库名（中文）或已 slug 化的合法集合名 —— 后者幂等，前者会被
        slug_collection_name 映射到建库时的实际集合名（见 rag_ingest.py）。
        """
        try:
            self._client().get_collection(name=slug_collection_name(collection_name))
            return True
        except Exception:
            return False

    def _load_vectorstore(self, collection_name: str):
        """加载指定集合的 langchain Chroma 向量库（调用方需先确认集合存在）。

        collection_name 先过 slug_collection_name 规范化，保证中文库名也能定位
        到 rag_ingest 建库时的同一集合。
        """
        return Chroma(
            persist_directory=self.persist_dir,
            embedding_function=self.embeddings,
            collection_name=slug_collection_name(collection_name),
        )

    # ==================== 检索 ====================
    def retrieve(self, collection_name: str, query: str, k: int = DEFAULT_K):
        """按距离阈值检索，返回 (是否命中知识库, 命中文档列表)

        Chroma 的 similarity_search_with_score 返回 (embedding距离, 文档)，
        距离越小越相似；最佳结果的距离仍超过阈值时视为知识库中无相关内容。
        """
        if not self.collection_exists(collection_name):
            raise ValueError(f"知识库（向量库）不存在: {collection_name}")

        vectorstore = self._load_vectorstore(collection_name)
        if vectorstore._collection.count() == 0:
            return False, []

        results = vectorstore.similarity_search_with_score(query, k=k)
        if results:
            best_distance = results[0][1]
            print(f"📏 最佳检索距离: {best_distance:.4f}（阈值: {self.distance_threshold}）")

        docs = [
            doc for doc, distance in results
            if distance <= self.distance_threshold
        ]
        return (len(docs) > 0), docs

    # ==================== 问答 ====================
    def ask(self, collection_name: str, question: str, generate, k: int = DEFAULT_K) -> dict:
        """基于命名向量库回答。

        Args:
            collection_name: 知识库（向量库）名
            question: 用户问题
            generate: 生成回调 generate(prompt: str) -> str，绑定调用方选定的生成模型
            k: 检索 top-k

        Returns:
            {"question", "answer", "sources"}
        """
        found, docs = self.retrieve(collection_name, question, k=k)

        if not found:
            # 未命中知识库：模型直接回答，并在前面加标注
            answer = NOT_FOUND_TAG + generate(question)
            sources = []
        else:
            context = "\n\n".join(doc.page_content for doc in docs)
            prompt = QA_TEMPLATE.format(context=context, question=question)
            answer = generate(prompt)
            sources = [
                {
                    "content": doc.page_content[:200] + ("..." if len(doc.page_content) > 200 else ""),
                    "metadata": doc.metadata,
                }
                for doc in docs
            ]

        return {"question": question, "answer": answer, "sources": sources}


if __name__ == "__main__":
    print("RAGService：本模块作为库使用，不提供命令行演示。")
    print("由 app 层绑定生成模型（本地/外部）后调用 rag.ask(collection_name, question, generate)。")
