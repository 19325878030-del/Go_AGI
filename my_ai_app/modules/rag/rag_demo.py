# my_ai_app/modules/rag/rag_demo.py
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

# Windows控制台默认GBK编码，无法打印emoji，强制stdout使用UTF-8
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_classic.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 知识库中未检索到相关内容时，直接回答前加的标注
NOT_FOUND_TAG = "<#未能在标准中找到#>"


class RAGSystem:
    """基于LangChain的RAG系统"""

    def __init__(self,
                 model_name: str = "qwen2.5:3b",
                 persist_dir: str = None,
                 embedding_model: str = "nomic-embed-text",
                 distance_threshold: float = 1.0):
        """
        初始化RAG系统

        Args:
            model_name: Ollama模型名称
            persist_dir: 向量数据库持久化目录
            embedding_model: Ollama嵌入模型名称
            distance_threshold: L2距离阈值，最佳检索结果的距离超过该值即视为知识库中无相关内容
                （Chroma默认L2距离，范围约0~2，越小越相似；需根据日志中的实际距离调整）
        """
        self.model_name = model_name
        self.persist_dir = persist_dir or str(project_root / "data" / "chroma_db")
        self.embedding_model = embedding_model
        self.distance_threshold = distance_threshold

        # 初始化LLM（嵌入与生成均走Ollama，Python侧不加载本地模型，节省内存）
        # trust_env=False：绕开系统代理，否则httpx会把localhost请求发给代理导致连接被拒
        self.llm = OllamaLLM(
            model=model_name,
            temperature=0.7,
            base_url="http://localhost:11434",
            client_kwargs={'trust_env': False}
        )

        # 初始化嵌入模型
        self.embeddings = OllamaEmbeddings(
            model=embedding_model,
            base_url="http://localhost:11434",
            client_kwargs={'trust_env': False}
        )

        # 初始化向量数据库
        self.vectorstore = None
        self.qa_chain = None

        logger.info(f"✅ RAG系统初始化完成，使用模型: {model_name}")

    def load_documents(self, file_path: str):
        """加载文档"""
        logger.info(f"📄 加载文档: {file_path}")

        # 根据文件类型选择加载器
        if file_path.endswith('.txt'):
            loader = TextLoader(file_path, encoding='utf-8')
        else:
            raise ValueError(f"不支持的文件类型: {file_path}")

        documents = loader.load()
        logger.info(f"✅ 成功加载 {len(documents)} 个文档")
        return documents

    def split_documents(self, documents, chunk_size: int = 500, chunk_overlap: int = 50):
        """文档切片"""
        logger.info(f"✂️ 开始文档切片，chunk_size={chunk_size}, overlap={chunk_overlap}")

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]
        )

        chunks = text_splitter.split_documents(documents)
        logger.info(f"✅ 生成 {len(chunks)} 个文本块")
        return chunks

    def create_vectorstore(self, documents, collection_name: str = "rag_collection"):
        """创建向量数据库"""
        logger.info(f"🗄️ 创建向量数据库，collection: {collection_name}")

        # 先切片
        chunks = self.split_documents(documents)

        # 清理同名旧集合：重复运行会不断追加切片，导致检索结果重复
        try:
            Chroma(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings,
                collection_name=collection_name,
            ).delete_collection()
        except Exception:
            pass  # 首次运行，集合不存在

        # 创建向量数据库
        self.vectorstore = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=self.persist_dir,
            collection_name=collection_name
        )

        # Chroma 0.4+ 已自动持久化，无需手动调用 persist()
        logger.info(f"✅ 向量数据库已保存到: {self.persist_dir}")

        return self.vectorstore

    def load_vectorstore(self, collection_name: str = "rag_collection"):
        """加载已有的向量数据库"""
        logger.info(f"📂 加载向量数据库: {collection_name}")

        self.vectorstore = Chroma(
            persist_directory=self.persist_dir,
            embedding_function=self.embeddings,
            collection_name=collection_name
        )

        logger.info(f"✅ 向量数据库加载成功")
        return self.vectorstore

    def collection_size(self) -> int:
        """当前集合中的切片数量；集合为空或读取失败返回0（视为需要重建）"""
        try:
            return self.vectorstore._collection.count()
        except Exception:
            return 0

    def retrieve(self, question: str, k: int = 3):
        """按L2距离阈值检索相关文档，返回(是否命中知识库, 文档列表)

        Chroma的similarity_search_with_score返回(embedding距离, 文档)，
        距离越小越相似；最佳结果的距离仍超过阈值时视为知识库中无相关内容。
        """
        results = self.vectorstore.similarity_search_with_score(question, k=k)

        if results:
            best_distance = results[0][1]
            logger.info(f"📏 最佳检索距离: {best_distance:.4f}（阈值: {self.distance_threshold}）")

        docs = [
            doc for doc, distance in results
            if distance <= self.distance_threshold
        ]
        return (len(docs) > 0), docs

    def setup_qa_chain(self, k: int = 3):
        """设置问答链"""
        if not self.vectorstore:
            raise ValueError("请先创建或加载向量数据库")

        logger.info(f"🔧 设置问答链，检索top-{k}个相关文档")

        # 自定义提示模板
        template = """你是一个专业的问答助手。请回答用户的问题。

        如果下面的上下文信息中有相关内容，请基于上下文回答。
        如果上下文中没有相关信息，请用你自己的知识正常回答，不要说"我不知道"。

        上下文信息：
        {context}

        问题：{question}

        请用中文回答，回答要准确、简洁、有帮助："""

        QA_PROMPT = PromptTemplate(
            template=template,
            input_variables=["context", "question"]
        )

        # 创建检索器
        retriever = self.vectorstore.as_retriever(
            search_kwargs={"k": k}
        )

        # 创建问答链
        self.qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=retriever,
            chain_type_kwargs={"prompt": QA_PROMPT},
            return_source_documents=True
        )

        logger.info(f"✅ 问答链设置完成")
        return self.qa_chain

    def ask(self, question: str) -> dict:
        """提问"""
        if not self.qa_chain:
            raise ValueError("请先设置问答链")

        # 先按阈值检索，判断知识库中是否有相关内容
        found, docs = self.retrieve(question, k=3)

        if found:
            # 命中知识库：走RAG问答链，答案基于检索到的上下文
            result = self.qa_chain.invoke({"query": question})
            answer = result['result']
            sources = result.get('source_documents', [])
        else:
            # 未命中知识库：模型直接回答，并在前面加标注
            answer = NOT_FOUND_TAG + self.llm.invoke(question)
            sources = []

        return {
            "question": question,
            "answer": answer,
            "sources": [
                {
                    "content": doc.page_content[:200] + "...",
                    "metadata": doc.metadata
                }
                for doc in sources
            ]
        }


def demo():
    """演示RAG系统"""
    print("=" * 60)
    print("🚀 RAG系统演示")
    print("=" * 60)

    # 1. 创建RAG系统
    rag = RAGSystem(model_name="qwen2.5:3b")

    # 2. 准备示例文档
    sample_data_path = project_root / "data" / "sample.txt"

    # 示例文档自动创建已注释：sample.txt 已存在，防止重复写入覆盖手工内容
    # 如需重新生成示例文档：删除 data/sample.txt 后取消下面整段注释
    # if not sample_data_path.exists():
    #     sample_data_path.parent.mkdir(parents=True, exist_ok=True)
    #     with open(sample_data_path, 'w', encoding='utf-8') as f:
    #         f.write("""人工智能发展简史
    #
    # 人工智能（Artificial Intelligence，简称AI）是计算机科学的一个重要分支。
    #
    # 1950年，艾伦·图灵提出了"图灵测试"，用来判断机器是否具有智能。
    #
    # 1956年，达特茅斯会议正式确立了"人工智能"这一学科。
    #
    # 人工智能的发展经历了几个阶段：
    # 1. 早期探索期（1956-1974）：主要研究符号推理和问题求解
    # 2. 第一次寒冬（1974-1980）：由于技术限制，AI研究进入低谷
    # 3. 专家系统时期（1980-1987）：专家系统在特定领域取得突破
    # 4. 第二次寒冬（1987-1993）：专家系统维护成本高昂，再次陷入低谷
    # 5. 机器学习时期（1993-2010）：统计学习方法崛起
    # 6. 深度学习时期（2010-至今）：深度神经网络取得了革命性突破
    #
    # 近年来，大语言模型（如GPT系列、Qwen等）的出现，标志着AI进入了新的发展阶段。
    #
    # 人工智能的主要应用领域包括：
    # - 自然语言处理
    # - 计算机视觉
    # - 自动驾驶
    # - 医疗诊断
    # - 金融分析
    # - 智能制造
    #
    # 中国在人工智能领域也取得了显著进展，阿里巴巴、百度、华为等公司都在积极研发AI技术。
    # """)
    #     print(f"✅ 创建示例文档: {sample_data_path}")

    # 3. 文档不存在时明确报错（自动创建已注释，防止覆盖手工内容）
    if not sample_data_path.exists():
        raise FileNotFoundError(
            f"文档不存在: {sample_data_path}\n"
            "请手动创建该文件，或取消 demo() 中注释的自动生成代码后重新运行"
        )

    # 4/5. 已有向量库直接加载（秒开）；仅首次或 sample.txt 更新后才重建
    #      重建需逐块调用Ollama嵌入接口，是之前启动慢的主因
    import hashlib

    sample_data_path = str(sample_data_path)
    rebuild = True
    try:
        rag.load_vectorstore()
        with open(sample_data_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        # metadata中记录来源文件哈希，一致则跳过重建
        meta = rag.vectorstore._collection.metadata or {}
        if meta.get("source_md5") == file_hash and rag.collection_size() > 0:
            rebuild = False
            print(f"⚡ 向量库已是最新，跳过重建（{rag.collection_size()} 个切片）")
    except Exception as e:
        logger.info(f"首次运行或向量库不可用，将重建: {e}")

    if rebuild:
        documents = rag.load_documents(sample_data_path)
        rag.create_vectorstore(documents)
        # 记录来源文件哈希，供下次启动比对
        with open(sample_data_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        rag.vectorstore._collection.modify(metadata={"source_md5": file_hash})

    # 6. 设置问答链
    rag.setup_qa_chain(k=3)

    print("\n" + "=" * 60)
    print("💬 RAG问答系统（输入 q 退出）")
    print("=" * 60)

    # 命令行参数带问题时逐个提问，否则进入交互模式
    questions = sys.argv[1:]

    if questions:
        for q in questions:
            ask_and_print(rag, q)
    else:
        while True:
            try:
                q = input("\n❓ 请输入问题: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break
            if not q or q.lower() in ("q", "quit", "exit"):
                print("再见！")
                break
            ask_and_print(rag, q)


def ask_and_print(rag, question: str):
    """提问并打印结果"""
    print(f"\n❓ 问题: {question}")
    result = rag.ask(question)
    print(f"🤖 回答: {result['answer']}")
    print(f"📚 参考来源数: {len(result['sources'])}")
    print("-" * 60)


if __name__ == "__main__":
    demo()