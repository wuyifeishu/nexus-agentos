"""  # noqa: E501
Conversation Memory with sliding window management.

Manages multi-turn conversations with configurable window strategies:
- Sliding window (FIFO with max turns)
- Token-aware window (trim by token count)
- Importance-weighted (keep high-importance turns, evict low)
- Hybrid (combine token budget + importance scoring)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WindowStrategy(Enum):
    SLIDING = "sliding"
    """FIFO: keep last N turns, evict oldest."""

    TOKEN_AWARE = "token_aware"
    """Keep as many turns as fit within token budget."""

    IMPORTANCE = "importance"
    """Keep high-importance turns, evict lowest scores."""

    HYBRID = "hybrid"
    """Token budget + importance scoring combined."""


@dataclass
class ConversationTurn:
    """Single turn in a conversation."""

    role: str
    """'user', 'assistant', 'system', 'tool'."""

    content: str
    timestamp: float = 0.0
    token_count: int = 0
    importance: float = 0.5
    """0.0 = least important, 1.0 = most important."""

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WindowConfig:
    """Configuration for conversation window management."""

    strategy: WindowStrategy = WindowStrategy.SLIDING

    max_turns: int = 20
    """Max conversation turns (sliding window)."""

    max_tokens: int = 8000
    """Max total token budget (token_aware / hybrid)."""

    importance_threshold: float = 0.3
    """Minimum importance score to keep (importance / hybrid)."""

    system_prompt: str | None = None
    """System prompt always kept at top of window."""

    preserve_last_n: int = 2
    """Always keep the last N turns regardless of eviction rules."""


class ConversationMemory:
    """
    Multi-turn conversation memory with sliding window strategies.

    Example::

        mem = ConversationMemory(WindowConfig(strategy=WindowStrategy.HYBRID, max_tokens=4000))
        mem.add_turn(ConversationTurn(role="user", content="Hello"))
        mem.add_turn(ConversationTurn(role="assistant", content="Hi! How can I help?"))
        messages = mem.get_messages()  # [{"role": "user", "content": "Hello"}, ...]
    """

    def __init__(self, config: WindowConfig | None = None):
        self.config = config or WindowConfig()
        self._turns: list[ConversationTurn] = []
        self._token_count_cache: int = 0

    def add_turn(self, turn: ConversationTurn) -> None:
        """Add a turn and apply window eviction if needed."""
        self._turns.append(turn)
        self._token_count_cache += (
            turn.token_count if turn.token_count > 0 else self._estimate_tokens(turn.content)
        )
        self._apply_window()

    def add_user_message(self, content: str, importance: float = 0.5) -> None:
        self.add_turn(
            ConversationTurn(
                role="user",
                content=content,
                importance=importance,
                token_count=self._estimate_tokens(content),
            )
        )

    def add_assistant_message(self, content: str, importance: float = 0.5) -> None:
        self.add_turn(
            ConversationTurn(
                role="assistant",
                content=content,
                importance=importance,
                token_count=self._estimate_tokens(content),
            )
        )

    def add_system_message(self, content: str) -> None:
        self.add_turn(
            ConversationTurn(
                role="system",
                content=content,
                importance=1.0,
                token_count=self._estimate_tokens(content),
            )
        )

    def _apply_window(self) -> None:
        """Apply the configured window strategy to evict excess turns."""
        strategy = self.config.strategy

        if strategy == WindowStrategy.SLIDING:
            self._evict_sliding()
        elif strategy == WindowStrategy.TOKEN_AWARE:
            while (
                self._token_count_cache > self.config.max_tokens
                and len(self._turns) > self.config.preserve_last_n
            ):
                self._evict_one(0)
        elif strategy == WindowStrategy.IMPORTANCE:
            self._evict_by_importance()
        elif strategy == WindowStrategy.HYBRID:
            self._evict_hybrid()

    def _evict_sliding(self) -> None:
        """FIFO: remove oldest turns exceeding max_turns."""
        preserve = self.config.preserve_last_n
        max_keep = self.config.max_turns

        while len(self._turns) > max_keep:
            evict_idx = 0
            # Don't evict system prompt
            if self._turns[0].role == "system":
                evict_idx = 1
            # Don't evict preserved last N turns
            if len(self._turns) - evict_idx <= preserve:
                break
            self._evict_one(evict_idx)

    def _evict_by_importance(self) -> None:
        """Evict lowest-importance turns above threshold."""
        preserve = self.config.preserve_last_n
        threshold = self.config.importance_threshold

        while True:
            candidates = [
                (i, t)
                for i, t in enumerate(self._turns)
                if t.role != "system"
                and i < len(self._turns) - preserve
                and t.importance < threshold
            ]
            if not candidates:
                break

            # Evict the least important
            idx, _ = min(candidates, key=lambda x: x[1].importance)
            self._evict_one(idx)
            if not any(
                t.importance < threshold
                for i, t in enumerate(self._turns)
                if t.role != "system" and i < len(self._turns) - preserve
            ):
                break

    def _evict_hybrid(self) -> None:
        """Token budget + importance scoring combined."""
        preserve = self.config.preserve_last_n
        threshold = self.config.importance_threshold

        # First, evict low-importance turns within budget
        while self._token_count_cache > self.config.max_tokens:
            candidates = [
                (i, t)
                for i, t in enumerate(self._turns)
                if t.role != "system"
                and i < len(self._turns) - preserve
                and t.importance < threshold
            ]
            if not candidates:
                # Fall back to evicting oldest non-system turn
                oldest_idx = -1
                for i, t in enumerate(self._turns):
                    if t.role != "system" and i < len(self._turns) - preserve:
                        oldest_idx = i
                        break
                if oldest_idx == -1:
                    break
                self._evict_one(oldest_idx)
            else:
                idx, _ = min(candidates, key=lambda x: x[1].importance)
                self._evict_one(idx)

    def _evict_one(self, index: int) -> None:
        """Remove a single turn at given index."""
        if 0 <= index < len(self._turns):
            turn = self._turns.pop(index)
            self._token_count_cache -= (
                turn.token_count if turn.token_count > 0 else self._estimate_tokens(turn.content)
            )
            self._token_count_cache = max(0, self._token_count_cache)

    def get_messages(self) -> list[dict[str, str]]:
        """Return conversation as list of dicts (OpenAI chat format)."""
        msgs: list[dict[str, str]] = []
        if self.config.system_prompt:
            msgs.append({"role": "system", "content": self.config.system_prompt})
        for turn in self._turns:
            msgs.append({"role": turn.role, "content": turn.content})
        return msgs

    def get_turns(self) -> list[ConversationTurn]:
        return list(self._turns)

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    @property
    def token_count(self) -> int:
        return self._token_count_cache

    def clear(self) -> None:
        """Reset conversation memory."""
        self._turns.clear()
        self._token_count_cache = 0

    def to_summary(self) -> str:
        """Generate a brief summary of the conversation memory."""
        turns = self._turns
        if not turns:
            return "Empty conversation."

        lines = [
            f"Total turns: {len(turns)}",
            f"Total tokens (est.): {self._token_count_cache}",
            f"First turn: [{turns[0].role}] {turns[0].content[:80]}...",
        ]
        if len(turns) > 1:
            lines.append(f"Last turn: [{turns[-1].role}] {turns[-1].content[:80]}...")
        return "\n".join(lines)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimation: ~4 chars per token."""
        return max(1, len(text) // 4)

    def __len__(self) -> int:
        return len(self._turns)

    def __repr__(self) -> str:
        return f"ConversationMemory(turns={len(self._turns)}, tokens={self._token_count_cache}, strategy={self.config.strategy.value})"  # noqa: E501

    # ── Persistence (v1.14.9) ────────────────

    def get_state(self) -> dict[str, Any]:
        """Export conversation memory state for persistence."""
        return {
            "config": {
                "strategy": self.config.strategy.value,
                "max_turns": self.config.max_turns,
                "max_tokens": self.config.max_tokens,
                "importance_threshold": self.config.importance_threshold,
                "system_prompt": self.config.system_prompt,
                "preserve_last_n": self.config.preserve_last_n,
            },
            "turns": [
                {
                    "role": turn.role,
                    "content": turn.content,
                    "timestamp": turn.timestamp,
                    "token_count": turn.token_count,
                    "importance": turn.importance,
                    "metadata": turn.metadata,
                }
                for turn in self._turns
            ],
            "token_count_cache": self._token_count_cache,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore conversation memory from a persisted snapshot."""
        config_data = state.get("config", {})
        self.config = WindowConfig(
            strategy=WindowStrategy(config_data.get("strategy", "sliding")),
            max_turns=config_data.get("max_turns", 20),
            max_tokens=config_data.get("max_tokens", 8000),
            importance_threshold=config_data.get("importance_threshold", 0.3),
            system_prompt=config_data.get("system_prompt"),
            preserve_last_n=config_data.get("preserve_last_n", 2),
        )
        self._turns = []
        for turn_data in state.get("turns", []):
            self._turns.append(
                ConversationTurn(
                    role=turn_data.get("role", "user"),
                    content=turn_data.get("content", ""),
                    timestamp=turn_data.get("timestamp", 0.0),
                    token_count=turn_data.get("token_count", 0),
                    importance=turn_data.get("importance", 0.5),
                    metadata=turn_data.get("metadata", {}),
                )
            )
        self._token_count_cache = state.get("token_count_cache", 0)
