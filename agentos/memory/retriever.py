"""
Semantic Memory Retriever — Embedding-based memory retrieval with hybrid search.

Supports semantic (embedding), keyword (BM25), and hybrid search across
conversation memory, long-term memory, and working memory. Aligns with
ConversationMemory window strategies and LongTermMemory persistence.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class RetrievalStrategy(Enum):
    """检索策略枚举。"""

    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"
    RECENT = "recent"


@dataclass
class MemoryEntry:
    """A single memory entry with content and metadata."""

    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    timestamp: float | None = None
    importance: float = 0.5
    source: str = "conversation"  # conversation / long_term / working


@dataclass
class RetrievalResult:
    """A single retrieval result with relevance score."""

    entry: MemoryEntry
    score: float
    strategy: RetrievalStrategy


@dataclass
class RetrievalStats:
    """Statistics for a retrieval operation."""

    total_entries: int
    retrieved: int
    strategies_used: list[RetrievalStrategy] = field(default_factory=list)
    latency_ms: float = 0.0


class SemanticMemoryRetriever:
    """
    Semantic retrieval engine for AgentOS memory systems.

    Supports three retrieval strategies:
    - **semantic**: Cosine similarity over embeddings (requires embedder)
    - **keyword**: BM25-style TF-IDF keyword matching (no embedder needed)
    - **hybrid**: Weighted combination of semantic + keyword scores

    Example::

        retriever = SemanticMemoryRetriever(embedder=my_embedder)
        results = retriever.retrieve(
            "What did we discuss about deployment?",
            top_k=5,
            strategy=RetrievalStrategy.HYBRID,
        )
        for r in results:
            print(f"[{r.score:.2f}] {r.entry.content[:80]}...")
    """

    def __init__(
        self,
        embedder: Callable[[str], list[float]] | None = None,
        hybrid_weight: float = 0.7,
        min_keyword_score: float = 0.01,
        default_top_k: int = 10,
    ):
        """
        Args:
            embedder: Callable that takes text and returns embedding vector.
            hybrid_weight: Weight for semantic score in hybrid mode (0-1).
                           Remaining weight goes to keyword score.
            min_keyword_score: Minimum BM25 score to include in results.
            default_top_k: Default number of results to return.
        """
        self._embedder = embedder
        self._hybrid_weight = hybrid_weight
        self._min_keyword_score = min_keyword_score
        self._default_top_k = default_top_k
        self._entries: dict[str, MemoryEntry] = {}
        self._idf_cache: dict[str, float] = {}
        self._doc_freqs: Counter[str, int] = Counter()
        self._total_docs: int = 0

    def index(self, entries: list[MemoryEntry]) -> None:
        """Add entries to the search index."""
        for entry in entries:
            self._entries[entry.id] = entry
            if entry.embedding and self._embedder:
                # Already has embedding, no need to re-embed
                pass
            elif self._embedder:
                entry.embedding = self._embedder(entry.content)

            # Update keyword index
            tokens = self._tokenize(entry.content)
            unique_tokens = set(tokens)
            self._doc_freqs.update(unique_tokens)
            self._total_docs += 1

    def remove(self, entry_ids: list[str]) -> None:
        """Remove entries from the index."""
        for eid in entry_ids:
            if eid in self._entries:
                entry = self._entries.pop(eid)
                unique_tokens = set(self._tokenize(entry.content))
                for token in unique_tokens:
                    self._doc_freqs[token] = max(0, self._doc_freqs[token] - 1)
                self._total_docs = max(0, self._total_docs - 1)
        self._idf_cache.clear()

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        strategy: RetrievalStrategy = RetrievalStrategy.HYBRID,
        filter_source: str | None = None,
        min_importance: float = 0.0,
    ) -> list[RetrievalResult]:
        """
        Retrieve the most relevant memories for a query.

        Args:
            query: Search query.
            top_k: Number of results to return.
            strategy: Retrieval strategy.
            filter_source: Only return entries from this source.
            min_importance: Minimum importance score filter.

        Returns:
            List of RetrievalResult sorted by relevance.
        """
        import time

        start = time.perf_counter()
        top_k = top_k or self._default_top_k

        # Filter entries
        candidates = [
            e
            for e in self._entries.values()
            if (filter_source is None or e.source == filter_source)
            and e.importance >= min_importance
        ]

        if not candidates:
            return []

        if strategy == RetrievalStrategy.RECENT:
            results = self._retrieve_recent(candidates, top_k)
        elif strategy == RetrievalStrategy.KEYWORD:
            results = self._retrieve_keyword(query, candidates, top_k)
        elif strategy == RetrievalStrategy.SEMANTIC:
            results = self._retrieve_semantic(query, candidates, top_k)
        else:  # HYBRID
            results = self._retrieve_hybrid(query, candidates, top_k)

        (time.perf_counter() - start) * 1000
        # Attach stats to results via a common approach
        return results

    def _retrieve_recent(
        self,
        candidates: list[MemoryEntry],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Return most recent entries sorted by timestamp."""
        sorted_entries = sorted(
            candidates,
            key=lambda e: e.timestamp or 0,
            reverse=True,
        )
        return [
            RetrievalResult(
                entry=e,
                score=1.0,
                strategy=RetrievalStrategy.RECENT,
            )
            for e in sorted_entries[:top_k]
        ]

    def _retrieve_keyword(
        self,
        query: str,
        candidates: list[MemoryEntry],
        top_k: int,
    ) -> list[RetrievalResult]:
        """BM25-style keyword search."""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = []
        for entry in candidates:
            score = self._bm25_score(query_tokens, entry.content)
            if score >= self._min_keyword_score:
                scores.append((score, entry))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [
            RetrievalResult(
                entry=e,
                score=s,
                strategy=RetrievalStrategy.KEYWORD,
            )
            for s, e in scores[:top_k]
        ]

    def _retrieve_semantic(
        self,
        query: str,
        candidates: list[MemoryEntry],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Cosine similarity semantic search."""
        if not self._embedder:
            return self._retrieve_keyword(query, candidates, top_k)

        query_embedding = np.array(self._embedder(query))
        scores = []
        for entry in candidates:
            if entry.embedding is None:
                entry.embedding = self._embedder(entry.content)
            entry_embedding = np.array(entry.embedding)
            similarity = self._cosine_sim(query_embedding, entry_embedding)
            scores.append((similarity, entry))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [
            RetrievalResult(
                entry=e,
                score=float(s),
                strategy=RetrievalStrategy.SEMANTIC,
            )
            for s, e in scores[:top_k]
        ]

    def _retrieve_hybrid(
        self,
        query: str,
        candidates: list[MemoryEntry],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Weighted combination of semantic and keyword scores."""
        query_tokens = self._tokenize(query)
        has_embedder = self._embedder is not None

        if has_embedder:
            query_embedding = np.array(self._embedder(query))

        scores = []
        for entry in candidates:
            kw_score = self._bm25_score(query_tokens, entry.content)

            if has_embedder:
                if entry.embedding is None:
                    entry.embedding = self._embedder(entry.content)
                entry_embedding = np.array(entry.embedding)
                sem_score = self._cosine_sim(query_embedding, entry_embedding)
                combined = self._hybrid_weight * sem_score + (1 - self._hybrid_weight) * kw_score
            else:
                combined = kw_score

            if combined > 0:
                scores.append((combined, entry))

        scores.sort(key=lambda x: x[0], reverse=True)
        return [
            RetrievalResult(
                entry=e,
                score=float(s),
                strategy=RetrievalStrategy.HYBRID,
            )
            for s, e in scores[:top_k]
        ]

    # --- BM25 implementation ---

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple word tokenizer."""
        text = text.lower()
        # Split on non-alphanumeric, keep sequences of 2+ chars
        tokens = []
        current = []
        for ch in text:
            if ch.isalnum():
                current.append(ch)
            else:
                if len(current) >= 2:
                    tokens.append("".join(current))
                current = []
        if len(current) >= 2:
            tokens.append("".join(current))
        return tokens

    def _idf(self, term: str) -> float:
        """Inverse document frequency."""
        if term not in self._idf_cache:
            df = self._doc_freqs.get(term, 0)
            if df == 0 or self._total_docs == 0:
                self._idf_cache[term] = 0.0
            else:
                self._idf_cache[term] = math.log((self._total_docs - df + 0.5) / (df + 0.5) + 1.0)
        return self._idf_cache[term]

    def _bm25_score(
        self,
        query_tokens: list[str],
        document: str,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> float:
        """BM25 score for a document given query tokens."""
        doc_tokens = self._tokenize(document)
        doc_len = len(doc_tokens)
        avg_doc_len = max(1, self._total_docs)

        term_freqs = Counter(doc_tokens)
        score = 0.0

        for token in query_tokens:
            tf = term_freqs.get(token, 0)
            if tf == 0:
                continue
            idf = self._idf(token)
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * doc_len / avg_doc_len)
            score += idf * numerator / denominator

        return round(score, 6)

    # --- Utilities ---

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two vectors."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self._idf_cache.clear()
        self._doc_freqs.clear()
        self._total_docs = 0

    def get_stats(self) -> dict[str, Any]:
        """Return index statistics."""
        return {
            "total_entries": len(self._entries),
            "total_docs": self._total_docs,
            "unique_terms": len(self._doc_freqs),
            "has_embedder": self._embedder is not None,
            "hybrid_weight": self._hybrid_weight,
        }
