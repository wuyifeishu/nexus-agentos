"""Sub-agent management: spec, mode, lifecycle, parent-child communication, collaboration."""

from .manager import SubAgentManager, SubAgentMode, SubAgentSpec, SubAgentResult
from .parent_child import (
    ChildStatus,
    ChildHeartbeat,
    ChildInfo,
    SharedState,
    ChildContext,
    ChildHandle,
)
from .collaboration import (
    AgentCollaboration,
    CollaborationMode,
    CollaborationResult,
    DebateRound,
    VoteBallot,
    VoteStrategy,
    ReviewPass,
)

__all__ = [
    # Manager
    "SubAgentManager",
    "SubAgentMode",
    "SubAgentSpec",
    "SubAgentResult",
    # Parent-Child
    "ChildStatus",
    "ChildHeartbeat",
    "ChildInfo",
    "SharedState",
    "ChildContext",
    "ChildHandle",
    # Collaboration
    "AgentCollaboration",
    "CollaborationMode",
    "CollaborationResult",
    "DebateRound",
    "VoteBallot",
    "VoteStrategy",
    "ReviewPass",
]
