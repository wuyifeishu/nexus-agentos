"""Core module - DI system, Handoff protocol, CodeAgent, Agent Loop, State Machine"""

from agentos.core.di import (
    Agent,
    RunContext,
    Depends,
    inject_tool,
    requires_context,
)
from agentos.core.handoff import (
    Handoff,
    HandoffResult,
    transfer_to,
    can_handle,
)
from agentos.core.code_agent import (
    CodeAgent,
    CodeResult,
    CodeStep,
)
from agentos.core.context import (
    AgentContext,
    ContextManager,
    Message as CoreMessage,
    ToolCall as CoreToolCall,
    ToolResult as CoreToolResult,
)
from agentos.core.state_machine import (
    AgentStateMachine,
    AgentState,
    StateTransition,
    TransitionError,
    StateTimeoutError,
)
from agentos.core.streaming import (
    StreamChunk,
    StreamEmitter,
    StreamEvent,
    ResponseCollector,
)
from agentos.core.session import (
    Session,
    SessionStore,
)
from agentos.core.async_loop import (
    AsyncAgentLoop,
    AsyncLoopConfig,
    AsyncInvocationResult,
    AsyncContextManager,
)

__all__ = [
    "Agent",
    "RunContext",
    "Depends",
    "inject_tool",
    "requires_context",
    "Handoff",
    "HandoffResult",
    "transfer_to",
    "can_handle",
    "CodeAgent",
    "CodeResult",
    "CodeStep",
    "AgentContext",
    "ContextManager",
    "CoreMessage",
    "CoreToolCall",
    "CoreToolResult",
    "AgentStateMachine",
    "AgentState",
    "StateTransition",
    "TransitionError",
    "StateTimeoutError",
    "StreamChunk",
    "StreamEmitter",
    "StreamEvent",
    "ResponseCollector",
    "Session",
    "SessionStore",
    "AsyncAgentLoop",
    "AsyncLoopConfig",
    "AsyncInvocationResult",
    "AsyncContextManager",
]
