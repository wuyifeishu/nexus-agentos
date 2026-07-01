"""
Hybrid Search + Re-Ranking for RAG (v1.9.0)

Production-grade hybrid search combining:
  - Dense (semantic) retrieval via embeddings
  - Sparse (keyword) retrieval via BM25
  - Cross-encoder re-ranking for precision
  - Citation tracking with source provenance
  - Multi-modal: text, code, markdown, tables
  - Fusion algorithms: RRF, weighted sum, cascade

Compatible with existing ChromaStore + RAGPipeline.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Callable


# ── Types ───────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    """A single search result with metadata."""
    doc_id: str
    content: str
    source: str = ""           # File path, URL, or source identifier
    title: str = ""
    score: float = 0.0
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rerank_score: float = 0.0
    chunk_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)  # Specific sentences/quotes


@dataclass
class Citation:
    """A citation from source material."""
    text: str
    source: str
    doc_id: str = ""
    chunk_index: int = 0
    start_pos: int = 0
    end_pos: int = 0
    confidence: float = 1.0


# ── BM25 Sparse Retriever ───────────────────────────────────────────

class BM25Retriever:
    """Pure Python BM25 implementation for keyword search.

    No external dependencies. Tokenizes, builds inverted index,
    and scores documents using Okapi BM25.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: list[str] = []
        self._doc_ids: list[str] = []
        self._doc_lengths: list[int] = []
        self._avg_dl: float = 0.0
        self._inverted_index: dict[str, dict[int, int]] = defaultdict(dict)
        self._idf: dict[str, float] = {}
        self._N: int = 0

    def index(self, documents: list[dict[str, str]]):
        """Build BM25 index from documents.

        Args:
            documents: List of {id, content} dicts.
        """
        self._docs = [doc.get("content", "") for doc in documents]
        self._doc_ids = [doc.get("id", f"doc_{i}") for i, doc in enumerate(documents)]
        self._doc_lengths = [len(self._tokenize(doc)) for doc in self._docs]
        self._N = len(self._docs)
        self._avg_dl = sum(self._doc_lengths) / max(self._N, 1)

        # Build inverted index
        self._inverted_index.clear()
        doc_freq: dict[str, int] = defaultdict(int)

        for doc_id, doc in enumerate(self._docs):
            tokens = self._tokenize(doc)
            token_counts = Counter(tokens)
            for token, count in token_counts.items():
                self._inverted_index[token][doc_id] = count
                doc_freq[token] += 1

        # Compute IDF
        self._idf = {
            token: math.log(1 + (self._N - freq + 0.5) / (freq + 0.5))
            for token, freq in doc_freq.items()
        }

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """BM25 keyword search."""
        if not self._docs:
            return []

        query_tokens = self._tokenize(query)
        scores: list[float] = [0.0] * self._N

        for token in query_tokens:
            if token not in self._inverted_index:
                continue
            idf = self._idf.get(token, 0)
            for doc_id, tf in self._inverted_index[token].items():
                dl = self._doc_lengths[doc_id]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(self._avg_dl, 1))
                scores[doc_id] += idf * numerator / max(denominator, 1e-9)

        # Rank and return
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        max_score = ranked[0][1] if ranked else 1.0

        return [
            SearchResult(
                doc_id=self._doc_ids[doc_id],
                content=self._docs[doc_id][:500],
                sparse_score=score / max(max_score, 1e-9),
                score=score / max(max_score, 1e-9),
                metadata={"method": "bm25"},
            )
            for doc_id, score in ranked[:top_k] if score > 0
        ]

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization: lowercase, split on non-alphanumeric, filter short tokens."""
        tokens = re.findall(r'[\w\u4e00-\u9fff]+', text.lower())
        return [t for t in tokens if len(t) > 1]


# ── Dense Retriever ─────────────────────────────────────────────────

class DenseRetriever:
    """Semantic search via embeddings.

    Wraps an embedding function (e.g., OpenAI embeddings, sentence-transformers)
    and a vector store (ChromaDB or similar).
    """

    def __init__(
        self,
        vector_store=None,
        embed_fn: Optional[Callable[[str], list[float]]] = None,
    ):
        self._store = vector_store
        self._embed = embed_fn

    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Dense vector search."""
        if not self._store:
            return []

        try:
            results = await self._store.search(query, top_k=top_k)

            max_score = results[0].get("score", 1.0) if results else 1.0

            return [
                SearchResult(
                    doc_id=result.get("id", ""),
                    content=result.get("content", "")[:500],
                    dense_score=result.get("score", 0) / max(max_score, 1e-9),
                    score=result.get("score", 0) / max(max_score, 1e-9),
                    metadata=result.get("metadata", {}),
                )
                for result in results
            ]
        except Exception:
            return []


# ── Cross-Encoder Re-Ranker ─────────────────────────────────────────

class CrossEncoderReranker:
    """Re-rank search results with a cross-encoder model.

    Instead of embedding query and documents independently (bi-encoder),
    a cross-encoder processes (query, document) pairs together for higher
    accuracy — at the cost of more computation.

    Supports:
      - HuggingFace cross-encoder models (e.g., ms-marco-MiniLM)
      - Custom scoring functions
      - LLM-based re-ranking (use an LLM to judge relevance)
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        use_llm: bool = False,
        llm_client=None,
    ):
        self._model_name = model_name
        self._model = None
        self._use_llm = use_llm
        self._llm = llm_client

    async def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Re-rank candidates by relevance to query.

        Args:
            query: Original search query
            candidates: Initial retrieval results
            top_k: Number of results to return after re-ranking

        Returns:
            Re-ranked candidates with updated rerank_score.
        """
        if not candidates:
            return []

        if self._use_llm and self._llm:
            return await self._llm_rerank(query, candidates, top_k)
        else:
            return await self._cross_encoder_rerank(query, candidates, top_k)

    async def _cross_encoder_rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """Re-rank using HuggingFace cross-encoder."""
        try:
            from sentence_transformers import CrossEncoder
            if self._model is None:
                self._model = CrossEncoder(self._model_name)

            pairs = [(query, c.content[:1000]) for c in candidates]
            scores = self._model.predict(pairs)

            for candidate, score in zip(candidates, scores):
                candidate.rerank_score = float(score)
                # Weighted fusion
                candidate.score = (
                    candidate.dense_score * 0.3 +
                    candidate.sparse_score * 0.2 +
                    float(score) * 0.5
                )

            candidates.sort(key=lambda x: x.rerank_score, reverse=True)
            return candidates[:top_k]

        except ImportError:
            return candidates[:top_k]  # Fallback: no re-ranking

    async def _llm_rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """Re-rank using LLM relevance judgment."""
        if not self._llm:
            return candidates[:top_k]

        prompt = f"Query: {query}\n\nRate each document's relevance on a scale of 0-10:\n\n"
        for i, c in enumerate(candidates[:20]):
            prompt += f"[{i}] {c.content[:300]}\n\n"
        prompt += "Output format: [doc_id] score"

        try:
            response = await self._llm.complete(prompt)
            # Parse scores
            scores: dict[int, float] = {}
            for line in response.split("\n"):
                match = re.match(r'\[(\d+)\]\s*(\d+(?:\.\d+)?)', line.strip())
                if match:
                    idx = int(match.group(1))
                    score = float(match.group(2)) / 10.0
                    if idx < len(candidates):
                        scores[idx] = score

            for i, candidate in enumerate(candidates):
                candidate.rerank_score = scores.get(i, 0.5)
                candidate.score = (
                    candidate.dense_score * 0.25 +
                    candidate.sparse_score * 0.15 +
                    candidate.rerank_score * 0.6
                )

            candidates.sort(key=lambda x: x.rerank_score, reverse=True)
            return candidates[:top_k]

        except Exception:
            return candidates[:top_k]


# ── Fusion Algorithms ───────────────────────────────────────────────

class FusionMethod:
    """Collection of rank fusion algorithms."""

    @staticmethod
    def reciprocal_rank_fusion(
        dense_results: list[SearchResult],
        sparse_results: list[SearchResult],
        k: int = 60,
    ) -> list[SearchResult]:
        """RRF: Reciprocal Rank Fusion.

        RRF_score(d) = sum_{ranker} 1 / (k + rank(d))
        """
        scores: dict[str, float] = {}
        docs: dict[str, SearchResult] = {}

        for rank, result in enumerate(dense_results):
            scores[result.doc_id] = 1.0 / (k + rank + 1)
            docs[result.doc_id] = result

        for rank, result in enumerate(sparse_results):
            if result.doc_id in scores:
                scores[result.doc_id] += 1.0 / (k + rank + 1)
            else:
                scores[result.doc_id] = 1.0 / (k + rank + 1)
                docs[result.doc_id] = result

        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        for doc_id, score in fused:
            doc = docs[doc_id]
            doc.score = score
            results.append(doc)

        return results

    @staticmethod
    def weighted_sum(
        dense_results: list[SearchResult],
        sparse_results: list[SearchResult],
        dense_weight: float = 0.6,
        sparse_weight: float = 0.4,
    ) -> list[SearchResult]:
        """Weighted score summation."""
        scores: dict[str, list[float]] = defaultdict(list)
        docs: dict[str, SearchResult] = {}

        for result in dense_results:
            scores[result.doc_id].append(result.dense_score * dense_weight)
            docs[result.doc_id] = result

        for result in sparse_results:
            scores[result.doc_id].append(result.sparse_score * sparse_weight)
            if result.doc_id not in docs:
                docs[result.doc_id] = result

        fused = []
        for doc_id, wscores in scores.items():
            doc = docs[doc_id]
            doc.score = sum(wscores)
            fused.append(doc)

        fused.sort(key=lambda x: x.score, reverse=True)
        return fused

    @staticmethod
    def cascade(
        dense_results: list[SearchResult],
        sparse_results: list[SearchResult],
    ) -> list[SearchResult]:
        """Cascade: dense first, then sparse fills gaps."""
        seen: set[str] = set()
        results: list[SearchResult] = []

        for r in dense_results:
            results.append(r)
            seen.add(r.doc_id)

        for r in sparse_results:
            if r.doc_id not in seen:
                results.append(r)
                seen.add(r.doc_id)

        return results


# ── Citation Tracker ────────────────────────────────────────────────

class CitationTracker:
    """Track and verify citations from source documents.

    Key features:
      - Extract citations from generated text
      - Verify against source documents
      - Mark unverifiable (potential hallucination)
      - Track citation usage statistics
    """

    def __init__(self):
        self._citations: list[Citation] = []
        self._source_index: dict[str, dict] = {}  # doc_id → metadata

    def add_source(self, doc_id: str, content: str, metadata: dict[str, Any] | None = None):
        """Register a source document."""
        self._source_index[doc_id] = {
            "content": content,
            "metadata": metadata or {},
        }

    def extract_citations(self, text: str, sources: list[SearchResult]) -> list[Citation]:
        """Extract and verify citations from generated text.

        Args:
            text: Generated response text
            sources: Source documents used for generation

        Returns:
            List of verified Citation objects.
        """
        citations: list[Citation] = []

        for source in sources:
            # Find substrings of generated text that appear in source
            source_content = source.content.lower()
            text_lower = text.lower()

            # Extract sentences from generated text
            sentences = re.split(r'[.!?]+', text)
            for sent in sentences:
                sent = sent.strip()
                if len(sent) < 15:
                    continue

                # Check if this sentence appears in source (with fuzzy matching)
                if self._is_from_source(sent.lower(), source_content):
                    citations.append(Citation(
                        text=sent,
                        source=source.source or source.doc_id,
                        doc_id=source.doc_id,
                        chunk_index=source.chunk_index,
                        confidence=0.9,
                    ))

        # Deduplicate
        seen: set[str] = set()
        unique = []
        for c in citations:
            key = c.text[:50]
            if key not in seen:
                seen.add(key)
                unique.append(c)

        self._citations.extend(unique)
        return unique

    def verify(self, text: str, sources: list[SearchResult]) -> dict[str, Any]:
        """Verify all claims in text against source documents.

        Returns:
            Dict with verified/unverified segments and hallucination score.
        """
        citations = self.extract_citations(text, sources)

        sentences = re.split(r'[.!?]+', text)
        total_sentences = len(sentences)
        cited_sentences = sum(
            1 for s in sentences
            if any(c.text[:30].lower() in s.strip().lower() for c in citations)
        )

        uncited = total_sentences - cited_sentences
        hallucination_risk = uncited / max(total_sentences, 1)

        return {
            "total_sentences": total_sentences,
            "cited_sentences": cited_sentences,
            "uncited_sentences": uncited,
            "hallucination_risk": round(hallucination_risk, 3),
            "citations": [
                {"text": c.text[:100], "source": c.source, "confidence": c.confidence}
                for c in citations[:10]
            ],
            "status": "clean" if hallucination_risk < 0.3 else "medium_risk" if hallucination_risk < 0.6 else "high_risk",
        }

    def _is_from_source(self, text: str, source: str, threshold: float = 0.6) -> bool:
        """Check if text originated from source using substring and word overlap."""
        if text in source:
            return True

        text_words = set(text.split())
        source_words = set(source.split())
        if not text_words:
            return False

        overlap = len(text_words & source_words) / len(text_words)
        return overlap >= threshold

    def get_stats(self) -> dict[str, Any]:
        """Get citation statistics."""
        return {
            "total_citations": len(self._citations),
            "by_source": Counter(c.source for c in self._citations),
            "avg_confidence": (
                sum(c.confidence for c in self._citations) / len(self._citations)
                if self._citations else 0
            ),
            "sources_indexed": len(self._source_index),
        }


# ── Hybrid Search Engine ────────────────────────────────────────────

class HybridSearchEngine:
    """Unified hybrid search engine.

    Combines dense + sparse retrieval with fusion and re-ranking.

    Usage:
        engine = HybridSearchEngine(
            dense_retriever=DenseRetriever(vector_store=chroma_store),
            sparse_retriever=BM25Retriever(),
        )

        # Index documents
        engine.index_sparse(documents)

        # Hybrid search
        results = await engine.search("How to implement retry logic?")
        for r in results:
            print(f"{r.score:.3f} | {r.content[:100]}")
    """

    def __init__(
        self,
        dense_retriever: Optional[DenseRetriever] = None,
        sparse_retriever: Optional[BM25Retriever] = None,
        reranker: Optional[CrossEncoderReranker] = None,
        citation_tracker: Optional[CitationTracker] = None,
        fusion_method: str = "rrf",
        dense_weight: float = 0.6,
    ):
        self.dense = dense_retriever or DenseRetriever()
        self.sparse = sparse_retriever or BM25Retriever()
        self.reranker = reranker or CrossEncoderReranker()
        self.citations = citation_tracker or CitationTracker()

        self.fusion_method = fusion_method
        self.dense_weight = dense_weight

    def index_sparse(self, documents: list[dict[str, str]]):
        """Build sparse index from documents."""
        self.sparse.index(documents)
        for doc in documents:
            self.citations.add_source(
                doc_id=doc.get("id", ""),
                content=doc.get("content", ""),
                metadata=doc.get("metadata"),
            )

    async def search(
        self,
        query: str,
        top_k: int = 10,
        rerank: bool = True,
        return_citations: bool = False,
    ) -> list[SearchResult]:
        """Hybrid search: dense + sparse → fusion → rerank.

        Args:
            query: Search query
            top_k: Number of results
            rerank: Whether to apply re-ranking
            return_citations: Whether to attach citation info

        Returns:
            Ranked SearchResults.
        """
        # Step 1: Parallel retrieval
        dense_results = await self.dense.search(query, top_k=top_k * 2)
        sparse_results = self.sparse.search(query, top_k=top_k * 2)

        # Step 2: Fusion
        if self.fusion_method == "rrf":
            fused = FusionMethod.reciprocal_rank_fusion(dense_results, sparse_results)
        elif self.fusion_method == "cascade":
            fused = FusionMethod.cascade(dense_results, sparse_results)
        else:  # weighted_sum
            fused = FusionMethod.weighted_sum(
                dense_results, sparse_results,
                dense_weight=self.dense_weight,
                sparse_weight=1.0 - self.dense_weight,
            )

        # Step 3: Re-rank (optional)
        if rerank and len(fused) > top_k:
            fused = await self.reranker.rerank(query, fused, top_k=top_k)
        else:
            fused = fused[:top_k]

        # Step 4: Attach citations (optional)
        if return_citations and fused:
            for result in fused:
                result.citations = [
                    c.text for c in self.citations.extract_citations(
                        result.content, [result]
                    )
                ]

        return fused

    async def search_with_citations(
        self,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search and return both results and verified citations."""
        results = await self.search(query, top_k=top_k, return_citations=True)

        # Build combined text from top results
        combined = "\n\n".join(r.content for r in results)

        # Verify citations
        verification = self.citations.verify(combined, results)

        return {
            "results": results,
            "verification": verification,
            "top_result": results[0] if results else None,
            "citation_stats": self.citations.get_stats(),
        }

    def get_stats(self) -> dict[str, Any]:
        """Get search engine statistics."""
        return {
            "bm25_documents": self.sparse._N if self.sparse else 0,
            "bm25_vocabulary": len(self.sparse._idf) if self.sparse else 0,
            "citation_stats": self.citations.get_stats(),
            "fusion_method": self.fusion_method,
        }
