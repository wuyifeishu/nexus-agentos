"""Protocols module - Output validation, Agent Card, A2A, MCP, Contracts"""

from agentos.protocols.output import (
    StructuredOutput,
    validate_output,
    OutputValidator,
)
from agentos.protocols.agent_card import (
    AgentCard,
    AgentCardRegistry,
    AgentCardDiscovery,
    discover_local,
)
from agentos.protocols.a2a import (
    A2ATask,
    A2AMessage,
    A2AArtifact,
    A2AHandoff,
    A2ASession,
    A2AClient,
    A2AServer,
    TextPart,
    FilePart,
    DataPart,
    TaskState,
    new_task,
    new_handoff,
)
from agentos.protocols.mcp import (
    MCPClient,
    MCPServerConfig,
    MCPToolSchema,
)
from agentos.protocols.contracts import (
    AgentContract,
    AgentCapability,
    CapabilityDomain,
    QoSLevel,
    CapabilityMatcher,
    ContractRegistry,
    MatchScore,
)
from agentos.protocols.a2a_store import (
    A2ATaskStore,
    InMemoryTaskStore,
    SqliteTaskStore,
)
from agentos.protocols.a2a_streaming import (
    A2AStreamEvent,
    TaskProgress,
    A2AStreamSession,
    A2AStreamManager,
)
from agentos.protocols.registry import (
    DiscoveryCapability,
    DiscoveryCard,
    AgentStatus,
    RegistryEntry,
    AgentRegistry,
    A2ARegistryBridge,
    default_registry,
)

__all__ = [
    "StructuredOutput",
    "validate_output",
    "OutputValidator",
    "AgentCard",
    "AgentCardRegistry",
    "AgentCardDiscovery",
    "discover_local",
    "A2ATask",
    "A2AMessage",
    "A2AArtifact",
    "A2AHandoff",
    "A2ASession",
    "A2AClient",
    "A2AServer",
    "TextPart",
    "FilePart",
    "DataPart",
    "TaskState",
    "new_task",
    "new_handoff",
    "MCPClient",
    "MCPServerConfig",
    "MCPToolSchema",
    "AgentContract",
    "AgentCapability",
    "CapabilityDomain",
    "QoSLevel",
    "CapabilityMatcher",
    "ContractRegistry",
    "MatchScore",
    "A2ATaskStore",
    "InMemoryTaskStore",
    "SqliteTaskStore",
    "A2AStreamEvent",
    "TaskProgress",
    "A2AStreamSession",
    "A2AStreamManager",
    # Agent Registry (v1.14.0)
    "DiscoveryCapability",
    "DiscoveryCard",
    "AgentStatus",
    "RegistryEntry",
    "AgentRegistry",
    "A2ARegistryBridge",
    "default_registry",
]
