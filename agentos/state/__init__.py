"""AgentOS State — 结构化 Agent 状态管理 (v1.14.0)

Pydantic 驱动的强类型 Agent 运行时状态系统，与 Checkpoint 系统无缝对接。

Usage:
    from agentos.state import AgentState
    state = AgentState()
    state.add_message("user", "Hello")
    state.add_message("assistant", "Hi there!")
    snapshot = state.snapshot()
"""

from agentos.state.schema import (
    AgentState,
    BaseAgentState,
    MultiAgentState,
    ToolCallState,
    ReducerStrategy,
    StateSchemaRegistry,
    state_registry,
)

__all__ = [
    "AgentState",
    "BaseAgentState",
    "MultiAgentState",
    "ToolCallState",
    "ReducerStrategy",
    "StateSchemaRegistry",
    "state_registry",
]
