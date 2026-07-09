"""
Checkpointer 抽象基类与数据结构。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class CheckpointMetadata:
    """Checkpoint 元信息。"""

    thread_id: str  # 对话线程 ID
    checkpoint_id: str  # 唯一 ID
    step: int  # 步骤序号
    parent_checkpoint_id: str | None = None  # 父 checkpoint（用于分支/回溯）
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    tags: list[str] = field(default_factory=list)  # 标签
    summary: str = ""  # 可选摘要


@dataclass
class Checkpoint:
    """单个 Checkpoint — 完整的运行时状态快照。"""

    metadata: CheckpointMetadata  # 元信息
    messages: list[dict[str, Any]]  # 对话消息（序列化后）
    state: dict[str, Any]  # Agent 运行时状态
    tools_result: dict[str, Any]  # 工具调用结果
    next_node: str = ""  # 下一个执行节点

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": {
                "thread_id": self.metadata.thread_id,
                "checkpoint_id": self.metadata.checkpoint_id,
                "parent_checkpoint_id": self.metadata.parent_checkpoint_id,
                "step": self.metadata.step,
                "created_at": self.metadata.created_at,
                "tags": self.metadata.tags,
                "summary": self.metadata.summary,
            },
            "messages": self.messages,
            "state": self.state,
            "tools_result": self.tools_result,
            "next_node": self.next_node,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Checkpoint:
        meta = d["metadata"]
        return cls(
            metadata=CheckpointMetadata(
                thread_id=meta["thread_id"],
                checkpoint_id=meta["checkpoint_id"],
                parent_checkpoint_id=meta.get("parent_checkpoint_id"),
                step=meta["step"],
                created_at=meta["created_at"],
                tags=meta.get("tags", []),
                summary=meta.get("summary", ""),
            ),
            messages=d.get("messages", []),
            state=d.get("state", {}),
            tools_result=d.get("tools_result", {}),
            next_node=d.get("next_node", ""),
        )


class CheckpointBackend(ABC):
    """Checkpoint 存储后端抽象基类。"""

    @abstractmethod
    async def put(self, checkpoint: Checkpoint) -> str:
        """保存 checkpoint，返回 checkpoint_id。"""
        ...

    @abstractmethod
    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        """按 ID 获取 checkpoint。"""
        ...

    @abstractmethod
    async def get_latest(self, thread_id: str) -> Checkpoint | None:
        """获取某线程的最新 checkpoint。"""
        ...

    @abstractmethod
    async def list_threads(self, limit: int = 50, offset: int = 0) -> list[CheckpointMetadata]:
        """列出所有线程的最新 checkpoint 元信息。"""
        ...

    @abstractmethod
    async def list_checkpoints(
        self, thread_id: str, limit: int = 100, offset: int = 0
    ) -> list[CheckpointMetadata]:
        """列出某线程的所有 checkpoint（支持回溯/时间旅行）。"""
        ...

    @abstractmethod
    async def delete_thread(self, thread_id: str) -> int:
        """删除某线程的所有 checkpoint，返回删除数。"""
        ...

    @abstractmethod
    async def delete_before(self, thread_id: str, before_step: int) -> int:
        """删除某线程 before_step 之前的所有 checkpoint。"""
        ...
