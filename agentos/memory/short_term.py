"""
短期记忆 — 向量数据库存储，覆盖数天到数周的记忆。
"""

from __future__ import annotations

from dataclasses import dataclass

from agentos.memory.working import MemoryItem


@dataclass
class VectorMemory:
    """
    短期记忆 — 基于ChromaDB的向量存储。
    存近期对话和重要上下文，按语义相似度检索。
    """

    def __init__(self, collection_name: str = "agentos_short_term"):
        self.collection_name = collection_name
        self._items: list[MemoryItem] = []
        self._chroma_client = None

    @property
    def chroma_client(self):
        """延迟加载ChromaDB客户端。"""
        if self._chroma_client is None:
            try:
                import chromadb

                self._chroma_client = chromadb.PersistentClient(path="./.agentos/vector_db")
            except ImportError:
                self._chroma_client = None
        return self._chroma_client

    async def add(self, item: MemoryItem):
        self._items.append(item)

    async def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """
        向量语义搜索。
        如果ChromaDB不可用，降级为关键词匹配。
        """
        if self._chroma_client:
            try:
                collection = self._chroma_client.get_or_create_collection(self.collection_name)
                results = collection.query(query_texts=[query], n_results=limit)
                ids = results.get("ids", [[]])[0]
                return [self._items[int(i)] for i in ids if int(i) < len(self._items)]
            except Exception:
                pass

        # 降级：关键词匹配
        return [item for item in self._items[-limit:] if query.lower() in item.content.lower()]

    def clear(self):
        self._items.clear()
