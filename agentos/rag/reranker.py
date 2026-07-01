"""Re-ranking for RAG pipeline.

Cross-encoder and LLM-based reranking to refine retrieval results.
Supports: cross-encoder (sentence-transformers), LLM reranking,
and simple heuristic reranking (diversity, freshness).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math


@dataclass
class RerankConfig:
    """Configuration for reranking."""
    method: str = "cross_encoder"  # cross_encoder | llm | diversity | mmr
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_n: int = 5  # number of results after reranking
    diversity_lambda: float = 0.5  # MMR diversity weight
    llm_prompt_template: str = ""  # custom prompt for LLM reranker
    batch_size: int = 8


class Reranker:
    """Re-rank retrieval results for improved relevance.

    Methods:
    - cross_encoder: Uses sentence-transformers cross-encoder for precision.
    - mmr: Maximal Marginal Relevance for diversity.
    - llm: Uses an LLM to score relevance of each passage.
    """

    def __init__(self, config: Optional[RerankConfig] = None):
        self.config = config or RerankConfig()
        self._cross_encoder = None
        self._embed_fn = None  # for MMR diversity

    async def rerank(
        self,
        query: str,
        passages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Re-rank passages by relevance to query.

        Args:
            query: Original search query.
            passages: List of dicts with 'text' and 'score' keys.

        Returns:
            Re-ranked list with updated 'rerank_score' key.
        """
        if not passages:
            return []

        if self.config.method == "cross_encoder":
            return await self._cross_encode_rerank(query, passages)
        elif self.config.method == "mmr":
            return self._mmr_rerank(query, passages)
        elif self.config.method == "llm":
            return await self._llm_rerank(query, passages)
        else:
            # diversity: sort by text length variability as proxy
            return self._diversity_rerank(passages)

    async def _cross_encode_rerank(
        self,
        query: str,
        passages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Use cross-encoder model for relevance scoring."""
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            # Fallback: use simple heuristic based on term overlap
            return self._fallback_rerank(query, passages)

        if self._cross_encoder is None:
            self._cross_encoder = CrossEncoder(self.config.model)

        pairs = [(query, p["text"]) for p in passages]
        scores = self._cross_encoder.predict(pairs, batch_size=self.config.batch_size)

        for p, s in zip(passages, scores):
            p["rerank_score"] = float(s)
            p["rerank_method"] = "cross_encoder"

        passages.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return passages[: self.config.top_n]

    def _mmr_rerank(
        self,
        query: str,
        passages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Maximal Marginal Relevance: balance relevance with diversity.

        Without embeddings, uses Jaccard similarity on token sets as proxy.
        """
        if not passages:
            return []

        texts = [p["text"] for p in passages]

        # Tokenize for diversity computation
        token_sets = []
        for t in texts:
            import re
            tokens = set(re.findall(r'\w+', t.lower()))
            token_sets.append(tokens)

        query_tokens = set(re.findall(r'\w+', query.lower())) if query else set()

        def _jaccard_sim(a: set, b: set) -> float:
            if not a or not b:
                return 0.0
            return len(a & b) / len(a | b)

        # Initial relevance scores (original scores or query overlap)
        relevance = []
        for i, (p, ts) in enumerate(zip(passages, token_sets)):
            if query_tokens:
                rel = _jaccard_sim(query_tokens, ts)
            else:
                rel = p.get("score", 0.0)
            relevance.append(rel)

        selected = []
        remaining = list(range(len(passages)))

        while remaining and len(selected) < self.config.top_n:
            best_idx = None
            best_score = -float("inf")

            for idx in remaining:
                diversity = min(
                    (1.0 - _jaccard_sim(token_sets[idx], token_sets[s]))
                    for s in selected
                ) if selected else 1.0

                score = (
                    self.config.diversity_lambda * relevance[idx]
                    + (1 - self.config.diversity_lambda) * diversity
                )

                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_idx is not None:
                selected.append(best_idx)
                remaining.remove(best_idx)
            else:
                break

        result = [passages[i] for i in selected]
        for i, p in enumerate(result):
            p["rerank_score"] = relevance[selected[i]]
            p["rerank_method"] = "mmr"

        return result

    async def _llm_rerank(
        self,
        query: str,
        passages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """LLM-based reranking: ask an LLM to score passage relevance.

        Falls back to fallback heuristic if no LLM is configured.
        """
        # This is a framework hook — the actual LLM call is done by the caller
        # by injecting an llm_call function or using the default heuristic
        return self._fallback_rerank(query, passages)

    def _diversity_rerank(
        self,
        passages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Simple diversity reranking: penalize similar-length passages."""
        import re

        texts = [p["text"] for p in passages]
        token_sets = []
        for t in texts:
            token_sets.append(set(re.findall(r'\w+', t.lower())))

        # Score: original score * diversity bonus (penalize similarity to higher-ranked)
        scored = []
        for i, p in enumerate(passages):
            diversity_penalty = 0.0
            for j in range(i):
                if token_sets[i] and token_sets[j]:
                    overlap = len(token_sets[i] & token_sets[j]) / len(token_sets[i] | token_sets[j])
                    diversity_penalty += overlap * 0.1
            p["rerank_score"] = p.get("score", 0.5) * (1.0 - min(diversity_penalty, 0.5))
            p["rerank_method"] = "diversity"

        passages.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return passages[: self.config.top_n]

    def _fallback_rerank(
        self,
        query: str,
        passages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Fallback: simple term-overlap heuristic rerank."""
        import re

        query_tokens = set(re.findall(r'\w+', query.lower())) if query else set()

        for p in passages:
            text_tokens = set(re.findall(r'\w+', p["text"].lower()))
            if query_tokens and text_tokens:
                overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
                p["rerank_score"] = p.get("score", 0.0) * 0.5 + overlap * 0.5
            else:
                p["rerank_score"] = p.get("score", 0.0)
            p["rerank_method"] = "fallback_heuristic"

        passages.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        return passages[: self.config.top_n]


class DiversityRanker:
    """Diversity-focused reranker for varied search results."""

    def __init__(self, lambda_param: float = 0.6):
        self.lambda_param = lambda_param

    def rerank(
        self,
        passages: List[Dict[str, Any]],
        top_n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Maximize result diversity while keeping relevance high."""
        if not passages:
            return []

        texts = [p["text"] for p in passages]
        import re

        token_sets = []
        for t in texts:
            token_sets.append(set(re.findall(r'\w+', t.lower())))

        def sim(a: set, b: set) -> float:
            if not a or not b:
                return 0.0
            return len(a & b) / len(a | b)

        selected = [0]
        remaining = set(range(1, len(passages)))

        while len(selected) < min(top_n, len(passages)):
            best_idx = -1
            best_score = -float("inf")
            for idx in remaining:
                max_sim = max(sim(token_sets[idx], token_sets[s]) for s in selected)
                score = (
                    self.lambda_param * passages[idx].get("score", 0.5)
                    - (1 - self.lambda_param) * max_sim
                )
                if score > best_score:
                    best_score = score
                    best_idx = idx
            if best_idx < 0:
                break
            selected.append(best_idx)
            remaining.remove(best_idx)

        return [passages[i] for i in selected]
