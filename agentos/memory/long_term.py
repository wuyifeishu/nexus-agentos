"""
AgentOS v0.20 长期记忆系统。
RAG检索 + 知识图谱双重记忆。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryEntry:
    """长期记忆条目。"""

    id: str
    content: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0


class LongTermMemory:
    """
    长期记忆 — RAG + 知识图谱。

    功能:
    - 语义检索（向量相似度）
    - 关键词检索（倒排索引）
    - 实体关系图（知识图谱）
    - 记忆衰减（时间加权）
    - 自动摘要压缩
    """

    def __init__(self, embedding_dim: int = 1536, max_entries: int = 100000):
        self._entries: dict[str, MemoryEntry] = {}
        self._keyword_index: dict[str, set[str]] = {}
        self._entity_graph: dict[str, set[tuple[str, str]]] = {}
        self._embedding_dim = embedding_dim
        self._max_entries = max_entries

    def add(self, entry: MemoryEntry):
        """添加记忆条目。"""
        if len(self._entries) >= self._max_entries:
            self._evict_oldest()
        self._entries[entry.id] = entry
        self._index_keywords(entry)

    def search_by_keyword(self, query: str, top_k: int = 10) -> list[MemoryEntry]:
        """关键词检索。"""
        keywords = query.lower().split()
        scores: dict[str, int] = {}
        for kw in keywords:
            for entry_id in self._keyword_index.get(kw, set()):
                scores[entry_id] = scores.get(entry_id, 0) + 1
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [self._entries[eid] for eid, _ in ranked if eid in self._entries]

    def search_by_vector(self, query_embedding: list[float], top_k: int = 10) -> list[MemoryEntry]:
        """向量相似度检索（余弦相似度）。"""

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            return dot / (norm_a * norm_b + 1e-8)

        scored = []
        for entry in self._entries.values():
            if entry.embedding:
                sim = cosine(query_embedding, entry.embedding)
                scored.append((sim, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def add_relation(self, entity_a: str, relation: str, entity_b: str):
        """添加知识图谱三元组。"""
        self._entity_graph.setdefault(entity_a, set()).add((relation, entity_b))
        self._entity_graph.setdefault(entity_b, set()).add((relation + "_reverse", entity_a))

    def query_relations(self, entity: str, depth: int = 1) -> list[tuple[str, str]]:
        """查询实体的关系。"""
        results = list(self._entity_graph.get(entity, set()))
        return results[:50]

    def _index_keywords(self, entry: MemoryEntry):
        for word in entry.content.lower().split():
            clean = "".join(c for c in word if c.isalnum())
            if clean and len(clean) > 1:
                self._keyword_index.setdefault(clean, set()).add(entry.id)

    def _evict_oldest(self):
        oldest = min(self._entries.values(), key=lambda e: e.created_at)
        del self._entries[oldest.id]
        for kw_set in self._keyword_index.values():
            kw_set.discard(oldest.id)

    # ── Persistence (v1.14.9) ────────────────

    def get_state(self) -> dict[str, Any]:
        """Export LongTermMemory state for persistence."""
        return {
            "embedding_dim": self._embedding_dim,
            "max_entries": self._max_entries,
            "entries": {
                eid: {
                    "id": entry.id,
                    "content": entry.content,
                    "embedding": entry.embedding,
                    "metadata": entry.metadata,
                    "created_at": entry.created_at,
                }
                for eid, entry in self._entries.items()
            },
            "entity_graph": {
                entity: [(r, e) for r, e in relations]
                for entity, relations in self._entity_graph.items()
            },
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore LongTermMemory from a persisted snapshot."""
        self._embedding_dim = state.get("embedding_dim", self._embedding_dim)
        self._max_entries = state.get("max_entries", self._max_entries)
        self._entries.clear()
        self._keyword_index.clear()
        self._entity_graph.clear()

        for eid, entry_data in state.get("entries", {}).items():
            entry = MemoryEntry(
                id=entry_data.get("id", eid),
                content=entry_data.get("content", ""),
                embedding=entry_data.get("embedding"),
                metadata=entry_data.get("metadata", {}),
                created_at=entry_data.get("created_at", 0.0),
            )
            self._entries[eid] = entry
            self._index_keywords(entry)

        for entity, relations in state.get("entity_graph", {}).items():
            for rel, target in relations:
                self._entity_graph.setdefault(entity, set()).add((rel, target))


class MemoryStore:
    """三层记忆系统的统一入口。"""

    def __init__(self, long_term: LongTermMemory | None = None):
        self.working: dict[str, Any] = {}
        self.short_term: list[dict] = []
        self.long_term = long_term or LongTermMemory()

    def remember(self, key: str, value: Any, long_term: bool = False):
        """存储记忆。"""
        if long_term:
            entry = MemoryEntry(id=key, content=str(value), created_at=__import__("time").time())
            self.long_term.add(entry)
        else:
            self.working[key] = value
            self.short_term.append({"key": key, "value": value})

    def recall(self, query: str, use_long_term: bool = True) -> list[Any]:
        """检索记忆。"""
        results = []
        # 工作记忆优先
        if query in self.working:
            results.append(self.working[query])
        # 短期记忆
        for item in self.short_term:
            if query.lower() in item["key"].lower():
                results.append(item["value"])
        # 长期记忆
        if use_long_term and not results:
            long_results = self.long_term.search_by_keyword(query)
            results.extend([e.content for e in long_results])
        return results if results else None

    def clear_short_term(self):
        self.short_term.clear()

    # ── Persistence (v1.14.9) ────────────────

    def get_state(self) -> dict[str, Any]:
        """Export MemoryStore state for persistence."""
        return {
            "working": self.working,
            "short_term": self.short_term,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore MemoryStore from a persisted snapshot."""
        self.working = dict(state.get("working", {}))
        self.short_term = list(state.get("short_term", []))
