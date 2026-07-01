"""
向量存储抽象层 — ChromaDB 封装。

支持创建/加载 collection、添加文档、语义检索。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_PERSIST_DIR = Path.home() / ".agentos" / "chroma"


@dataclass
class SearchResult:
    """检索结果。"""
    content: str
    score: float
    metadata: dict = field(default_factory=dict)
    source: str = ""


class VectorStore(ABC):
    """向量存储抽象基类。"""

    @abstractmethod
    def add(self, texts: list[str], metadatas: list[dict] | None = None, ids: list[str] | None = None):
        ...

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        ...

    @abstractmethod
    def count(self) -> int:
        ...

    @abstractmethod
    def clear(self):
        ...


class ChromaStore(VectorStore):
    """ChromaDB 向量存储实现。

    Args:
        collection_name: 集合名称
        persist_dir: 持久化目录，None 则仅内存模式
        embedding_model: 嵌入模型名称（默认使用 sentence-transformers 轻量模型）
    """

    def __init__(
        self,
        collection_name: str = "default",
        persist_dir: str | None = None,
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self._collection_name = collection_name
        self._persist_dir = persist_dir
        self._embedding_model = embedding_model
        self._client = None
        self._collection = None
        self._initialized = False

    def _get_embedding_function(self):
        """获取 embedding 函数，优先 sentence-transformers，fallback 到 ONNX 内置模型。"""
        from chromadb.utils import embedding_functions
        try:
            import sentence_transformers  # noqa: F401
            return embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self._embedding_model,
            )
        except ImportError:
            return embedding_functions.DefaultEmbeddingFunction()

    def _ensure_init(self):
        if self._initialized:
            return
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            if self._persist_dir:
                os.makedirs(self._persist_dir, exist_ok=True)
                self._client = chromadb.PersistentClient(path=self._persist_dir)
            else:
                self._client = chromadb.Client()

            self._ef = self._get_embedding_function()
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=self._ef,
            )
            self._initialized = True
        except ImportError:
            raise ImportError(
                "chromadb 未安装。运行: pip install chromadb sentence-transformers"
            )

    def add(self, texts: list[str], metadatas: list[dict] | None = None, ids: list[str] | None = None):
        self._ensure_init()
        if ids is None:
            ids = [str(self.count() + i) for i in range(len(texts))]
        self._collection.add(documents=texts, metadatas=metadatas or None, ids=ids)

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        self._ensure_init()
        results = self._collection.query(query_texts=[query], n_results=top_k)
        out = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                doc = results["documents"][0][i] or ""
                score = 0.0
                if results.get("distances") and results["distances"][0]:
                    score = 1.0 / (1.0 + float(results["distances"][0][i]))
                meta = {}
                if results.get("metadatas") and results["metadatas"][0]:
                    meta = results["metadatas"][0][i] or {}
                out.append(SearchResult(content=doc, score=score, metadata=meta))
        return out

    def count(self) -> int:
        self._ensure_init()
        return self._collection.count()

    def clear(self):
        self._ensure_init()
        self._client.delete_collection(self._collection_name)
        self._initialized = False
