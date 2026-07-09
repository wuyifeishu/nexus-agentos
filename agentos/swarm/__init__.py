"""Swarm module - Swarm coordinator, collaboration patterns, v1.9.8 tool registry + routing"""

from agentos.swarm.agent_memory import (
    AgentMemory,
    ContextBudget,
    ContextWindowManager,
    LongTermMemory,
    MemoryEntry,
    ShortTermMemory,
    WorkingMemory,
)
from agentos.swarm.agent_monitor import (
    AgentMonitor,
    GateAction,
    GateResult,
    GateStatus,
    MonitorReport,
    QualityGate,
    confidence_min,
    contains_keywords,
    latency_max,
    no_error_output,
    output_length_range,
    output_not_empty,
)
from agentos.swarm.code_sandbox import (
    CodeFeedbackExtractor,
    CodeSandbox,
    SandboxResult,
    TestCase,
)
from agentos.swarm.coordinator import (
    ConflictResolver,
    ConflictType,
    ExecutionMode,
    SmartSwarmCoordinator,
    SwarmAgentInfo,
    # Migrated from orchestration/swarm_coordinator.py (v1.16.2)
    SwarmAgentRole,
    SwarmCoordinator,  # backward-compat alias
    SwarmMessage,
    SwarmResult,
    SwarmTask,
    SwarmTopology,
    TaskAllocator,
    TaskPriority,
    TaskStatus,
)
from agentos.swarm.eval_feedback_loop import (
    EvalFeedbackLoop,
    FeedbackSignal,
    LoopResult,
    RetryConfig,
)
from agentos.swarm.execution_trace import (
    ExecutionTrace,
    TraceCollector,
    TraceEvent,
    TraceSpan,
)
from agentos.swarm.human_loop import (
    Breakpoint,
    BreakpointType,
    HITLConfig,
    HITLManager,
    HumanDecision,
)
from agentos.swarm.patterns import (
    CollaborationConfig,
    CollaborationResult,
    SwarmPatterns,
    Topology,
)
from agentos.swarm.result_fusion import (
    FusedResult,
    ResultFusion,
)
from agentos.swarm.task_decomposer import (
    Decomposition,
    SubTask,
    TaskDecomposer,
)
from agentos.swarm.tool_registry import (
    RoutingContext,
    RoutingDecision,
    ToolCategory,
    ToolExecutionError,
    ToolExecutor,
    ToolParam,
    ToolRegistry,
    ToolRouter,
    ToolSchema,
    create_tool,
)

__all__ = [
    # Coordinator
    "SmartSwarmCoordinator",
    "SwarmCoordinator",
    "SwarmTopology",
    "SwarmMessage",
    "SwarmResult",
    "ExecutionMode",
    # Migrated from orchestration (v1.16.2)
    "SwarmAgentRole",
    "TaskPriority",
    "TaskStatus",
    "SwarmAgentInfo",
    "SwarmTask",
    "TaskAllocator",
    "ConflictResolver",
    "ConflictType",
    # Patterns
    "SwarmPatterns",
    "Topology",
    "CollaborationConfig",
    "CollaborationResult",
    # Task Decomposer
    "TaskDecomposer",
    "SubTask",
    "Decomposition",
    # Result Fusion
    "ResultFusion",
    "FusedResult",
    # Eval Feedback Loop
    "EvalFeedbackLoop",
    "LoopResult",
    "FeedbackSignal",
    "RetryConfig",
    # Code Sandbox (v1.9.5)
    "CodeSandbox",
    "SandboxResult",
    "TestCase",
    "CodeFeedbackExtractor",
    # Human-in-the-Loop (v1.9.5)
    "HITLManager",
    "HITLConfig",
    "Breakpoint",
    "BreakpointType",
    "HumanDecision",
    # Agent Monitor (v1.9.6)
    "AgentMonitor",
    "QualityGate",
    "MonitorReport",
    "GateResult",
    "GateStatus",
    "GateAction",
    "output_not_empty",
    "output_length_range",
    "no_error_output",
    "contains_keywords",
    "latency_max",
    "confidence_min",
    # Execution Trace (v1.9.6)
    "ExecutionTrace",
    "TraceSpan",
    "TraceEvent",
    "TraceCollector",
    # Agent Memory (v1.9.7)
    "AgentMemory",
    "WorkingMemory",
    "ShortTermMemory",
    "LongTermMemory",
    "ContextWindowManager",
    "ContextBudget",
    "MemoryEntry",
    # Tool Registry & Router (v1.9.8)
    "ToolRegistry",
    "ToolRouter",
    "ToolExecutor",
    "ToolSchema",
    "ToolParam",
    "ToolCategory",
    "RoutingDecision",
    "RoutingContext",
    "ToolExecutionError",
    "create_tool",
]
