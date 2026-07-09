"""
RAG 模块入口 — 向量存储 / 文档加载 / 检索生成管道 / 混合搜索。

v1.5.1: ChromaDB 向量存储 + PDF/DOCX/TXT 文档加载 + 基础 RAG Pipeline。
v1.9.0: 混合搜索 + BM25 稀疏检索 + 跨编码器重排 + 引用追踪。
"""

from agentos.rag.hybrid_search import (
    BM25Retriever,
    Citation,
    CitationTracker,
    CrossEncoderReranker,
    DenseRetriever,
    FusionMethod,
    HybridSearchEngine,
    SearchResult,
)
from agentos.rag.loader import DocumentLoader, load_directory, load_file
from agentos.rag.pipeline import RAGPipeline
from agentos.rag.store import ChromaStore, VectorStore

# 向后兼容别名
BaseVectorStore = VectorStore
FAISSVectorStore = None  # FAISS 已移除，由 ChromaDB 替代
ChromaVectorStore = ChromaStore

# 配置兼容别名
ChunkConfig = dict  # chunk_size + chunk_overlap
EmbeddingConfig = dict  # model_name + device


# TextChunker 兼容层
class TextChunker:
    """文本分块器（向后兼容）。"""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self._loader = DocumentLoader(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def chunk(self, text: str, source: str = "") -> list[str]:
        docs = self._loader._chunk(text, source)
        return [d.content for d in docs]

    def chunk_file(self, path: str) -> list[str]:
        docs = self._loader.load_file(path)
        return [d.content for d in docs]


__all__ = [
    "VectorStore",
    "ChromaStore",
    "DocumentLoader",
    "load_file",
    "load_directory",
    "RAGPipeline",
    # 混合搜索 v1.9.0
    "HybridSearchEngine",
    "BM25Retriever",
    "DenseRetriever",
    "CrossEncoderReranker",
    "CitationTracker",
    "Citation",
    "SearchResult",
    "FusionMethod",
    # 向后兼容
    "BaseVectorStore",
    "FAISSVectorStore",
    "ChromaVectorStore",
    "TextChunker",
]
