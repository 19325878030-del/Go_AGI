# my_ai_app/modules/rag/rag_ingest.py
"""
向量库生成工具（文档入库）。

前端上传文件 → app 层存到临时目录 → 本模块按扩展名加载 → 分块 →
本地 Ollama 嵌入（nomic-embed-text）→ 存入本地 Chroma 命名集合（data/chroma_db）。

与 rag_service.py 的关系：本模块只负责"建库/追加"，检索与问答在 RAGService。
两端共用同一 Ollama 嵌入模型，务必保持一致（换模型需重建所有库）。

Chroma 集合名仅允许 [a-zA-Z0-9_-]（3-512位），中文等库名会被 slug 化为
kb-<短哈希>，原名存入集合 metadata.display_name，list 时还原展示。
"""
import hashlib
import re
import sys
from pathlib import Path

import chromadb
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import Chroma

# Windows控制台默认GBK编码，无法打印emoji，强制stdout使用UTF-8
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 与 rag_service.py 保持一致
OLLAMA_BASE = "http://localhost:11434"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_PERSIST_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "chroma_db")

# 分块参数：中文文档为主，块大一些保证语义完整；overlap 让相邻块衔接
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120


def _embeddings(embedding_model: str) -> OllamaEmbeddings:
    # trust_env=False：绕开系统代理，否则 httpx 会把 localhost 请求发给代理导致连接被拒
    return OllamaEmbeddings(
        model=embedding_model,
        base_url=OLLAMA_BASE,
        client_kwargs={'trust_env': False}
    )


def _load_text(path: Path) -> list:
    """txt/md 直接读文件：utf-8 优先、gbk 兜底（中文 Windows 文件常见编码）。

    不用 TextLoader(autodetect_encoding=True)，它依赖 chardet，少装一个包。
    """
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("无法识别文件编码（尝试过 utf-8/gbk）")
    return [Document(page_content=text, metadata={"source": path.name})]


# 支持的扩展名 → 加载方式（统一小写比较；txt/md 用自带 utf-8/gbk 读取）
LOADER_MAP = {
    ".txt": _load_text,
    ".md": _load_text,
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
}
SUPPORTED_EXTS = sorted(LOADER_MAP.keys())


def slug_collection_name(display_name: str) -> str:
    """把用户可见的库名转成 Chroma 合法集合名。

    规则：保留 [a-zA-Z0-9_-]，其余字符替换为 '-'；全被替换掉（纯中文/符号）时
    回退为 'kb-' + 名字哈希前12位。结果 3-512 位，不满足时补齐/截断。
    """
    slug = re.sub(r'[^a-zA-Z0-9_-]', '-', display_name.strip()).strip('-')
    if len(slug.replace('-', '').replace('_', '')) == 0:
        # 纯非ASCII名（如中文）：没有任何可用字符，直接用哈希
        slug = 'kb-' + hashlib.md5(display_name.encode('utf-8')).hexdigest()[:12]
    if len(slug) < 3:
        slug = (slug + '-kb')[:3] if slug else 'kb-x'
    return slug[:512]


def ingest_documents(collection_name: str,
                     file_paths,
                     persist_dir: str = None,
                     embedding_model: str = DEFAULT_EMBEDDING_MODEL,
                     chunk_size: int = CHUNK_SIZE,
                     chunk_overlap: int = CHUNK_OVERLAP) -> dict:
    """把若干文档写入命名向量库（已存在则增量追加/覆盖同名块），返回入库统计。

    Args:
        collection_name: 用户可见库名（中文可），内部映射为 Chroma 合法集合名
        file_paths: 文件路径列表（str 或 Path），支持 .txt/.md/.pdf/.docx
        persist_dir: Chroma 持久化目录；缺省 my_ai_app/data/chroma_db
        embedding_model: 嵌入模型，建库与检索必须一致

    Returns:
        {"collection": 合法集合名, "display_name": 原始库名,
         "total_chunks": 本次入库块数, "files": [{file, chunks, ok, error}]}
    """
    persist_dir = persist_dir or DEFAULT_PERSIST_DIR
    file_paths = [Path(p) for p in file_paths]

    # 逐文件加载 + 分块（单文件失败不影响其余文件）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        # 中文感知：优先按段落/换行切，避免把中文句子拦腰斩断
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )
    all_chunks, file_stats = [], []
    for fp in file_paths:
        loader = LOADER_MAP.get(fp.suffix.lower())
        if loader is None:
            file_stats.append({"file": fp.name, "chunks": 0, "ok": False,
                               "error": f"不支持的格式 {fp.suffix}（支持 {' '.join(SUPPORTED_EXTS)}）"})
            continue
        try:
            # 普通函数（_load_text）直接调用返回文档列表；加载器类先实例化再 load()
            docs = loader(fp) if not isinstance(loader, type) else loader(str(fp)).load()
            chunks = splitter.split_documents(docs)
        except Exception as e:
            file_stats.append({"file": fp.name, "chunks": 0, "ok": False, "error": str(e)})
            continue
        # 元数据补文件名，检索命中后可溯源；PDF 的 page 等加载器元数据保留
        for ch in chunks:
            ch.metadata["source_file"] = fp.name
        all_chunks.extend(chunks)
        file_stats.append({"file": fp.name, "chunks": len(chunks), "ok": True, "error": None})
        print(f"📄 {fp.name} → {len(chunks)} 块")

    if not all_chunks:
        raise ValueError("没有可入库的内容：" +
                         "；".join(f"{s['file']}: {s['error']}" for s in file_stats if not s['ok']))

    # 建库/取库并 upsert（Chroma upsert 语义：同 ID 覆盖，重复上传同一文件不堆积）
    name = slug_collection_name(collection_name)
    client = chromadb.PersistentClient(path=persist_dir)
    client.get_or_create_collection(
        name=name,
        metadata={"display_name": collection_name, "embedding_model": embedding_model},
    )
    vectorstore = Chroma(
        persist_directory=persist_dir,
        embedding_function=_embeddings(embedding_model),
        collection_name=name,
    )
    # 块ID = md5(合法集合名|文件名|块序号)：同名库重传同文件幂等；换文件/换库名不冲突
    ids = [hashlib.md5(f"{name}|{c.metadata['source_file']}|{i}".encode('utf-8')).hexdigest()
           for i, c in enumerate(all_chunks)]
    vectorstore.add_documents(all_chunks, ids=ids)

    print(f"✅ 库「{collection_name}」({name}) 入库 {len(all_chunks)} 块 → {persist_dir}")
    return {"collection": name, "display_name": collection_name,
            "total_chunks": len(all_chunks), "files": file_stats}


def delete_collection(collection_name: str, persist_dir: str = None) -> bool:
    """删除向量库。入参可以是原始库名（中文）或已 slug 化的合法集合名。"""
    persist_dir = persist_dir or DEFAULT_PERSIST_DIR
    client = chromadb.PersistentClient(path=persist_dir)
    for candidate in (collection_name, slug_collection_name(collection_name)):
        try:
            client.delete_collection(name=candidate)
            return True
        except Exception:
            continue
    return False


def list_collections(persist_dir: str = None) -> list:
    """列出全部向量库：[{name: 合法集合名, display_name: 显示名, count: 块数}]"""
    persist_dir = persist_dir or DEFAULT_PERSIST_DIR
    try:
        client = chromadb.PersistentClient(path=persist_dir)
        result = []
        for c in client.list_collections():
            meta = c.metadata or {}
            result.append({
                "name": c.name,
                "display_name": meta.get("display_name", c.name),
                "count": c.count(),
            })
        return sorted(result, key=lambda x: x["display_name"])
    except Exception as e:
        print(f"⚠️ 列出向量库失败: {e}")
        return []


if __name__ == "__main__":
    print("rag_ingest：本模块作为库使用，不提供命令行演示。")
    print("由 app 层接收前端上传文件后调用 ingest_documents()。")
