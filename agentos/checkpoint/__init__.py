"""
AgentOS Checkpointer — 对话与工作流持久化引擎。

参考 LangGraph PostgresSaver 设计，实现:
  - 故障恢复：Agent 崩溃后从最近 checkpoint 恢复
  - 时间旅行：回退到任意历史状态，重放/分支
  - 多后端：Postgres / SQLite / File
  - 自动快照：每次 tool_call / llm_call 后自动保存

用法:
    from agentos.checkpoint import create_checkpointer

    cp = create_checkpointer("sqlite", db_path="checkpoints.db")
    await cp.put(checkpoint)   # 保存状态
    state = await cp.get(id)   # 恢复状态
"""

from agentos.checkpoint.base import (
    Checkpoint,
    CheckpointBackend,
    CheckpointMetadata,
)
from agentos.checkpoint.factory import create_checkpointer
from agentos.checkpoint.postgres import PostgresCheckpointer
from agentos.checkpoint.sqlite import SQLiteCheckpointer

__all__ = [
    "Checkpoint",
    "CheckpointMetadata",
    "CheckpointBackend",
    "SQLiteCheckpointer",
    "PostgresCheckpointer",
    "create_checkpointer",
]
