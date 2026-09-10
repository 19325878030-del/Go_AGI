# my_ai_app/modules/rag/__init__.py
from .rag_service import RAGService
from .rag_ingest import (
    ingest_documents,
    list_collections,
    delete_collection,
    slug_collection_name,
    SUPPORTED_EXTS,
)

__all__ = [
    'RAGService',
    'ingest_documents',
    'list_collections',
    'delete_collection',
    'slug_collection_name',
    'SUPPORTED_EXTS',
]
