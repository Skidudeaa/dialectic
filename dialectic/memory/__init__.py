# memory/__init__.py — Memory subsystem exports

from .manager import MemoryManager
from .embeddings import EmbeddingProvider, get_embedding_provider
from .vector_store import VectorStore, SimilarityMatch
from .cross_session import CrossSessionMemoryManager, GlobalSearchResult

__all__ = [
    'MemoryManager',
    'EmbeddingProvider',
    'get_embedding_provider',
    'VectorStore',
    'SimilarityMatch',
    'CrossSessionMemoryManager',
    'GlobalSearchResult',
]
