"""Sub-agent management: spec, mode, lifecycle, parent-child communication, collaboration."""

from .collaboration import (
    AgentCollaboration,
    CollaborationMode,
    CollaborationResult,
    DebateRound,
    ReviewPass,
    VoteBallot,
    VoteStrategy,
)
from .manager import SubAgentManager, SubAgentMode, SubAgentResult, SubAgentSpec
from .parent_child import (
    ChildContext,
    ChildHandle,
    ChildHeartbeat,
    ChildInfo,
    ChildStatus,
    SharedState,
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
