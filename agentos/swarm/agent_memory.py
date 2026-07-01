"""
v1.9.7: Agent Memory System — layered memory with context window management.

Three-tier memory architecture:
- WorkingMemory: current task context, small capacity, fast access
- ShortTermMemory: recent N conversation rounds, sliding window with summarization
- LongTermMemory: vector-based semantic retrieval for historical knowledge

ContextWindowManager: auto-trim/compress context to fit token budgets.
"""

from __future__ import annotations

import heapq
import json
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MemoryEntry:
    """A single memory entry."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    content: str = ""
    role: str = "system"    # system, user, assistant, tool
    timestamp: float = field(default_factory=time.time)
    importance: float = 0.5  # 0.0-1.0
    ttl: float = 0.0        # Time-to-live in seconds, 0 = never expire
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None  # For long-term vector search
    summary: str = ""       # Compressed version for context window


# ── Working Memory ────────────────────────────────────────────────

class WorkingMemory:
    """Ultra-fast, small-capacity memory for the current task.

    Holds task description, active goals, intermediate results.
    Max entries enforced — oldest evicted on overflow.
    """

    def __init__(self, max_entries: int = 20):
        self.max_entries = max_entries
        self._entries: OrderedDict[str, MemoryEntry] = OrderedDict()
        self.task_goal: str = ""
        self.active_subtask: str = ""
        self.scratchpad: dict[str, Any] = {}

    def add(self, entry: MemoryEntry) -> None:
        self._entries[entry.id] = entry
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def set_task(self, goal: str, subtask: str = "") -> None:
        self.task_goal = goal
        self.active_subtask = subtask or goal

    def get_all(self) -> list[MemoryEntry]:
        return list(self._entries.values())

    def get_last(self, n: int = 5) -> list[MemoryEntry]:
        return list(self._entries.values())[-n:]

    def clear(self) -> None:
        self._entries.clear()
        self.scratchpad.clear()

    def to_context(self, max_tokens: int = 500) -> str:
        """Serialize working memory as context string for LLM."""
        parts = []
        if self.task_goal:
            parts.append(f"[Task] {self.task_goal}")
        if self.active_subtask and self.active_subtask != self.task_goal:
            parts.append(f"[SubTask] {self.active_subtask}")
        for entry in list(self._entries.values())[-5:]:
            content = entry.summary or entry.content
            if len(content) > 200:
                content = content[:197] + "..."
            parts.append(f"[{entry.role}] {content}")
        result = "\n".join(parts)
        if self._estimate_tokens(result) > max_tokens:
            # Truncate from front
            lines = result.split("\n")
            while lines and self._estimate_tokens("\n".join(lines)) > max_tokens:
                lines.pop(0)
            result = "\n".join(lines)
        return result

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation: ~4 chars per token."""
        return max(1, len(text) // 4)


# ── Short-Term Memory ─────────────────────────────────────────────

class ShortTermMemory:
    """Sliding window of recent conversation rounds.

    Auto-summarizes old rounds to maintain a compact window.
    Supports importance-based retention.
    """

    def __init__(
        self,
        max_rounds: int = 50,
        auto_summarize: bool = True,
        summarize_threshold: int = 20,  # Summarize when rounds > threshold
        keep_recent: int = 10,          # Keep N most recent rounds raw
    ):
        self.max_rounds = max_rounds
        self.auto_summarize = auto_summarize
        self.summarize_threshold = summarize_threshold
        self.keep_recent = keep_recent

        self._rounds: deque[list[MemoryEntry]] = deque()
        self._summaries: list[str] = []  # Compressed old rounds
        self.total_rounds = 0

    def add_round(self, entries: list[MemoryEntry]) -> None:
        """Add a full conversation round."""
        self._rounds.append(entries)
        self.total_rounds += 1

        # Enforce max rounds
        while len(self._rounds) > self.max_rounds:
            evicted = self._rounds.popleft()
            if self.auto_summarize:
                summary = self._summarize_round(evicted)
                if summary:
                    self._summaries.append(summary)

        # Auto-summarize middle rounds when over threshold
        if self.auto_summarize and len(self._rounds) > self.summarize_threshold:
            self._compress_middle()

    def _compress_middle(self) -> None:
        """Compress rounds between recent keepers and front."""
        keep_count = min(self.keep_recent, len(self._rounds))
        recent = list(self._rounds)[-keep_count:]
        middle = list(self._rounds)[:-keep_count] if keep_count < len(self._rounds) else []

        if not middle:
            return

        # Summarize middle rounds
        for entries in middle:
            summary = self._summarize_round(entries)
            if summary:
                self._summaries.append(summary)

        # Replace deque with only recent rounds
        self._rounds = deque(recent)

    def _summarize_round(self, entries: list[MemoryEntry]) -> str:
        """Create a compressed summary of a round."""
        if not entries:
            return ""

        # Collect key content
        parts = []
        for entry in entries:
            content = entry.content
            if len(content) > 100:
                content = content[:97] + "..."
            parts.append(f"{entry.role}: {content}")

        if not parts:
            return ""

        timestamp = entries[0].timestamp if entries else time.time()
        return f"[Round@{timestamp:.0f}] " + " | ".join(parts)

    def get_context(
        self,
        include_summaries: bool = True,
        max_rounds: int = 15,
    ) -> list[MemoryEntry]:
        """Get flattened context entries."""
        flat: list[MemoryEntry] = []

        # Add summaries as system entries
        if include_summaries:
            for summary in self._summaries[-3:]:  # Keep last 3 summaries
                flat.append(MemoryEntry(
                    content=f"[History Summary] {summary}",
                    role="system",
                    importance=0.3,
                ))

        # Add recent rounds
        recent_rounds = list(self._rounds)[-max_rounds:]
        for entries in recent_rounds:
            flat.extend(entries)

        return flat

    def clear(self) -> None:
        self._rounds.clear()
        self._summaries.clear()
        self.total_rounds = 0


# ── Long-Term Memory ──────────────────────────────────────────────

class LongTermMemory:
    """Vector-based semantic memory for historical knowledge retrieval.

    Stores important memories with embeddings. Supports cosine-similarity search.
    Falls back to keyword search when no embeddings available.
    """

    def __init__(
        self,
        max_entries: int = 10000,
        importance_threshold: float = 0.4,  # Only store entries above this importance
        persist_path: str = "",
    ):
        self.max_entries = max_entries
        self.importance_threshold = importance_threshold
        self.persist_path = persist_path

        self._entries: dict[str, MemoryEntry] = {}
        self._embeddings: dict[str, list[float]] = {}  # entry_id → embedding

        self._embedder: Any = None  # Lazy-loaded embedder

    def add(self, entry: MemoryEntry) -> None:
        """Store a memory entry. Only stores if importance >= threshold."""
        if entry.importance < self.importance_threshold:
            return

        self._entries[entry.id] = entry
        if entry.embedding:
            self._embeddings[entry.id] = entry.embedding

        # Evict oldest if over capacity
        while len(self._entries) > self.max_entries:
            oldest_id = min(
                self._entries.keys(),
                key=lambda k: self._entries[k].timestamp,
            )
            del self._entries[oldest_id]
            self._embeddings.pop(oldest_id, None)

    def search(
        self,
        query: str,
        top_k: int = 5,
        query_embedding: list[float] | None = None,
    ) -> list[MemoryEntry]:
        """Semantic search over stored memories.

        Uses cosine similarity if embeddings available, else keyword overlap.
        """
        if self._embeddings and query_embedding:
            return self._vector_search(query_embedding, top_k)
        return self._keyword_search(query, top_k)

    def search_keywords(
        self,
        keywords: list[str],
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """Search memories by keyword overlap."""
        results = []
        for entry in self._entries.values():
            content_lower = entry.content.lower()
            score = sum(1 for kw in keywords if kw.lower() in content_lower)
            if score > 0:
                results.append((score, entry))
        results.sort(key=lambda x: (-x[0], -x[1].importance))
        return [entry for _, entry in results[:top_k]]

    def search_by_timerange(
        self,
        start: float,
        end: float | None = None,
        top_k: int = 10,
    ) -> list[MemoryEntry]:
        """Search memories by time range."""
        end = end or time.time()
        results = [
            entry for entry in self._entries.values()
            if start <= entry.timestamp <= end
        ]
        results.sort(key=lambda e: e.timestamp, reverse=True)
        return results[:top_k]

    def _vector_search(
        self,
        query_emb: list[float],
        top_k: int,
    ) -> list[MemoryEntry]:
        """Cosine similarity search."""
        scores = []
        for eid, emb in self._embeddings.items():
            sim = self._cosine_similarity(query_emb, emb)
            scores.append((sim, eid))
        scores.sort(reverse=True)
        return [self._entries[eid] for _, eid in scores[:top_k] if eid in self._entries]

    def _keyword_search(self, query: str, top_k: int) -> list[MemoryEntry]:
        """Fallback keyword overlap search."""
        query_words = set(query.lower().split())
        if not query_words:
            return []
        return self.search_keywords(list(query_words), top_k)

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Cosine similarity between two vectors."""
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def export_important(self, top_k: int = 20) -> list[MemoryEntry]:
        """Export most important entries."""
        entries = sorted(
            self._entries.values(),
            key=lambda e: (e.importance, e.timestamp),
            reverse=True,
        )
        return entries[:top_k]

    def clear(self) -> None:
        self._entries.clear()
        self._embeddings.clear()

    def save(self, path: str = "") -> None:
        """Persist to disk (without embeddings)."""
        save_path = path or self.persist_path
        if not save_path:
            return

        data = []
        for entry in self._entries.values():
            data.append({
                "id": entry.id,
                "content": entry.content,
                "role": entry.role,
                "timestamp": entry.timestamp,
                "importance": entry.importance,
                "metadata": entry.metadata,
            })

        with open(save_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str = "") -> int:
        """Load from disk."""
        load_path = path or self.persist_path
        if not load_path:
            return 0

        try:
            with open(load_path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return 0

        count = 0
        for item in data:
            entry = MemoryEntry(
                id=item.get("id", uuid.uuid4().hex[:8]),
                content=item.get("content", ""),
                role=item.get("role", "system"),
                timestamp=item.get("timestamp", time.time()),
                importance=item.get("importance", 0.5),
                metadata=item.get("metadata", {}),
            )
            self._entries[entry.id] = entry
            count += 1

        return count


# ── Context Window Manager ────────────────────────────────────────

@dataclass
class ContextBudget:
    """Token budget for context window management."""

    total_tokens: int = 4096           # Max total tokens
    system_reserved: int = 512         # Reserved for system prompt
    working_memory_budget: int = 640   # Budget for working memory
    short_term_budget: int = 1536      # Budget for short-term memory
    long_term_budget: int = 512        # Budget for injected long-term memories
    query_budget: int = 896            # Budget for current query
    safety_margin: int = 128           # Safety margin


class ContextWindowManager:
    """Manages token budgets and assembles context windows.

    Automatically trims/compresses content to fit within token budgets.
    Handles the three-tier memory system's context assembly.
    """

    def __init__(self, budget: ContextBudget | None = None):
        self.budget = budget or ContextBudget()

    def assemble(
        self,
        working: WorkingMemory,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        current_query: str = "",
        retrieval_query: str = "",
    ) -> str:
        """Assemble a full context window from all memory tiers.

        Returns a string ready to prepend to the LLM prompt.
        """
        sections = []

        # 1. Working memory context
        wm_ctx = working.to_context(max_tokens=self.budget.working_memory_budget)
        if wm_ctx:
            sections.append(("Working Memory", wm_ctx, self.budget.working_memory_budget))

        # 2. Short-term memory context
        st_entries = short_term.get_context(include_summaries=True, max_rounds=15)
        st_ctx = self._entries_to_context(st_entries, self.budget.short_term_budget)
        if st_ctx:
            sections.append(("Recent History", st_ctx, self.budget.short_term_budget))

        # 3. Long-term memory (semantic retrieval)
        lt_entries = []
        if retrieval_query:
            lt_entries = long_term.search(retrieval_query, top_k=5)
        else:
            lt_entries = long_term.export_important(top_k=5)

        if lt_entries:
            lt_ctx = self._entries_to_context(lt_entries, self.budget.long_term_budget)
            if lt_ctx:
                sections.append(("Relevant Memories", lt_ctx, self.budget.long_term_budget))

        # 4. Current query
        query_section = current_query
        if query_section:
            est_tokens = self._estimate_tokens(query_section)
            if est_tokens > self.budget.query_budget:
                query_section = self._truncate_text(query_section, self.budget.query_budget)
            sections.append(("Current Task", query_section, self.budget.query_budget))

        # Assemble final context
        final_parts = []
        for name, content, _ in sections:
            final_parts.append(f"--- {name} ---\n{content}")

        return "\n\n".join(final_parts)

    def fit_to_budget(self, text: str, max_tokens: int) -> str:
        """Trim text to fit within token budget."""
        if self._estimate_tokens(text) <= max_tokens:
            return text
        return self._truncate_text(text, max_tokens)

    def _entries_to_context(self, entries: list[MemoryEntry], max_tokens: int) -> str:
        """Convert memory entries to context string, fitting budget."""
        if not entries:
            return ""

        lines = []
        token_count = 0

        for entry in entries:
            content = entry.summary or entry.content
            line = f"[{entry.role}] {content}"
            line_tokens = self._estimate_tokens(line)

            if token_count + line_tokens > max_tokens:
                # Try truncated version
                available = max_tokens - token_count - 10
                if available > 20:
                    truncated = content[:available * 4]
                    line = f"[{entry.role}] {truncated}..."
                    token_count += self._estimate_tokens(line)
                break

            lines.append(line)
            token_count += line_tokens

        return "\n".join(lines)

    def _truncate_text(self, text: str, max_tokens: int) -> str:
        """Truncate text from the beginning to fit token budget."""
        # Estimate char budget: ~4 chars per token
        char_budget = max_tokens * 4
        if len(text) <= char_budget:
            return text

        # Keep last char_budget characters for relevance
        return "...(truncated) " + text[-char_budget:]

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation."""
        return max(1, len(text) // 4)


# ── Unified Agent Memory ──────────────────────────────────────────

class AgentMemory:
    """Unified memory system combining all three tiers + context management.

    High-level API for agent memory operations:
    - Remember conversation rounds
    - Retrieve relevant history
    - Assemble context window

    Usage:
        memory = AgentMemory()
        memory.add_round([user_msg, assistant_msg])
        context = memory.get_context(query="What files did I create yesterday?")
    """

    def __init__(
        self,
        working_max: int = 20,
        short_term_max_rounds: int = 50,
        long_term_max: int = 10000,
        budget: ContextBudget | None = None,
    ):
        self.working = WorkingMemory(max_entries=working_max)
        self.short_term = ShortTermMemory(max_rounds=short_term_max_rounds)
        self.long_term = LongTermMemory(max_entries=long_term_max)
        self.window_manager = ContextWindowManager(budget=budget)

    def add_round(
        self,
        entries: list[MemoryEntry],
        importance: float = 0.5,
    ) -> None:
        """Add a full conversation round to memory."""
        self.short_term.add_round(entries)

        # Store important entries to long-term
        for entry in entries:
            if entry.importance >= 0.4:
                self.long_term.add(entry)

    def set_task(self, goal: str, subtask: str = "") -> None:
        """Set current task context in working memory."""
        self.working.set_task(goal, subtask)

    def remember(
        self,
        content: str,
        role: str = "system",
        importance: float = 0.5,
        ttl: float = 0.0,
        metadata: dict | None = None,
    ) -> MemoryEntry:
        """Store a single memory entry."""
        entry = MemoryEntry(
            content=content,
            role=role,
            importance=importance,
            ttl=ttl,
            metadata=metadata or {},
        )
        self.working.add(entry)
        if importance >= 0.6:
            self.long_term.add(entry)
        return entry

    def recall(
        self,
        query: str,
        top_k: int = 5,
        include_short_term: bool = True,
        include_long_term: bool = True,
    ) -> list[MemoryEntry]:
        """Search across memory tiers."""
        results: list[MemoryEntry] = []

        if include_short_term:
            st_entries = self.short_term.get_context(include_summaries=True)
            # Simple keyword filter on short-term
            query_words = set(query.lower().split())
            for entry in st_entries:
                score = sum(1 for w in query_words if w in entry.content.lower())
                if score > 0:
                    results.append(entry)

        if include_long_term:
            lt_results = self.long_term.search(query, top_k=top_k)
            for entry in lt_results:
                if entry not in results:
                    results.append(entry)

        # Sort by importance then timestamp
        results.sort(key=lambda e: (e.importance, e.timestamp), reverse=True)
        return results[:top_k]

    def get_context(self, query: str = "") -> str:
        """Assemble full context window for the current task."""
        return self.window_manager.assemble(
            working=self.working,
            short_term=self.short_term,
            long_term=self.long_term,
            current_query=query,
            retrieval_query=query,
        )

    def clear_working(self) -> None:
        self.working.clear()

    def clear_all(self) -> None:
        self.working.clear()
        self.short_term.clear()
        self.long_term.clear()
