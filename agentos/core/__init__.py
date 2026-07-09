"""Core module - DI system, Handoff protocol, CodeAgent, Agent Loop, State Machine"""

from agentos.core.async_loop import (
    AsyncAgentLoop,
    AsyncContextManager,
    AsyncInvocationResult,
    AsyncLoopConfig,
)
from agentos.core.code_agent import (
    CodeAgent,
    CodeResult,
    CodeStep,
)
from agentos.core.context import (
    AgentContext,
    ContextManager,
)
from agentos.core.context import (
    Message as CoreMessage,
)
from agentos.core.context import (
    ToolCall as CoreToolCall,
)
from agentos.core.context import (
    ToolResult as CoreToolResult,
)
from agentos.core.di import (
    Agent,
    Depends,
    RunContext,
    inject_tool,
    requires_context,
)
from agentos.core.handoff import (
    Handoff,
    HandoffResult,
    can_handle,
    transfer_to,
)
from agentos.core.session import (
    Session,
    SessionStore,
)
from agentos.core.state_machine import (
    AgentState,
    AgentStateMachine,
    StateTimeoutError,
    StateTransition,
    TransitionError,
)
from agentos.core.streaming import (
    ResponseCollector,
    StreamChunk,
    StreamEmitter,
    StreamEvent,
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
