"""Hybrid search (dense + sparse) for RAG pipeline.

Combines dense vector search with BM25 sparse retrieval
using reciprocal rank fusion (RRF) or weighted score fusion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class HybridConfig:
    """Configuration for hybrid search."""
    dense_weight: float = 0.6  # weight for dense scores
    sparse_weight: float = 0.4  # weight for BM25 scores
    fusion_method: str = "weighted"  # "weighted" | "rrf"
    rrf_k: int = 60  # RRF constant
    bm25_k1: float = 1.5  # BM25 term frequency saturation
    bm25_b: float = 0.75  # BM25 document length normalization
    top_k_per_source: int = 20  # candidates from each retriever before fusion


class BM25Retriever:
    """BM25 sparse retrieval with Okapi BM25 scoring.

    Works with pre-chunked documents, builds an in-memory inverted index.
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        stop_words: Optional[List[str]] = None,
    ):
        self.k1 = k1
        self.b = b
        self.stop_words = set(stop_words or _DEFAULT_STOP_WORDS)
        self._docs: List[str] = []
        self._doc_lens: List[int] = []
        self._avgdl: float = 0.0
        self._df: Dict[str, int] = {}  # term -> document frequency
        self._term_freqs: List[Dict[str, int]] = []  # per-doc term freqs
        self._built = False

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace + punctuation tokenization."""
        import re
        tokens = re.findall(r'\w+', text.lower())
        return [t for t in tokens if t not in self.stop_words and len(t) > 1]

    def index(self, documents: List[str]):
        """Build BM25 index from documents."""
        self._docs = documents
        self._doc_lens = [len(d) for d in documents]
        self._avgdl = sum(self._doc_lens) / max(len(documents), 1)
        self._df = {}
        self._term_freqs = []

        for doc in documents:
            tokens = self._tokenize(doc)
            tf = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            self._term_freqs.append(tf)
            for t in tf:
                self._df[t] = self._df.get(t, 0) + 1

        self._built = True

    def search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """Search and return (doc_index, score) sorted by score descending."""
        if not self._built:
            return []

        query_tokens = self._tokenize(query)
        idf_cache = {
            t: math.log(1 + (len(self._docs) - freq + 0.5) / (freq + 0.5))
            for t, freq in self._df.items()
            if t in query_tokens
        }

        scores = []
        for i, tf in enumerate(self._term_freqs):
            score = 0.0
            for t in query_tokens:
                if t not in tf:
                    continue
                idf = idf_cache.get(t, 0.0)
                f = tf[t]
                dl = self._doc_lens[i]
                numerator = f * (self.k1 + 1)
                denominator = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                score += idf * numerator / denominator
            if score > 0:
                scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class HybridRetriever:
    """Combined dense + sparse retrieval with score fusion.

    Usage:
        retriever = HybridRetriever(
            dense_fn=your_dense_search_fn,
            bm25=bm25_retriever,
        )
        results = await retriever.search(query="how to train a model", top_k=5)
    """

    def __init__(
        self,
        dense_fn,
        bm25: Optional[BM25Retriever] = None,
        config: Optional[HybridConfig] = None,
    ):
        self.dense_fn = dense_fn
        self.bm25 = bm25 or BM25Retriever()
        self.config = config or HybridConfig()

    def index_documents(self, documents: List[str]):
        """Index documents for BM25 sparse retrieval."""
        self.bm25.index(documents)

    async def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Hybrid search combining dense and sparse scores.

        Returns list of dicts with 'text', 'score', 'dense_score',
        'sparse_score', 'index'.
        """
        # Dense retrieval
        dense_results = await self.dense_fn(query, self.config.top_k_per_source)

        # BM25 retrieval
        bm25_pairs = self.bm25.search(query, self.config.top_k_per_source)

        # Normalize and fuse scores
        fused = self._fuse_scores(dense_results, bm25_pairs)
        fused.sort(key=lambda x: x["score"], reverse=True)

        return fused[:top_k]

    def _fuse_scores(
        self,
        dense_results: List[Dict[str, Any]],
        bm25_pairs: List[Tuple[int, float]],
    ) -> List[Dict[str, Any]]:
        """Fuse dense and sparse scores using configured method."""
        # Build lookup: doc_index -> result
        index_map: Dict[int, Dict[str, Any]] = {}
        for i, r in enumerate(dense_results):
            idx = r.get("index", i)
            index_map[idx] = {
                "text": r.get("text", ""),
                "dense_score": r.get("score", 0.0),
                "sparse_score": 0.0,
                "index": idx,
                "metadata": r.get("metadata", {}),
                "dense_rank": i + 1,  # 1-based rank
                "sparse_rank": 0,
            }

        for rank, (idx, bm25_score) in enumerate(bm25_pairs):
            rank_p1 = rank + 1
            if idx in index_map:
                index_map[idx]["sparse_score"] = bm25_score
                index_map[idx]["sparse_rank"] = rank_p1
            else:
                index_map[idx] = {
                    "text": "",
                    "dense_score": 0.0,
                    "sparse_score": bm25_score,
                    "index": idx,
                    "metadata": {},
                    "dense_rank": 0,
                    "sparse_rank": rank_p1,
                }

        # Compute fused score
        for idx, entry in index_map.items():
            if self.config.fusion_method == "rrf":
                dr = entry["dense_rank"] or (self.config.top_k_per_source + 1)
                sr = entry["sparse_rank"] or (self.config.top_k_per_source + 1)
                entry["score"] = 1.0 / (self.config.rrf_k + dr) + 1.0 / (self.config.rrf_k + sr)
            else:
                entry["score"] = (
                    self.config.dense_weight * entry["dense_score"]
                    + self.config.sparse_weight * self._normalize_bm25(entry["sparse_score"])
                )

        return list(index_map.values())

    def _normalize_bm25(self, score: float) -> float:
        """Simple sigmoid normalization for BM25 scores."""
        if score <= 0:
            return 0.0
        return 2.0 / (1.0 + math.exp(-score / 3.0)) - 1.0


_DEFAULT_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "it", "its", "this",
    "that", "these", "those", "i", "you", "he", "she", "they", "we", "my",
    "your", "his", "her", "our", "their", "not", "no", "if", "so", "as",
    "than", "then", "just", "about", "also", "very", "too", "into", "over",
    "after", "before", "between", "under", "more", "up", "out", "some",
    "such", "only", "other", "each", "all", "both", "few", "most",
}
