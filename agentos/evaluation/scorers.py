"""
AgentOS v0.70 — 评测打分系统。
基因来源: ROUGE/BLEU 经典算法 + 语义相似度

评分策略:
- ROUGE-L: 最长公共子序列召回率 (摘要质量)
- BLEU: n-gram精确率 (翻译质量)
- Semantic: 基于embedding的语义相似度
- Exact: 精确匹配
- Contains: 包含匹配
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable


# ── ROUGE-L ─────────────────────────────────────

def _lcs_length(x: list, y: list) -> int:
    """最长公共子序列长度（DP优化版）。"""
    if len(x) < len(y):
        x, y = y, x
    prev = [0] * (len(y) + 1)
    for i in range(1, len(x) + 1):
        curr = [0] * (len(y) + 1)
        for j in range(1, len(y) + 1):
            if x[i - 1] == y[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    return prev[len(y)]


def rouge_l(reference: str, candidate: str) -> float:
    """ROUGE-L F1 score (character-level)。"""
    if not reference or not candidate:
        return 0.0

    ref_chars = list(reference)
    cand_chars = list(candidate)
    lcs = _lcs_length(ref_chars, cand_chars)

    if len(cand_chars) == 0 or len(ref_chars) == 0:
        return 0.0

    recall = lcs / len(ref_chars)
    precision = lcs / len(cand_chars)

    if recall + precision == 0:
        return 0.0
    return 2 * recall * precision / (recall + precision)


# ── BLEU ────────────────────────────────────────

def _ngrams(tokens: list[str], n: int) -> Counter:
    return Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def bleu(reference: str, candidate: str, max_n: int = 4) -> float:
    """BLEU score (token-level, un-smoothed)。"""
    ref_tokens = _tokenize(reference)
    cand_tokens = _tokenize(candidate)

    if not cand_tokens or not ref_tokens:
        return 0.0

    precisions = []
    for n in range(1, max_n + 1):
        ref_ngrams = _ngrams(ref_tokens, n)
        cand_ngrams = _ngrams(cand_tokens, n)

        if not cand_ngrams:
            precisions.append(0.0)
            continue

        clipped = sum(min(cand_ngrams[ng], ref_ngrams.get(ng, 0)) for ng in cand_ngrams)
        precisions.append(clipped / sum(cand_ngrams.values()))

    if any(p == 0 for p in precisions):
        return 0.0

    # Brevity penalty
    bp = min(1.0, math.exp(1 - len(ref_tokens) / max(len(cand_tokens), 1)))

    # Geometric mean of n-gram precisions
    log_sum = sum(math.log(p) for p in precisions)
    return bp * math.exp(log_sum / max_n)


def _tokenize(text: str) -> list[str]:
    """英文分词 + 数字/标点分离。"""
    # Split on whitespace, keep punctuation as separate tokens for Chinese
    text = text.lower()
    # For Chinese: character-level
    if re.search(r'[\u4e00-\u9fff]', text):
        tokens = []
        for ch in text:
            if ch.strip():
                tokens.append(ch)
        return tokens
    # English
    return re.findall(r'\w+|[^\w\s]', text)


# ── Semantic Similarity ─────────────────────────

def semantic_similarity(candidate: str, reference: str, embedder: Any = None) -> float:
    """
    基于embedding的语义相似度（cosine similarity）。
    需要传入embedder实例或使用默认LocalEmbedder。
    """
    if not candidate or not reference:
        return 0.0

    if embedder is None:
        from agentos.cache.embedder import LocalEmbedder
        embedder = LocalEmbedder()

    try:
        emb_cand = embedder.embed(candidate)
        emb_ref = embedder.embed(reference)
        from agentos.cache.embedder import cosine_similarity as cos_sim
        return float(cos_sim(emb_cand, emb_ref))
    except Exception:
        return 0.0


# ── Exact / Contains ────────────────────────────

def exact_match(reference: str, candidate: str) -> float:
    """精确匹配：返回 0.0 或 1.0。"""
    return 1.0 if reference.strip() == candidate.strip() else 0.0


def contains_match(reference: str, candidate: str) -> float:
    """候选文本是否包含参考文本（忽略大小写）。"""
    return 1.0 if reference.lower() in candidate.lower() else 0.0


# ── Composite Scorer ────────────────────────────

@dataclass
class ScoringStrategy:
    """评分配置策略。"""

    name: str = "composite"
    weights: dict[str, float] = field(default_factory=lambda: {
        "rouge_l": 0.3,
        "bleu": 0.2,
        "exact": 0.2,
        "contains": 0.3,
    })
    pass_threshold: float = 0.6


@dataclass
class ScoreResult:
    """评分结果。"""

    reference: str
    candidate: str
    scores: dict[str, float] = field(default_factory=dict)
    weighted_score: float = 0.0
    passed: bool = False
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "scores": self.scores,
            "weighted_score": round(self.weighted_score, 4),
            "passed": self.passed,
            "details": self.details,
        }


class CompositeScorer:
    """
    复合评分器 — 多策略加权。
    """

    def __init__(self, strategy: ScoringStrategy | None = None):
        self.strategy = strategy or ScoringStrategy()

    def score(self, reference: str, candidate: str, embedder: Any = None) -> ScoreResult:
        """对候选文本打分。"""
        scores: dict[str, float] = {}

        # ROUGE-L
        if "rouge_l" in self.strategy.weights:
            scores["rouge_l"] = rouge_l(reference, candidate)

        # BLEU
        if "bleu" in self.strategy.weights:
            scores["bleu"] = bleu(reference, candidate)

        # Exact
        if "exact" in self.strategy.weights:
            scores["exact"] = exact_match(reference, candidate)

        # Contains
        if "contains" in self.strategy.weights:
            scores["contains"] = contains_match(reference, candidate)

        # Semantic
        if "semantic" in self.strategy.weights or self.strategy.weights.get("semantic", 0) > 0:
            scores["semantic"] = semantic_similarity(candidate, reference, embedder)

        # Weighted
        weighted = sum(
            scores.get(k, 0) * w
            for k, w in self.strategy.weights.items()
        )

        passed = weighted >= self.strategy.pass_threshold
        details = ", ".join(f"{k}={v:.3f}" for k, v in scores.items())

        return ScoreResult(
            reference=reference,
            candidate=candidate,
            scores=scores,
            weighted_score=weighted,
            passed=passed,
            details=details,
        )

    def batch_score(
        self,
        pairs: list[tuple[str, str]],
        embedder: Any = None,
    ) -> list[ScoreResult]:
        """批量评分。"""
        return [self.score(ref, cand, embedder) for ref, cand in pairs]


# ── Pre-built Strategies ────────────────────────

STRATEGY_CODE_GEN = ScoringStrategy(
    name="code_generation",
    weights={"rouge_l": 0.1, "bleu": 0.1, "exact": 0.3, "contains": 0.5},
    pass_threshold=0.5,
)

STRATEGY_QA = ScoringStrategy(
    name="question_answering",
    weights={"rouge_l": 0.3, "contains": 0.5, "exact": 0.2},
    pass_threshold=0.6,
)

STRATEGY_SUMMARY = ScoringStrategy(
    name="summarization",
    weights={"rouge_l": 0.5, "bleu": 0.1, "semantic": 0.4},
    pass_threshold=0.5,
)

STRATEGY_TRANSLATION = ScoringStrategy(
    name="translation",
    weights={"bleu": 0.6, "rouge_l": 0.2, "semantic": 0.2},
    pass_threshold=0.4,
)
