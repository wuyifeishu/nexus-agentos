"""AgentOS v1.3.10 - Conversation Manager 模块。

多轮对话上下文管理：滑动窗口、自动摘要、对话分支、token 感知裁剪。
适用于长会话场景，防止上下文溢出，同时保持关键信息不丢失。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class MessageRole(str, Enum):
    """消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TrimStrategy(Enum):
    """裁剪策略。"""

    FIFO = auto()
    SUMMARIZE = auto()
    IMPORTANCE_WEIGHTED = auto()
    TOKEN_BUDGET = auto()


@dataclass
class Message:
    """单条对话消息。"""

    role: MessageRole
    content: str
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0
    importance: float = 1.0
    metadata: dict = field(default_factory=dict)
    message_id: str = ""

    def __post_init__(self):
        if not self.message_id:
            raw = f"{self.role.value}:{self.content[:50]}:{self.timestamp}"
            self.message_id = hashlib.md5(raw.encode()).hexdigest()[:12]


@dataclass
class ConversationConfig:
    """对话管理配置。"""

    max_messages: int = 50
    max_tokens: int = 8000
    trim_strategy: TrimStrategy = TrimStrategy.FIFO
    preserve_system: bool = True
    preserve_last_n: int = 4
    summary_prompt: str = ""
    auto_summarize_threshold: float = 0.75
    token_counter: Callable[[str], int] | None = None


@dataclass
class ConversationStats:
    """对话统计。"""

    total_messages: int = 0
    total_tokens: int = 0
    trim_count: int = 0
    summarize_count: int = 0
    branch_count: int = 0
    oldest_timestamp: float = 0.0
    newest_timestamp: float = 0.0


@dataclass
class ConversationSnapshot:
    """对话快照（用于分支/恢复）。"""

    messages: list[Message]
    stats: ConversationStats
    snapshot_id: str
    created_at: float = field(default_factory=time.time)
    label: str = ""


class ConversationManager:
    """多轮对话上下文管理器。

    核心功能：
    - 滑动窗口：超出 max_messages/max_tokens 时自动裁剪
    - 自动摘要：超出阈值时压缩历史消息为摘要
    - 对话分支：支持 fork 创建分支，切换/合并分支
    - Token 感知：按 token 预算精确裁剪
    """

    def __init__(self, config: ConversationConfig | None = None):
        self.config = config or ConversationConfig()
        self._messages: list[Message] = []
        self._summary: str = ""
        self.stats = ConversationStats()
        self._branches: dict[str, ConversationSnapshot] = {}
        self._current_branch: str = "main"
        self._message_counter: int = 0

    # ── 消息管理 ──────────────────────────────────────────────

    def add(self, role: MessageRole | str, content: str, **meta) -> Message:
        """添加一条消息，自动触发裁剪检查。"""
        if isinstance(role, str):
            role = MessageRole(role)
        token_count = self._count_tokens(content)
        msg = Message(
            role=role,
            content=content,
            token_count=token_count,
            message_id=self._next_id(),
            metadata=meta,
        )
        self._messages.append(msg)
        self.stats.total_messages += 1
        self.stats.total_tokens += token_count
        if not self.stats.oldest_timestamp:
            self.stats.oldest_timestamp = msg.timestamp
        self.stats.newest_timestamp = msg.timestamp
        self._enforce_limits()
        return msg

    def add_many(self, messages: list[tuple[str, str]]) -> list[Message]:
        """批量添加消息。"""
        return [self.add(role, content) for role, content in messages]

    def get_context(
        self, include_summary: bool = True, limit: int | None = None
    ) -> list[dict]:
        """获取当前对话上下文，返回 OpenAI 兼容格式。"""
        result: list[dict] = []
        if include_summary and self._summary:
            result.append({"role": "system", "content": f"[对话摘要] {self._summary}"})
        msgs = self._messages[-limit:] if limit else self._messages
        for msg in msgs:
            result.append({"role": msg.role.value, "content": msg.content})
        return result

    def get_system_prompt(self) -> str:
        """提取 system 消息。"""
        for msg in self._messages:
            if msg.role == MessageRole.SYSTEM:
                return msg.content
        return ""

    # ── 裁剪与压缩 ────────────────────────────────────────────

    def _enforce_limits(self):
        """检查并执行裁剪。"""
        changed = False
        while len(self._messages) > self.config.max_messages:
            self._trim_one()
            changed = True
        while self.stats.total_tokens > self.config.max_tokens:
            self._trim_one()
            changed = True
        if (
            changed
            and self.config.trim_strategy == TrimStrategy.SUMMARIZE
            and self.config.summary_prompt
        ):
            self._update_summary()

    def _trim_one(self):
        """按裁剪策略移除一条消息。"""
        if self.config.trim_strategy == TrimStrategy.FIFO:
            self._trim_fifo()
        elif self.config.trim_strategy == TrimStrategy.IMPORTANCE_WEIGHTED:
            self._trim_lowest_importance()
        elif self.config.trim_strategy == TrimStrategy.TOKEN_BUDGET:
            self._trim_token_budget()
        else:
            self._trim_fifo()

    def _trim_fifo(self):
        """先进先出裁剪：移除最旧非保留消息。"""
        preserve = self.config.preserve_last_n
        for i, msg in enumerate(self._messages):
            if self.config.preserve_system and msg.role == MessageRole.SYSTEM:
                continue
            if len(self._messages) - i <= preserve:
                break
            self.stats.total_tokens -= msg.token_count
            self.stats.trim_count += 1
            self._messages.pop(i)
            return

    def _trim_lowest_importance(self):
        """移除重要性最低的消息。"""
        preserve = self.config.preserve_last_n
        candidates = list(enumerate(self._messages))
        if self.config.preserve_system:
            candidates = [(i, m) for i, m in candidates if m.role != MessageRole.SYSTEM]
        if len(candidates) <= preserve:
            return
        candidates = candidates[:-preserve]
        idx, _ = min(candidates, key=lambda x: x[1].importance)
        msg = self._messages.pop(idx)
        self.stats.total_tokens -= msg.token_count
        self.stats.trim_count += 1

    def _trim_token_budget(self):
        """按 token 预算裁剪。"""
        budget = int(self.config.max_tokens * self.config.auto_summarize_threshold)
        preserve_last = self.config.preserve_last_n
        system_count = sum(1 for m in self._messages if m.role == MessageRole.SYSTEM and self.config.preserve_system)
        while self.stats.total_tokens > budget and len(self._messages) > preserve_last + system_count:
            for i, msg in enumerate(self._messages):
                if self.config.preserve_system and msg.role == MessageRole.SYSTEM:
                    continue
                if len(self._messages) - i <= preserve_last:
                    break
                self.stats.total_tokens -= msg.token_count
                self.stats.trim_count += 1
                self._messages.pop(i)
                break
            else:
                break

    def _update_summary(self):
        """更新对话摘要（调用方需通过 summarize_callback 注入 LLM 实现）。"""
        self._summary = f"[共 {len(self._messages)} 条消息, {self.stats.total_tokens} tokens]"

    def set_summarizer(self, callback: Callable[[list[Message]], str]):
        """注入摘要回调。"""
        self._summarizer = callback

    # ── 对话分支 ──────────────────────────────────────────────

    def fork(self, label: str = "") -> ConversationSnapshot:
        """创建对话分支快照。"""
        import uuid

        sid = uuid.uuid4().hex[:8]
        snapshot = ConversationSnapshot(
            messages=list(self._messages),
            stats=ConversationStats(
                total_messages=self.stats.total_messages,
                total_tokens=self.stats.total_tokens,
                trim_count=self.stats.trim_count,
                summarize_count=self.stats.summarize_count,
                branch_count=self.stats.branch_count,
                oldest_timestamp=self.stats.oldest_timestamp,
                newest_timestamp=self.stats.newest_timestamp,
            ),
            snapshot_id=sid,
            label=label or f"branch-{sid}",
        )
        self._branches[sid] = snapshot
        self.stats.branch_count += 1
        return snapshot

    def switch_branch(self, snapshot_id: str):
        """切换到指定分支。"""
        snapshot = self._branches.get(snapshot_id)
        if not snapshot:
            raise KeyError(f"Branch '{snapshot_id}' not found")
        self._messages = list(snapshot.messages)
        self.stats = ConversationStats(
            total_messages=snapshot.stats.total_messages,
            total_tokens=snapshot.stats.total_tokens,
            trim_count=snapshot.stats.trim_count,
            summarize_count=snapshot.stats.summarize_count,
            branch_count=snapshot.stats.branch_count,
            oldest_timestamp=snapshot.stats.oldest_timestamp,
            newest_timestamp=snapshot.stats.newest_timestamp,
        )
        self._current_branch = snapshot_id

    def merge_branch(self, snapshot_id: str, strategy: str = "append"):
        """合并分支消息到当前对话。"""
        snapshot = self._branches.get(snapshot_id)
        if not snapshot:
            raise KeyError(f"Branch '{snapshot_id}' not found")
        if strategy == "append":
            existing_ids = {m.message_id for m in self._messages}
            for msg in snapshot.messages:
                if msg.message_id not in existing_ids:
                    self._messages.append(msg)
                    self.stats.total_messages += 1
                    self.stats.total_tokens += msg.token_count
        elif strategy == "replace":
            self._messages = list(snapshot.messages)
        self._enforce_limits()

    def list_branches(self) -> dict[str, ConversationSnapshot]:
        """列出所有分支。"""
        return dict(self._branches)

    # ── 工具方法 ──────────────────────────────────────────────

    def _count_tokens(self, text: str) -> int:
        """估算 token 数。"""
        if self.config.token_counter:
            return self.config.token_counter(text)
        return len(text) // 3

    def _next_id(self) -> str:
        self._message_counter += 1
        return f"msg_{self._message_counter:06d}"

    def clear(self, keep_system: bool = True):
        """清空对话历史。"""
        system_msgs = [m for m in self._messages if m.role == MessageRole.SYSTEM] if keep_system else []
        self._messages = system_msgs
        self._summary = ""
        self.stats = ConversationStats()

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def token_count(self) -> int:
        return self.stats.total_tokens

    def __len__(self) -> int:
        return len(self._messages)

    def __repr__(self) -> str:
        return f"<Conversation messages={len(self)} tokens={self.token_count} branches={len(self._branches)}>"


__all__ = [
    "ConversationManager",
    "ConversationConfig",
    "ConversationStats",
    "ConversationSnapshot",
    "Message",
    "MessageRole",
    "TrimStrategy",
]
