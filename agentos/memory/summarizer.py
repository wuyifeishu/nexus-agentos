"""
AgentOS v0.60 Memory Summarizer — 上下文压缩与记忆管理。
递归摘要 / 重要性评分 / 滑动窗口 / 混合记忆策略。
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class MemoryType(StrEnum):
    """记忆类型枚举。"""

    EPISODIC = "episodic"  # 对话片段
    SEMANTIC = "semantic"  # 知识点
    PROCEDURAL = "procedural"  # 操作步骤
    WORKING = "working"  # 当前上下文


@dataclass
class MemoryChunk:
    """记忆块。"""

    id: str
    content: str
    mtype: MemoryType = MemoryType.EPISODIC
    timestamp: float = field(default_factory=time.time)
    importance: float = 0.5  # 0~1
    access_count: int = 0
    token_estimate: int = 0
    summary: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.token_estimate == 0:
            self.token_estimate = max(1, len(self.content) // 3)


class ImportanceScorer:
    """多维度重要性评分。"""

    WEIGHTS = {
        "recency": 0.20,  # 时间衰减
        "access_frequency": 0.15,  # 访问频率
        "content_length": 0.10,  # 内容长度（过短=噪音，适中=有用）
        "keyword_density": 0.25,  # 关键信息密度
        "task_relevance": 0.30,  # 任务相关性(外部传入)
    }

    _IMPORTANT_KEYWORDS = [
        "error",
        "exception",
        "fail",
        "critical",
        "important",
        "key",
        "decision",
        "conclusion",
        "result",
        "summary",
        "must",
        "urgent",
        "deadline",
        "blocker",
        "fix",
    ]

    @classmethod
    def score(
        cls, chunk: MemoryChunk, task_relevance: float = 0.0, current_time: float | None = None
    ) -> float:
        now = current_time or time.time()
        scores = {}

        # 1. 时间衰减（指数衰减，半衰期24h）
        age_hours = (now - chunk.timestamp) / 3600
        scores["recency"] = math.exp(-age_hours * math.log(2) / 24)

        # 2. 访问频率
        scores["access_frequency"] = min(1.0, chunk.access_count / 10.0)

        # 3. 内容长度评分（100~2000 token 最佳）
        t = chunk.token_estimate
        if t < 50:
            scores["content_length"] = t / 50 * 0.3
        elif t <= 2000:
            scores["content_length"] = 1.0
        else:
            scores["content_length"] = max(0.1, 2000 / t)

        # 4. 关键词密度
        lowered = chunk.content.lower()
        keyword_hits = sum(1 for kw in cls._IMPORTANT_KEYWORDS if kw in lowered)
        scores["keyword_density"] = min(1.0, keyword_hits / 5.0)

        # 5. 任务相关性
        scores["task_relevance"] = task_relevance

        total = sum(cls.WEIGHTS[k] * scores[k] for k in cls.WEIGHTS)
        return round(min(1.0, max(0.0, total)), 4)


class MemorySummarizer:
    """记忆摘要器：递归压缩 + 重要性排序 + 滑动窗口裁剪。"""

    def __init__(
        self, max_context_tokens: int = 8000, summarizer_fn: Callable[[str], str] | None = None
    ):
        self.max_context_tokens = max_context_tokens
        self._summarizer = summarizer_fn or self._default_summarizer

    @staticmethod
    def _default_summarizer(text: str) -> str:
        """默认摘要器：提取首句 + 关键片段。"""
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) <= 3:
            return " ".join(lines)
        first = lines[0][:200]
        # 截取中间代表性句子
        mid = len(lines) // 2
        snippet = lines[mid][:150] if mid < len(lines) else ""
        return f"[{len(lines)}行] {first} ... {snippet}".strip()[:500]

    # ── 递归摘要 ───────────────────────────────────────────────────────────

    def recursive_summarize(
        self, chunks: list[MemoryChunk], target_ratio: float = 0.3
    ) -> list[MemoryChunk]:
        """递归压缩：反复摘要直到总 token 数降至目标比例以下。"""
        current = list(chunks)
        total_tokens = sum(c.token_estimate for c in current)
        target_tokens = int(self.max_context_tokens * target_ratio)

        while total_tokens > target_tokens and len(current) > 1:
            # 合并相邻 chunk 并摘要
            merged: list[MemoryChunk] = []
            for i in range(0, len(current) - 1, 2):
                combined = current[i].content + "\n" + current[i + 1].content
                summary = self._summarizer(combined)
                merged.append(
                    MemoryChunk(
                        id=f"sum_{i}",
                        content=summary,
                        mtype=MemoryType.SEMANTIC,
                        importance=max(current[i].importance, current[i + 1].importance),
                    )
                )
            if len(current) % 2 == 1:
                merged.append(current[-1])
            current = merged
            total_tokens = sum(c.token_estimate for c in current)

        return current

    # ── 重要性排序 ─────────────────────────────────────────────────────────

    def rank_and_prune(self, chunks: list[MemoryChunk], max_chunks: int = 20) -> list[MemoryChunk]:
        """按重要性排序并截断。"""
        scored = [(ImportanceScorer.score(c), c) for c in chunks]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:max_chunks]]

    # ── 滑动窗口 ───────────────────────────────────────────────────────────

    def sliding_window(self, chunks: list[MemoryChunk], window_size: int = 10) -> list[MemoryChunk]:
        """最近N条记忆（按时间排序）。"""
        sorted_chunks = sorted(chunks, key=lambda c: c.timestamp, reverse=True)
        return sorted_chunks[:window_size]

    # ── 混合策略 ───────────────────────────────────────────────────────────

    def build_context(
        self, chunks: list[MemoryChunk], strategy: str = "hybrid"
    ) -> list[MemoryChunk]:
        """构建上下文：混合策略 = 重要记忆 + 最近窗口。"""
        if strategy == "recency":
            return self.sliding_window(chunks, 15)
        elif strategy == "importance":
            return self.rank_and_prune(chunks, 15)
        elif strategy == "hybrid":
            recent = set(c.id for c in self.sliding_window(chunks, 7))
            important = self.rank_and_prune(chunks, 15)
            hybrid: list[MemoryChunk] = []
            seen: set[str] = set()
            for c in important:
                if c.id not in seen:
                    hybrid.append(c)
                    seen.add(c.id)
            for c in chunks:
                if c.id in recent and c.id not in seen:
                    hybrid.append(c)
                    seen.add(c.id)
            return hybrid
        return chunks

    def estimate_tokens(self, chunks: list[MemoryChunk]) -> int:
        return sum(c.token_estimate for c in chunks)


class ConversationMemory:
    """对话记忆：按轮次组织，支持压缩与重置。"""

    def __init__(self, max_turns: int = 50, summarizer: MemorySummarizer | None = None):
        self.max_turns = max_turns
        self.turns: list[MemoryChunk] = []
        self.summarizer = summarizer or MemorySummarizer()
        self._backup: list[MemoryChunk] = []

    def add_turn(self, role: str, content: str, metadata: dict | None = None):
        chunk = MemoryChunk(
            id=f"turn_{len(self.turns)}",
            content=f"[{role}] {content}",
            mtype=MemoryType.EPISODIC,
            importance=0.6 if role == "user" else 0.4,
            metadata=metadata or {},
        )
        self.turns.append(chunk)
        if len(self.turns) > self.max_turns:
            self.compress()

    def compress(self):
        """压缩旧对话为摘要。"""
        if len(self.turns) <= self.max_turns:
            return
        old_half = self.turns[: len(self.turns) // 2]
        self._backup = old_half
        compressed = self.summarizer.recursive_summarize(old_half, target_ratio=0.2)
        self.turns = compressed + self.turns[len(self.turns) // 2 :]

    def clear(self):
        self.turns.clear()
        self._backup.clear()

    def restore(self):
        """从备份恢复完整对话。"""
        if self._backup:
            self.turns = self._backup + self.turns
            self._backup.clear()

    @property
    def total_tokens(self) -> int:
        return self.summarizer.estimate_tokens(self.turns)
