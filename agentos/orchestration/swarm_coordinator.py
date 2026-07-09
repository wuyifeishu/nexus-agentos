"""
Deprecation shim — migrated to agentos.swarm.coordinator (v1.16.2).

This file remains for backward compatibility only.
All classes now live in swarm/coordinator.py.
"""

import warnings

warnings.warn(
    "agentos.orchestration.swarm_coordinator is deprecated; "
    "import from agentos.swarm.coordinator instead.",
    DeprecationWarning,
    stacklevel=2,
)

from agentos.swarm.coordinator import (  # noqa: E402
    ConflictResolver,
    ConflictType,
    MessageBus,
    # Core coordinator
    SwarmCoordinator,
    # Message types
    SwarmMessage,
    SwarmTask,
    # Topology
    SwarmTopology,
    # Classes
    TaskAllocator,
    TaskPriority,
    TaskStatus,
)
from agentos.swarm.coordinator import (  # noqa: E402
    # Dataclasses
    SwarmAgentInfo as AgentInfo,
)
from agentos.swarm.coordinator import (  # noqa: E402
    # Enums
    SwarmAgentRole as AgentRole,
)

__all__ = [
    "SwarmCoordinator",
    "SwarmTopology",
    "SwarmMessage",
    "MessageBus",
    "AgentRole",
    "TaskPriority",
    "TaskStatus",
    "AgentInfo",
    "SwarmTask",
    "TaskAllocator",
    "ConflictResolver",
    "ConflictType",
]
