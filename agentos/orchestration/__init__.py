"""Orchestration module — Graph orchestrator, A2A routing, graph executor, parallel scheduler, swarm coordinator, distributed orchestration, task decomposer"""  # noqa: E501  # noqa: E501

from agentos.orchestration.a2a_router import (
    A2ARouter,
    TaskResult,
    TaskStatus,
)
from agentos.orchestration.a2a_router import (
    AgentCard as RouterAgentCard,
)
from agentos.orchestration.a2a_router import (
    Task as RouterTask,
)
from agentos.orchestration.graph import (
    GraphEdge,
    GraphNode,
    GraphOrchestrator,
)
from agentos.orchestration.graph_executor import (
    AgentGraph,
    GraphNodeState,
    GraphRecipe,
    GraphResult,
)
from agentos.orchestration.parallel import (
    ParallelExecutor,
    RunResult,
)
from agentos.orchestration.task_decomposer import (
    DecompositionStrategy,
    DecompositionTrace,
    TaskDAG,
    TaskDecomposer,
    TaskEdge,
    TaskNode,
    TaskNodeStatus,
    create_decomposer,
)
from agentos.swarm.coordinator import (
    ConflictResolver,
    ConflictType,
    MessageBus,
    SwarmCoordinator,
    SwarmMessage,
    SwarmTask,
    SwarmTopology,
    TaskAllocator,
    TaskPriority,
)
from agentos.swarm.coordinator import (
    SwarmAgentInfo as AgentInfo,
)
from agentos.swarm.coordinator import (
    SwarmAgentRole as AgentRole,
)
from agentos.swarm.coordinator import (
    TaskStatus as SwarmTaskStatus,
)

# Distributed orchestration (optional: requires ray)
try:
    from agentos.orchestration.distributed import (
        AgentPlacementSpec,
        CrossNodeBus,
        CrossNodeMailbox,
        DistSwarmConfig,
        DistSwarmCoordinator,
        DistTaskQueue,
        DistTaskRecord,
        DistTaskStatus,
        PlacementStrategy,
        RayAgentActor,
        quick_start,
    )
    from agentos.orchestration.distributed import (
        AgentStatus as DistAgentStatus,
    )

    _HAS_DISTRIBUTED = True
except ImportError:
    DistSwarmCoordinator = None  # type: ignore
    DistSwarmConfig = None
    DistTaskQueue = None
    DistTaskRecord = None
    DistTaskStatus = None
    CrossNodeBus = None
    CrossNodeMailbox = None
    RayAgentActor = None
    AgentPlacementSpec = None
    DistAgentStatus = None
    PlacementStrategy = None
    quick_start = None
    _HAS_DISTRIBUTED = False

__all__ = [
    "GraphOrchestrator",
    "GraphNode",
    "GraphEdge",
    "A2ARouter",
    "RouterAgentCard",
    "RouterTask",
    "TaskResult",
    "TaskStatus",
    "AgentGraph",
    "GraphRecipe",
    "GraphNodeState",
    "GraphResult",
    "ParallelExecutor",
    "RunResult",
    # Swarm Coordinator v2
    "SwarmCoordinator",
    "AgentInfo",
    "AgentRole",
    "SwarmTask",
    "SwarmTopology",
    "TaskPriority",
    "SwarmTaskStatus",
    "TaskAllocator",
    "ConflictResolver",
    "ConflictType",
    "MessageBus",
    "SwarmMessage",
    # Task Decomposer v2 (v1.14.7)
    "TaskDecomposer",
    "TaskDAG",
    "TaskNode",
    "TaskEdge",
    "TaskNodeStatus",
    "DecompositionStrategy",
    "DecompositionTrace",
    "create_decomposer",
    # Distributed Orchestration (v1.14.2, optional)
    "DistSwarmCoordinator",
    "DistSwarmConfig",
    "DistTaskQueue",
    "DistTaskRecord",
    "DistTaskStatus",
    "CrossNodeBus",
    "CrossNodeMailbox",
    "RayAgentActor",
    "AgentPlacementSpec",
    "DistAgentStatus",
    "PlacementStrategy",
    "quick_start",
]
