"""Swarm module - Swarm coordinator, collaboration patterns, v1.9.8 tool registry + routing"""

from agentos.swarm.coordinator import (
    SmartSwarmCoordinator,
    SwarmCoordinator,  # backward-compat alias
    SwarmTopology,
    SwarmMessage,
    SwarmResult,
    ExecutionMode,
)
from agentos.swarm.patterns import (
    SwarmPatterns,
    Topology,
    CollaborationConfig,
    CollaborationResult,
)
from agentos.swarm.task_decomposer import (
    TaskDecomposer,
    SubTask,
    Decomposition,
)
from agentos.swarm.result_fusion import (
    ResultFusion,
    FusedResult,
)
from agentos.swarm.eval_feedback_loop import (
    EvalFeedbackLoop,
    LoopResult,
    FeedbackSignal,
    RetryConfig,
)
from agentos.swarm.code_sandbox import (
    CodeSandbox,
    SandboxResult,
    TestCase,
    CodeFeedbackExtractor,
)
from agentos.swarm.human_loop import (
    HITLManager,
    HITLConfig,
    Breakpoint,
    BreakpointType,
    HumanDecision,
)
from agentos.swarm.agent_monitor import (
    AgentMonitor,
    QualityGate,
    MonitorReport,
    GateResult,
    GateStatus,
    GateAction,
    output_not_empty,
    output_length_range,
    no_error_output,
    contains_keywords,
    latency_max,
    confidence_min,
)
from agentos.swarm.execution_trace import (
    ExecutionTrace,
    TraceSpan,
    TraceEvent,
    TraceCollector,
)
from agentos.swarm.agent_memory import (
    AgentMemory,
    WorkingMemory,
    ShortTermMemory,
    LongTermMemory,
    ContextWindowManager,
    ContextBudget,
    MemoryEntry,
)
from agentos.swarm.tool_registry import (
    ToolRegistry,
    ToolRouter,
    ToolExecutor,
    ToolSchema,
    ToolParam,
    ToolCategory,
    RoutingDecision,
    RoutingContext,
    ToolExecutionError,
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
