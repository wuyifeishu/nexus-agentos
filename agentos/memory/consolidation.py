"""
AgentOS v1.14.1 — 长期记忆巩固系统 (Memory Consolidation)。

受 Letta/MemGPT 三层记忆体系启发，在虚拟内存分页器之上增加主动记忆巩固层。
核心机制:
- Reflection: 定期分析对话历史，提取关键事实、模式、用户偏好
- Consolidation: 将 Reflection 结果写入长期向量存储
- Retrieval: 智能检索历史记忆，注入后续对话上下文

与 memory/pager.py 的关系:
- pager.py: 被动分页（上下文窗口溢出时 page_out / keyword search page_in）
- consolidation.py: 主动巩固（定期分析 → 提取 → 向量化存储）
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import (
    Any,
)

# ── Memory Data Models ──────────────────────


class MemoryType(StrEnum):
    """记忆类型。"""

    FACT = "fact"  # 事实性信息
    PREFERENCE = "preference"  # 用户偏好
    PATTERN = "pattern"  # 行为模式
    DECISION = "decision"  # 决策记录
    LESSON = "lesson"  # 经验教训
    CONTEXT = "context"  # 上下文摘要


class MemoryImportance(StrEnum):
    """记忆重要性。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MemoryFragment:
    """记忆片段 — 从对话中提取的原子事实。"""

    memory_id: str = field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:12]}")
    memory_type: MemoryType = MemoryType.FACT
    content: str = ""
    importance: MemoryImportance = MemoryImportance.MEDIUM
    source_messages: list[int] = field(default_factory=list)  # 源自哪些消息
    tags: list[str] = field(default_factory=list)
    confidence: float = 1.0  # 0.0~1.0 置信度
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    embedding: list[float] | None = None  # 向量嵌入（惰性计算）
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "importance": self.importance.value,
            "source_messages": self.source_messages,
            "tags": self.tags,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MemoryFragment:
        return cls(
            memory_id=d.get("memory_id", ""),
            memory_type=MemoryType(d.get("memory_type", "fact")),
            content=d.get("content", ""),
            importance=MemoryImportance(d.get("importance", "medium")),
            source_messages=d.get("source_messages", []),
            tags=d.get("tags", []),
            confidence=d.get("confidence", 1.0),
            created_at=d.get("created_at", time.time()),
            last_accessed=d.get("last_accessed", time.time()),
            access_count=d.get("access_count", 0),
            metadata=d.get("metadata", {}),
        )

    def touch(self) -> None:
        """更新访问时间。"""
        self.last_accessed = time.time()
        self.access_count += 1


@dataclass
class ReflectionResult:
    """一次 Reflection 的输出。"""

    fragments: list[MemoryFragment] = field(default_factory=list)
    summary: str = ""  # 会话级摘要
    contradictions: list[tuple[str, str]] = field(default_factory=list)  # 新旧矛盾
    deprecated_ids: list[str] = field(default_factory=list)  # 需淘汰的旧记忆
    user_profile_update: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def total_fragments(self) -> int:
        return len(self.fragments)

    @property
    def has_insights(self) -> bool:
        return bool(self.fragments or self.summary or self.user_profile_update)


# ── Vector Store Interface ──────────────────


class VectorStoreBackend:
    """向量存储后端抽象。

    支持多种后端: 内存、FAISS、Chroma、Pinecone 等。
    """

    async def add(
        self,
        fragments: list[MemoryFragment],
        embeddings: list[list[float]],
    ) -> list[str]:
        """批量添加记忆片段（含嵌入向量）。返回 memory_ids。"""
        raise NotImplementedError

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_types: list[MemoryType] | None = None,
        min_importance: MemoryImportance = MemoryImportance.LOW,
    ) -> list[tuple[MemoryFragment, float]]:
        """向量相似度搜索。返回 (fragment, score)。"""
        raise NotImplementedError

    async def delete(self, memory_ids: list[str]) -> int:
        """删除指定记忆。返回删除数量。"""
        raise NotImplementedError

    async def count(self) -> int:
        """记忆总数。"""
        raise NotImplementedError


class InMemoryVectorStore(VectorStoreBackend):
    """内存向量存储（开发/测试用）。"""

    def __init__(self):
        self._fragments: dict[str, MemoryFragment] = {}
        self._embeddings: dict[str, list[float]] = {}

    async def add(
        self,
        fragments: list[MemoryFragment],
        embeddings: list[list[float]],
    ) -> list[str]:
        ids = []
        for frag, emb in zip(fragments, embeddings):
            self._fragments[frag.memory_id] = frag
            self._embeddings[frag.memory_id] = emb
            ids.append(frag.memory_id)
        return ids

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_types: list[MemoryType] | None = None,
        min_importance: MemoryImportance = MemoryImportance.LOW,
    ) -> list[tuple[MemoryFragment, float]]:
        results = []
        importance_rank = {
            MemoryImportance.LOW: 0,
            MemoryImportance.MEDIUM: 1,
            MemoryImportance.HIGH: 2,
            MemoryImportance.CRITICAL: 3,
        }
        min_rank = importance_rank[min_importance]

        for mid, emb in self._embeddings.items():
            frag = self._fragments[mid]
            # Type filter
            if filter_types and frag.memory_type not in filter_types:
                continue
            # Importance filter
            if importance_rank[frag.importance] < min_rank:
                continue
            # Cosine similarity
            score = self._cosine_similarity(query_embedding, emb)
            results.append((frag, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    async def delete(self, memory_ids: list[str]) -> int:
        count = 0
        for mid in memory_ids:
            if mid in self._fragments:
                del self._fragments[mid]
                self._embeddings.pop(mid, None)
                count += 1
        return count

    async def count(self) -> int:
        return len(self._fragments)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ── Embedding Provider ──────────────────────


class EmbeddingProvider:
    """嵌入向量生成器抽象。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成嵌入向量。"""
        raise NotImplementedError

    async def embed_single(self, text: str) -> list[float]:
        """单条文本嵌入。"""
        results = await self.embed([text])
        return results[0]


class SimpleHashEmbedding(EmbeddingProvider):
    """简单位次嵌入（开发/测试用，非语义向量）。

    用字符 n-gram 哈希作为伪嵌入，提供基本的相似度。
    生产环境应替换为 OpenAI/Cohere 等真实嵌入模型。
    """

    def __init__(self, dim: int = 128):
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = [0.0] * self.dim
            # Character 3-gram hashing
            for i in range(len(text) - 2):
                gram = text[i : i + 3]
                h = hash(gram) % self.dim
                vec[h] += 1.0
            # L2 normalize
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                vec = [v / norm for v in vec]
            results.append(vec)
        return results


# ── Reflection Engine ───────────────────────


class ReflectionConfig:
    """Reflection 触发配置。"""

    def __init__(
        self,
        min_messages_since_last: int = 10,
        min_seconds_since_last: float = 300.0,  # 5 分钟
        max_conversation_turns: int = 50,
        auto_reflect: bool = True,
    ):
        self.min_messages_since_last = min_messages_since_last
        self.min_seconds_since_last = min_seconds_since_last
        self.max_conversation_turns = max_conversation_turns
        self.auto_reflect = auto_reflect


class ReflectionEngine:
    """记忆反思引擎。

    定期分析对话历史，提取:
    - Facts: 用户提到的具体信息
    - Preferences: 用户偏好与习惯
    - Patterns: 反复出现的行为模式
    - Lessons: 从错误中学到的经验

    Usage:
        engine = ReflectionEngine(llm_reflect_fn, vector_store, embedding_provider)
        # 在 agent loop 中定期调用
        should_reflect = engine.should_reflect(message_count)
        if should_reflect:
            result = await engine.reflect(messages_history)
    """

    def __init__(
        self,
        llm_reflect_fn: Callable[[list[dict], str], Any] | None = None,
        vector_store: Any | None = None,
        embedding_provider: Any | None = None,
        config: ReflectionConfig | None = None,
    ):
        """
        Args:
            llm_reflect_fn: LLM 调用函数，签名 (messages, prompt) -> reflection_text
            vector_store: 向量存储后端
            embedding_provider: 嵌入向量生成器
            config: 触发配置
        """
        self._llm_reflect = llm_reflect_fn
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self.config = config or ReflectionConfig()
        self._last_reflection_time: float = 0.0
        self._message_count_since_reflection: int = 0
        self._reflection_count: int = 0

    def should_reflect(self, current_message_count: int) -> bool:
        """判断是否应该触发 Reflection。"""
        if not self.config.auto_reflect:
            return False
        if self._reflection_count == 0 and current_message_count >= 5:
            return True  # 首次在 5 条消息后触发
        msg_check = self._message_count_since_reflection >= self.config.min_messages_since_last
        time_check = time.time() - self._last_reflection_time >= self.config.min_seconds_since_last
        return msg_check or time_check

    async def reflect(
        self,
        messages: list[dict],
        existing_fragments: list[MemoryFragment] | None = None,
    ) -> ReflectionResult:
        """执行一次 Reflection。

        Args:
            messages: 对话历史（dict 列表，含 role/content）
            existing_fragments: 已有的记忆片段（用于矛盾检测）

        Returns:
            ReflectionResult 含新提取的记忆片段
        """
        self._last_reflection_time = time.time()
        self._reflection_count += 1

        # 1. 构建 Reflection prompt
        prompt = self._build_reflection_prompt(messages, existing_fragments)

        # 2. 调用 LLM 提取记忆
        reflection_text = await self._llm_reflect(messages, prompt)

        # 3. 解析 LLM 输出
        result = self._parse_reflection_output(reflection_text, len(messages))

        # 4. 生成嵌入向量
        if result.fragments:
            texts = [f.content for f in result.fragments]
            embeddings = await self._embedding_provider.embed(texts)
            for frag, emb in zip(result.fragments, embeddings):
                frag.embedding = emb

        # 5. 存入向量库
        if result.fragments:
            await self._vector_store.add(result.fragments, embeddings)

        # 6. 淘汰旧记忆
        if result.deprecated_ids:
            await self._vector_store.delete(result.deprecated_ids)

        # Reset counter
        self._message_count_since_reflection = 0

        return result

    def record_message(self) -> None:
        """记录一条新消息（用于计数触发）。"""
        self._message_count_since_reflection += 1

    async def retrieve_relevant(
        self,
        query: str,
        top_k: int = 5,
        filter_types: list[MemoryType] | None = None,
    ) -> list[MemoryFragment]:
        """检索与查询相关的记忆。

        Args:
            query: 查询文本
            top_k: 返回数量
            filter_types: 按类型过滤

        Returns:
            相关记忆片段列表
        """
        query_embedding = await self._embedding_provider.embed_single(query)
        results = await self._vector_store.search(
            query_embedding,
            top_k=top_k,
            filter_types=filter_types,
        )
        fragments = []
        for frag, score in results:
            frag.touch()
            fragments.append(frag)
        return fragments

    def _build_reflection_prompt(
        self,
        messages: list[dict],
        existing_fragments: list[MemoryFragment] | None = None,
    ) -> str:
        """构建 Reflection prompt。"""
        existing_str = ""
        if existing_fragments:
            existing_items = [
                f"- [{f.memory_type.value}] {f.content}" for f in existing_fragments[:20]
            ]
            existing_str = "\n\nExisting memories:\n" + "\n".join(existing_items)

        return f"""You are a memory consolidation system. Analyze the conversation and extract:

1. FACTS: Specific information mentioned (names, dates, numbers, tools used, decisions made)
2. PREFERENCES: User preferences, likes, dislikes, habits
3. PATTERNS: Repeated behaviors, common workflows, recurring topics
4. LESSONS: What went wrong, what worked, what to avoid next time

For each extracted item, assign:
- type: "fact" | "preference" | "pattern" | "decision" | "lesson"
- importance: "low" | "medium" | "high" | "critical"
- confidence: 0.0 to 1.0

{existing_str}

Output JSON array only:
[{{"type": "...", "content": "...", "importance": "...", "confidence": 0.9, "tags": ["..."]}}]

If nothing significant to extract, output empty array: []"""

    def _parse_reflection_output(
        self,
        text: str,
        source_msg_count: int,
    ) -> ReflectionResult:
        """解析 LLM 输出的 JSON。"""
        result = ReflectionResult()

        try:
            # Extract JSON array
            start = text.find("[")
            end = text.rfind("]")
            if start >= 0 and end > start:
                json_str = text[start : end + 1]
                items = json.loads(json_str)
                for item in items:
                    frag = MemoryFragment(
                        memory_type=MemoryType(item.get("type", "fact")),
                        content=item.get("content", ""),
                        importance=MemoryImportance(item.get("importance", "medium")),
                        confidence=float(item.get("confidence", 1.0)),
                        tags=item.get("tags", []),
                        source_messages=list(
                            range(
                                max(0, source_msg_count - 20),
                                source_msg_count,
                            )
                        ),
                    )
                    if frag.content.strip():
                        result.fragments.append(frag)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

        return result

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "reflection_count": self._reflection_count,
            "last_reflection_time": self._last_reflection_time,
            "messages_since_last": self._message_count_since_reflection,
        }

    # ── Persistence (v1.14.9) ────────────────

    def get_state(self) -> dict[str, Any]:
        """Export ReflectionEngine state for persistence."""
        return {
            "reflection_count": self._reflection_count,
            "last_reflection_time": self._last_reflection_time,
            "message_count_since_reflection": self._message_count_since_reflection,
            "vector_store_fragments": (
                {mid: frag.to_dict() for mid, frag in self._vector_store._fragments.items()}
                if hasattr(self._vector_store, "_fragments") and self._vector_store
                else {}
            ),
            "vector_store_embeddings": {
                mid: list(emb) if emb else []
                for mid, emb in (
                    self._vector_store._embeddings.items()
                    if hasattr(self._vector_store, "_embeddings") and self._vector_store
                    else {}.items()
                )
            },
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore ReflectionEngine from a persisted snapshot."""
        self._reflection_count = state.get("reflection_count", 0)
        self._last_reflection_time = state.get("last_reflection_time", 0.0)
        self._message_count_since_reflection = state.get("message_count_since_reflection", 0)

        if self._vector_store and hasattr(self._vector_store, "_fragments"):
            self._vector_store._fragments.clear()
            self._vector_store._embeddings.clear()
            for mid, frag_data in state.get("vector_store_fragments", {}).items():
                self._vector_store._fragments[mid] = MemoryFragment.from_dict(frag_data)
            for mid, emb in state.get("vector_store_embeddings", {}).items():
                self._vector_store._embeddings[mid] = emb


# ── Memory Context Injector ─────────────────


class MemoryContextInjector:
    """记忆上下文注入器。

    在每次 Agent 对话开始时，自动检索相关历史记忆，
    注入到 system prompt 或上下文中。

    Usage:
        injector = MemoryContextInjector(reflection_engine)
        context = await injector.build_context("user query here")
        messages.insert(0, {"role": "system", "content": context})
    """

    def __init__(
        self,
        reflection_engine: ReflectionEngine,
        max_context_length: int = 2000,
        max_fragments: int = 5,
    ):
        self._engine = reflection_engine
        self.max_context_length = max_context_length
        self.max_fragments = max_fragments

    async def build_context(
        self,
        query: str,
        include_types: list[MemoryType] | None = None,
    ) -> str:
        """构建上下文注入文本。"""
        fragments = await self._engine.retrieve_relevant(
            query,
            top_k=self.max_fragments,
            filter_types=include_types,
        )

        if not fragments:
            return ""

        lines = ["[Relevant Memories]"]
        for frag in fragments:
            lines.append(
                f"- [{frag.memory_type.value}] {frag.content}"
                f" (confidence: {frag.confidence:.0%})"
            )

        context = "\n".join(lines)
        if len(context) > self.max_context_length:
            context = context[: self.max_context_length] + "..."

        return context

    async def build_condensed_context(
        self,
        query: str,
    ) -> str:
        """构建紧凑上下文（仅高重要性记忆）。"""
        fragments = await self._engine.retrieve_relevant(
            query,
            top_k=self.max_fragments,
        )
        # Filter: only HIGH/CRITICAL
        important = [
            f
            for f in fragments
            if f.importance in (MemoryImportance.HIGH, MemoryImportance.CRITICAL)
        ]
        if not important:
            return ""

        lines = ["[Key Context]"]
        for frag in important[:3]:
            lines.append(f"- {frag.content}")

        return "\n".join(lines)


# ── Memory Consolidation Pipeline ───────────


class MemoryConsolidationPipeline:
    """记忆巩固流水线（一键集成）。

    组合 ReflectionEngine + MemoryContextInjector，
    提供开箱即用的记忆系统。

    Usage:
        pipeline = MemoryConsolidationPipeline(llm_fn)
        # 在 agent loop 中:
        pipeline.record_message()
        if pipeline.should_reflect():
            await pipeline.reflect(messages)
        context = await pipeline.get_context(user_query)
    """

    def __init__(
        self,
        llm_reflect_fn: Callable,
        vector_store: VectorStoreBackend | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        config: ReflectionConfig | None = None,
    ):
        self._vector_store = vector_store or InMemoryVectorStore()
        self._embedding_provider = embedding_provider or SimpleHashEmbedding(128)
        self._reflection_engine = ReflectionEngine(
            llm_reflect_fn=llm_reflect_fn,
            vector_store=self._vector_store,
            embedding_provider=self._embedding_provider,
            config=config,
        )
        self._injector = MemoryContextInjector(self._reflection_engine)

    def record_message(self) -> None:
        self._reflection_engine.record_message()

    def should_reflect(self) -> bool:
        return self._reflection_engine.should_reflect(
            self._reflection_engine._message_count_since_reflection
        )

    async def reflect(self, messages: list[dict]) -> ReflectionResult:
        return await self._reflection_engine.reflect(messages)

    async def get_context(self, query: str) -> str:
        return await self._injector.build_context(query)

    async def get_condensed_context(self, query: str) -> str:
        return await self._injector.build_condensed_context(query)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "reflection": self._reflection_engine.stats,
            "total_memories": (
                asyncio.get_event_loop().run_until_complete(self._vector_store.count())
                if asyncio.get_event_loop().is_running()
                else 0
            ),
        }

    # ── Persistence (v1.14.9) ────────────────

    def get_state(self) -> dict[str, Any]:
        """Export consolidation pipeline state for persistence. Delegates to ReflectionEngine."""
        return self._reflection_engine.get_state()

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore consolidation pipeline from a persisted snapshot."""
        self._reflection_engine.restore_state(state)
