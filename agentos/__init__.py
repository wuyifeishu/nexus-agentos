"""NexusAgent - Production-grade Agent Framework SDK

v1.12.1: Async Parallel Primitives (fan-out/fan-in, parallel_gather, parallel_map, structured concurrency).
v1.12.0: Virtual Memory Pager (page-out/page-in + swap store + smart recall).
v1.11.0: Background Task Manager + Agent Supervision Tree + Checkpoint + Auto-Context Paging.
v1.10.0: Deploy (Docker/K8s) + Eval (SWE-bench/GAIA) + Multimodal + Prompt Hub + Cost Tracker.
v1.9.9: GuardPipeline (PII/Injection/Toxicity safety with strict/permissive modes).
v1.9.5: CodeSandbox (safe code gen + test case validation) + Human-in-the-Loop breakpoints.
v1.9.4: TaskDecomposer + ResultFusion + EvalFeedbackLoop (P0 three-bottleneck fix).
v1.9.3: CompositeScorer V2 (BLEU smoothing + LLM-as-Judge), 50+ benchmark cases, 80% pass rate.
v1.9.2: Swarm MESH 5x parallel, CompositeScorer, 14 built-in benchmarks, AutoPilot.
v1.7.1: Desktop client: visual approval engine, native desktop shell, tiered ops.
v1.0.0: Production release — ToolUsingAgent CLI, Mock fallback mode,
weather demo (`agentos demo`), unified LLM Provider abstraction,
streaming/retry/checkpoint/resume, PyPI + TestPyPI dual publish.

v1.3.38: +Tool-Using Agent streaming/retry/checkpoint/resume（run_stream/重试逻辑/断点恢复），
+MockLLMProvider 集成测试支持。11+10 条 Agent 测试全过。
v1.3.37: +Tool-Using Agent (agentos.agent) — 基于 LLM Function Calling 的自主 Agent 循环：
ToolExecutor 工具注册/执行、多步推理闭环、同步/异步运行、成本追踪、端到端天气 Agent 示例。
v1.3.36: +LLM Provider Module (agentos.llm) — unified abstraction with OpenAI/DeepSeek/Anthropic
providers, Function Calling / Tool Use, streaming, cost estimation. 零 SDK 依赖 AnthropicProvider
(pure httpx).
v1.3.15: +SubAgent Parent-Child Communication (SharedState, ChildContext/ChildHandle, heartbeat,
lifecycle management: pause/resume/cancel/timeout, heartbeat monitoring).
v1.3.14: +OpenTelemetry Integration (otel_bridge: OtelConfig/OtelTracer/OtelMeter/OtelMiddleware).
v1.3.13: +A2A Protocol v2 (Task Store with InMemory/SQLite backends, Streaming SSE task lifecycle
notifications, enhanced A2AClient with retry/auth/connection pooling, A2AServer with FastAPI
route builder + streaming + auth + pluggable persistence).
v1.3.12: +Prompt Optimizer (DSPy-inspired iterative refinement, bootstrapping, multi-strategy),
+Few-Shot Selector (similarity/diversity/label-balanced strategies),
+SSE Streaming (ASGI SSE with heartbeats, backpressure, typed events).
v1.3.11: +Guardrails (Input/Output safety engine with PII/Injection/Keyword/Toxicity rules, PolicyEnforcer),
+HITL (Human-in-the-Loop approval workflows with RiskLevel auto-decision, caching, preset policies).
v1.3.10: +Conversation Manager (multi-turn dialog, sliding window, branching, summarization).
v1.3.9: +Schema Enforcer (Pydantic output validation/auto-repair).
v1.3.8: +Quality (docstrings, bare-except/type-ignore fixes).

v1.4.0: +End-to-end examples (multi_agent_research.py, file_ops_agent.py),
+Professional README with feature comparison table,
+CLI demo upgraded with self-check mode, +Agent marketplace listing.
"""

__version__ = "1.50.7"

# v1.15.0: Tool Output Validation Layer (structured result validation + error classification + auto-repair suggestions).
# v1.14.9: Memory Persistence Checkpoint Delivery - all 6 memory subsystems get_state()/restore_state() + ServerDaemon lifecycle integration + DaemonConfig + /api/daemon/memory endpoint.  # noqa: E501
# v1.14.8: P0 regression fix (imports, version, dependencies).

# Core - DI system
# Tool-Using Agent (v1.3.38)
from agentos.agent import (
    AgentConfig,
    AgentResult,
    AgentStep,
    MockLLMProvider,
    ToolAgent,
    ToolExecutor,
)

# Agent Marketplace (v1.3.0)
from agentos.agents.market import (
    AgentCategory,
    AgentMarket,
    AgentSkill,
)

# API Middleware (v1.3.0)
from agentos.api.middleware import (
    AuthConfig,
    CORSConfig,
    CORSMiddleware,
    RequestContext,
    RequestIDMiddleware,
)

# API Server (v1.3.2)
from agentos.api.server import (
    AgentAPI,
    RunRequest,
    RunResponse,
)

# API Streaming (v1.3.0)
from agentos.api.streaming import (
    StreamEvent,
    StreamingAgent,
    StreamSession,
)

# API Versioning (v1.3.0)
from agentos.api.versioning import (
    APIVersion,
    VersionConfig,
    VersionNegotiator,
    VersionStrategy,
)

# Benchmark Runner (v1.3.0)
from agentos.benchmarks.runner import (
    BenchmarkConfig,
    BenchmarkReport,
    BenchmarkRunner,
    BenchmarkScenario,
)

# Cache - LLM Response Cache (v1.2.7)
from agentos.cache import (
    BaseEmbedder,
    CacheEntry,
    CacheKeyStrategy,
    CohereEmbedder,
    LLMCache,
    LocalEmbedder,
    OpenAIEmbedder,
    ResponseCache,
)

# CLI Init (v1.4.1)
from agentos.cli.init import (
    scaffold,
)

# CLI Main (v1.0.0)
from agentos.cli.main import main as cli_main

# CLI Serve (v1.3.0)
from agentos.cli.serve import (
    ServeConfig,
    start_api_server,
)

# Communication layer
from agentos.comm.layer import (
    Blackboard,
    CommunicationLayer,
    EventBus,
    Mailbox,
)

# Concurrency (v1.1.3)
from agentos.concurrency.batch import (
    AsyncBatchExecutor,
    BatchConfig,
    BatchResult,
    BatchStrategy,
    TaskSpec,
)
from agentos.concurrency.batch import (
    TaskResult as BatchTaskResult,
)
from agentos.concurrency.batch import (
    TaskStatus as BatchTaskStatus,
)

# Config System (v1.2.7)
from agentos.config import (
    AgentOSConfig,
    AgentOSPreset,
    ValidationResult,
)

# Core extensions (v1.2.9)
from agentos.core import (
    AgentContext,
    AgentState,
    AgentStateMachine,
    AsyncAgentLoop,
    AsyncContextManager,
    AsyncInvocationResult,
    AsyncLoopConfig,
    ContextManager,
    CoreMessage,
    CoreToolCall,
    CoreToolResult,
    ResponseCollector,
    Session,
    SessionStore,
    StateTimeoutError,
    StateTransition,
    StreamChunk,
    StreamEmitter,
    TransitionError,
)

# Core - CodeAgent
from agentos.core.code_agent import (
    CodeAgent,
    CodeResult,
    CodeStep,
)

# Cost Tracking (v1.20.0)
from agentos.core.cost_tracker import (
    CostTracker,
    ModelPricing,
    UsageRecord,
)
from agentos.core.di import (
    Agent,
    Depends,
    RunContext,
    inject_tool,
    requires_context,
)

# Feature Flags (v1.20.0)
# Core - Handoff protocol
from agentos.core.handoff import (
    Handoff,
    HandoffAwareAgent,
    HandoffResult,
    can_handle,
    execute_with_handoff,
    transfer_to,
)

# Agent Loop (v1.3.2)
from agentos.core.loop import (
    AgentLoop,
    HumanInterruptNeeded,
    LoopConfig,
    LoopState,
    MaxIterationsExceeded,
)

# Core - Middleware Pipeline (v1.2.7)
from agentos.core.middleware import (
    AgentMiddleware,
    MiddlewareContext,
    MiddlewareDecision,
    MiddlewarePhase,
    MiddlewarePipeline,
)

# Cost - Token Counter (v1.2.9)
from agentos.cost import (
    CostEstimate,
    ModelFamily,
    TokenCount,
    TokenCounter,
)

# Cost tracking (v1.1.4)
from agentos.cost.tracker import (
    PRICING,
    RunCostSession,
)

# Deployment (v1.2.8)
from agentos.deployment import (
    ComposeConfig,
    ComposeService,
    DockerConfig,
)

# Docs Generator (v1.3.2)
from agentos.docs.generator import (
    DocConfig,
    generate_api_docs,
    generate_quickstart,
)

# Errors (v1.2.8)
from agentos.errors import (
    ErrorCategory,
    ErrorContext,
    ErrorFormatter,
    HumanError,
)

# Evaluation Framework (v1.3.18)
from agentos.evaluation import (
    EvalReport,
    Evaluator,
    Scorer,
)
from agentos.evaluation.scorers import (
    CompositeScorer,
)

# Evolution engine
from agentos.evolution.engine import (
    EvolutionEngine,
    EvolutionProposal,
    EvolutionStatus,
)
from agentos.experiments import (
    Evaluator as ExperimentEvaluator,
)

# Experiments (v1.2.8)
from agentos.experiments import (
    ExperimentConfig,
    ExperimentReport,
    ExperimentRunner,
    PromptVariant,
    TrialResult,
)

# Feedback (v1.2.8)
from agentos.feedback import (
    FeedbackCollector,
    FeedbackRecord,
    FeedbackType,
    PreferenceLearner,
)

# Health (v1.2.9)
from agentos.health import (
    CheckResult,
    HealthCheck,
    HealthChecker,
    HealthStatus,
)

# Logging (v1.2.9)
from agentos.log import (
    JSONFormatter,
    TraceContext,
)

# MCP Package (v1.3.6)
from agentos.mcp import (
    MCPClient as MCPFullClient,
)
from agentos.mcp import (
    MCPError,
    MCPPromptDef,
    MCPPromptInfo,
    MCPResource,
    MCPResourceInfo,
    # MCP Server (v1.5.2)
    MCPServer,
    MCPToolDef,
    MCPToolInfo,
    connect_mcp_servers,
    create_default_server,
    start_mcp_server,
)
from agentos.mcp import (
    MCPServerConfig as MCPConfig,
)
from agentos.mcp.adapter import (
    MCPToolAdapter,
    MCPToolRegistry,
)

# Built-in MCP Servers (v1.7.8)
from agentos.mcp.builtin_servers import (
    BuiltinMCPRegistry,
    FilesystemServer,
    MemoryServer,
    WebFetchServer,
    create_default_registry,
)

# Memory - Retriever + Conversation (v1.2.7)
# Memory extensions (v1.2.8)
# Memory - Compressor (v1.2.9)
from agentos.memory import (
    ContextCompressor,
    ConversationMemory,
    ImportanceScorer,
    LongTermMemory,
    MemoryChunk,
    MemoryStore,
    MemorySummarizer,
    SemanticMemoryRetriever,
    VectorMemory,
    WorkingMemory,
    WorkingMemoryItem,
)

# Memory pyramid
from agentos.memory.pyramid import (
    MemoryItem,
    MemoryLayer,
    MemoryPyramid,
    MemoryType,
)

# Anthropic Claude Backend (v1.3.5)
from agentos.models.backends.anthropic import (
    ClaudeClient,
    ClaudeConfig,
)

# Gemini Backend (v1.3.1)
from agentos.models.backends.gemini import (
    GeminiClient,
    GeminiConfig,
    GeminiSafetySetting,
)

# Ollama Backend (v1.3.5)
from agentos.models.backends.ollama import (
    OllamaClient,
    OllamaConfig,
)

# OpenAI Backend (v1.3.5)
from agentos.models.backends.openai import (
    OpenAIClient,
    OpenAIConfig,
)

# Models - Resilience (v1.1.5)
from agentos.models.resilience import (
    CancellationSource,
    CancelledError,
    CircuitBreaker,
    CircuitBreakerConfig,
    ResilienceConfig,
    ResilientCall,
    RetryConfig,
    retry_with_backoff,
    with_fallback,
    with_timeout,
)

# Models - Router (v1.2.7 minimal)
# Model Route Types (v1.3.1)
# Model Config (v1.3.2)
from agentos.models.router import (
    RECOMMENDED_CONFIG,
    AllModelsFailed,
    ModelConfig,
    ModelResponse,
    ModelRouter,
    ModelSpec,
)

# Models - Routing Strategy (v1.2.8)
from agentos.models.routing_strategy import (
    Budget,
    Complexity,
    RoutingStrategy,
)

# Monitoring (v1.2.8)
from agentos.monitoring import (
    Alert,
    AlertEvaluator,
    AlertRule,
    AlertSeverity,
    AlertState,
    MonitoringConfig,
    WebhookConfig,
    WebhookDispatcher,
)

# Multimodal (v1.2.7)
from agentos.multimodal import (
    Modality,
    MultimodalManager,
)

# Observability (v1.2.7)
from agentos.observability import (
    BudgetAlert,
    CostAnalytics,
    MetricsCollector,
    NoopTracer,
    Tracer,
)

# Orchestration extensions (v1.2.8)
from agentos.orchestration import (
    A2ARouter,
    AgentGraph,
    GraphNodeState,
    GraphRecipe,
    GraphResult,
    RouterAgentCard,
    RouterTask,
    TaskResult,
    TaskStatus,
)

# Orchestration
from agentos.orchestration.graph import (
    GraphEdge,
    GraphNode,
    GraphOrchestrator,
)

# Plugin Manager (v1.2.9)
from agentos.plugin_manager import (
    PluginInfo,
    PluginManager,
)

# Plugins - Plugin System (v1.2.7)
from agentos.plugins import (
    DiscoveredPlugin,
    LifecycleManager,
    PluginDiscovery,
    PluginLoader,
    PluginRegistry,
    PluginStatus,
    RegisteredPlugin,
)

# Prompts (v1.2.7)
from agentos.prompts import (
    PromptRegistry,
    PromptTemplate,
)

# Protocols - Contracts (v1.2.9)
from agentos.protocols import (
    AgentCapability,
    AgentContract,
    CapabilityDomain,
    CapabilityMatcher,
    ContractRegistry,
    MatchScore,
    QoSLevel,
)

# Protocols - A2A
from agentos.protocols.a2a import (
    A2AArtifact,
    A2AClient,
    A2AHandoff,
    A2AMessage,
    A2AServer,
    A2ASession,
    A2ATask,
    DataPart,
    FilePart,
    TaskState,
    TextPart,
    new_handoff,
    new_task,
)

# Protocols - Agent Card
from agentos.protocols.agent_card import (
    AgentCard,
    AgentCardDiscovery,
    AgentCardRegistry,
    create_card,
    discover_local,
)

# MCP Protocol (v1.2.7)
from agentos.protocols.mcp import (
    MCPClient,
    MCPServerConfig,
    MCPToolSchema,
)

# Protocols - Structured output validation
from agentos.protocols.output import (
    OutputValidator,
    StructuredOutput,
    validate_output,
)

# Queue - Task Queue & Rate Limiter (v1.2.7)
from agentos.queue import (
    RateLimitConfig,
    RateLimiter,
    RateLimitStrategy,
    TaskPriority,
    TaskQueue,
)
from agentos.queue import (
    TaskState as QueueTaskState,
)

# RAG Pipeline (v1.3.5)
from agentos.rag import (
    ChunkConfig,
    EmbeddingConfig,
    RAGPipeline,
    TextChunker,
)

# Security extensions (v1.9.9)
from agentos.security import (
    ContentSafetyFilter,
    GuardAction,
    GuardChainResult,
    GuardPipeline,
    GuardResult,
    InputGuard,
    LLMSafetyAnalyzer,
    OutputGuard,
    PIIDetector,
    RiskLevel,
    SafetyReport,
    Sandbox,
    SandboxManager,
    Severity,
    create_permissive_guard,
    create_strict_guard,
)

# Security - Auditor (v1.2.7)
from agentos.security.auditor import (
    AuditFinding,
    AuditReport,
    SecurityAuditor,
)

# Security - Sandbox (v1.2.1)
from agentos.security.sandbox_executor import (
    DockerSandbox,
    ProcessSandbox,
    SandboxExecutor,
    SandboxMode,
    SandboxResult,
)

# MCP Server (v1.3.0)
from agentos.server.mcp_server import (
    MCPPrompt,
    MCPTool,
)

# Storage (v1.2.9)
from agentos.storage import (
    CheckpointStore,
    SqliteStore,
)

# SubAgent Manager (v1.2.9) + Parent-Child Communication (v1.3.15)
from agentos.subagent import (
    ChildContext,
    ChildHandle,
    ChildHeartbeat,
    ChildInfo,
    ChildStatus,
    SharedState,
    SubAgentManager,
    SubAgentMode,
    SubAgentResult,
    SubAgentSpec,
)

# Swarm Patterns (v1.2.8)
from agentos.swarm import (
    CollaborationConfig,
    CollaborationResult,
    SwarmPatterns,
    Topology,
)

# Code Sandbox (v1.9.5)
from agentos.swarm.code_sandbox import (
    CodeFeedbackExtractor,
    CodeSandbox,
)
from agentos.swarm.code_sandbox import (
    SandboxResult as CodeSandboxResult,
)
from agentos.swarm.code_sandbox import (
    TestCase as CodeTestCase,
)

# Swarm coordinator
# Swarm Coordinator extensions (v1.3.2)
from agentos.swarm.coordinator import (
    AgentRole,
    ExecutionMode,
    MessageBus,
    SmartSwarmCoordinator,
    SwarmCoordinator,
    SwarmMessage,
    SwarmResult,
    SwarmTopology,
)

# Human-in-the-Loop (v1.9.5)
from agentos.swarm.human_loop import (
    Breakpoint,
    BreakpointType,
    HITLConfig,
    HITLManager,
    HumanDecision,
)

# Testing Fixtures (v1.3.0)
from agentos.testing.fixtures import (
    MockLLMClient,
    MockLLMResponse,
    mock_model_response,
    mock_openai_client,
    sample_config,
)

# Tools extensions (v1.2.9)
from agentos.tools import (
    BaseTool,
    BaseToolCall,
    BaseToolResult,
    FCToolCall,
    FCToolRegistry,
    FCToolResult,
    GeneratedTool,
    OpenAPIToolGenerator,
    PermissionLevel,
    ToolRegistry,
    ToolSchema,
)

# Concrete Tools (v1.3.0)
from agentos.tools.code_agent import (
    CodeAgentTool,
    ShellTool,
)
from agentos.tools.file_tools import (
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)

# Fusion toolkit
from agentos.tools.fusion import (
    FusionResult,
    FusionToolkit,
    ToolSpec,
)

# Tools - Orchestrator (v1.2.7)
from agentos.tools.orchestrator import (
    DAGBuilder,
    DAGSpec,
    ToolOrchestrator,
)

# Tool risk rating (v1.1.4)
from agentos.tools.risk import (
    ToolRiskLevel,
    ToolRiskRating,
    get_risk_preset,
    infer_risk_level,
)
from agentos.tools.web_tools import (
    WebFetchTool,
)

# Vector Store (v1.2.7)
from agentos.vectorstore import (
    BaseVectorStore,
    ChromaVectorStore,
    FAISSVectorStore,
)

# Workflows (v1.2.7)
from agentos.workflows import (
    WorkflowEngine,
    WorkflowTemplate,
)

__all__ = [
    # Version
    "__version__",
    # Core DI
    "Agent",
    "RunContext",
    "Depends",
    "inject_tool",
    "requires_context",
    # Handoff
    "Handoff",
    "HandoffResult",
    "transfer_to",
    "can_handle",
    "execute_with_handoff",
    "HandoffAwareAgent",
    # CodeAgent
    "CodeAgent",
    "CodeResult",
    "CodeStep",
    # Tool-Using Agent (v1.3.38)
    "ToolAgent",
    "ToolExecutor",
    "AgentConfig",
    "AgentStep",
    "AgentResult",
    "MockLLMProvider",
    # Structured output
    "StructuredOutput",
    "validate_output",
    "OutputValidator",
    # Agent Card
    "AgentCard",
    "AgentCardRegistry",
    "AgentCardDiscovery",
    "discover_local",
    "create_card",
    # A2A
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
    # Memory
    "MemoryPyramid",
    "MemoryLayer",
    "MemoryType",
    "MemoryItem",
    # Evolution
    "EvolutionEngine",
    "EvolutionProposal",
    "EvolutionStatus",
    # Fusion
    "FusionToolkit",
    "FusionResult",
    "ToolSpec",
    # Risk
    "ToolRiskLevel",
    "ToolRiskRating",
    "get_risk_preset",
    "infer_risk_level",
    # Swarm
    "SwarmCoordinator",
    "SmartSwarmCoordinator",
    "SwarmTopology",
    "SwarmMessage",
    "ExecutionMode",
    "SwarmResult",
    # Communication
    "CommunicationLayer",
    "Blackboard",
    "EventBus",
    "Mailbox",
    # Orchestration
    "GraphOrchestrator",
    "GraphNode",
    "GraphEdge",
    # Concurrency
    "AsyncBatchExecutor",
    "BatchTaskStatus",
    "TaskSpec",
    "BatchTaskResult",
    "BatchConfig",
    "BatchResult",
    "BatchStrategy",
    # Cost
    "RunCostSession",
    "CostTracker",
    "ModelPricing",
    "UsageRecord",
    "PRICING",
    # Resilience
    "CancellationSource",
    "CancelledError",
    "RetryConfig",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "ResilienceConfig",
    "ResilientCall",
    "retry_with_backoff",
    "with_timeout",
    "with_fallback",
    # Router
    "ModelRouter",
    # Sandbox
    "SandboxExecutor",
    "SandboxMode",
    "SandboxResult",
    "ProcessSandbox",
    "DockerSandbox",
    # Middleware (v1.2.7)
    "MiddlewarePhase",
    "MiddlewareContext",
    "MiddlewareDecision",
    "AgentMiddleware",
    "MiddlewarePipeline",
    # Queue (v1.2.7)
    "TaskQueue",
    "QueueTaskState",
    "TaskPriority",
    "RateLimiter",
    "RateLimitStrategy",
    "RateLimitConfig",
    # Cache (v1.2.7)
    "LLMCache",
    "CacheEntry",
    "BaseEmbedder",
    "OpenAIEmbedder",
    "LocalEmbedder",
    "CohereEmbedder",
    "ResponseCache",
    "CacheKeyStrategy",
    # Plugins (v1.2.7)
    "PluginRegistry",
    "RegisteredPlugin",
    "PluginStatus",
    "PluginDiscovery",
    "DiscoveredPlugin",
    "PluginLoader",
    "LifecycleManager",
    # Observability (v1.2.7)
    "MetricsCollector",
    "Tracer",
    "NoopTracer",
    "CostAnalytics",
    "BudgetAlert",
    # Workflows (v1.2.7)
    "WorkflowEngine",
    "WorkflowTemplate",
    # MCP Protocol (v1.2.7)
    "MCPClient",
    "MCPServerConfig",
    "MCPToolSchema",
    # Config (v1.2.7)
    "AgentOSConfig",
    "AgentOSPreset",
    "ValidationResult",
    # Evaluation (v1.2.7)
    "Evaluator",
    "CompositeScorer",
    "BenchmarkCase",
    "EvalResult",
    # Audit (v1.2.7)
    "SecurityAuditor",
    "AuditFinding",
    "AuditReport",
    # Orchestrator (v1.2.7)
    "ToolOrchestrator",
    "DAGBuilder",
    "DAGSpec",
    # Memory (v1.2.7)
    "SemanticMemoryRetriever",
    "ConversationMemory",
    # Prompts (v1.2.7)
    "PromptTemplate",
    "PromptRegistry",
    # Multimodal (v1.2.7)
    "MultimodalManager",
    "Modality",
    # Vector Store (v1.2.7)
    "BaseVectorStore",
    "FAISSVectorStore",
    "ChromaVectorStore",
    # Errors (v1.2.8)
    "ErrorCategory",
    "ErrorContext",
    "ErrorFormatter",
    "HumanError",
    # Deployment (v1.2.8)
    "DockerConfig",
    "ComposeService",
    "ComposeConfig",
    # Monitoring (v1.2.8)
    "Alert",
    "AlertEvaluator",
    "AlertRule",
    "AlertSeverity",
    "AlertState",
    "MonitoringConfig",
    "WebhookConfig",
    "WebhookDispatcher",
    # Experiments (v1.2.8)
    "ExperimentRunner",
    "ExperimentConfig",
    "ExperimentReport",
    "PromptVariant",
    "TrialResult",
    "ExperimentEvaluator",
    # Feedback (v1.2.8)
    "FeedbackCollector",
    "FeedbackRecord",
    "FeedbackType",
    "PreferenceLearner",
    # Memory extensions (v1.2.8)
    "MemorySummarizer",
    "ImportanceScorer",
    "MemoryChunk",
    "LongTermMemory",
    "MemoryStore",
    "WorkingMemory",
    "WorkingMemoryItem",
    "VectorMemory",
    # Orchestration extensions (v1.2.8)
    "A2ARouter",
    "RouterAgentCard",
    "RouterTask",
    "TaskResult",
    "TaskStatus",
    "AgentGraph",
    "GraphRecipe",
    "GraphNodeState",
    "GraphResult",
    # Models - Routing (v1.2.8)
    "RoutingStrategy",
    "Complexity",
    "Budget",
    # Swarm Patterns (v1.2.8)
    "SwarmPatterns",
    "Topology",
    "CollaborationConfig",
    "CollaborationResult",
    # Code Sandbox (v1.9.5)
    "CodeSandbox",
    "CodeSandboxResult",
    "CodeTestCase",
    "CodeFeedbackExtractor",
    # Human-in-the-Loop (v1.9.5)
    "HITLManager",
    "HITLConfig",
    "Breakpoint",
    "BreakpointType",
    "HumanDecision",
    # Core extensions (v1.2.9)
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
    # Logging (v1.2.9)
    "JSONFormatter",
    "TraceContext",
    # Health (v1.2.9)
    "HealthChecker",
    "HealthStatus",
    "HealthCheck",
    "CheckResult",
    # Security extensions (v1.9.9)
    "GuardPipeline",
    "InputGuard",
    "OutputGuard",
    "PIIDetector",
    "ContentSafetyFilter",
    "GuardChainResult",
    "GuardResult",
    "GuardAction",
    "Severity",
    "create_strict_guard",
    "create_permissive_guard",
    "SandboxManager",
    "Sandbox",
    "SafetyReport",
    "RiskLevel",
    "LLMSafetyAnalyzer",
    # Storage (v1.2.9)
    "CheckpointStore",
    "SqliteStore",
    # Plugin Manager (v1.2.9)
    "PluginManager",
    "PluginInfo",
    # Cost - Token Counter (v1.2.9)
    "TokenCounter",
    "TokenCount",
    "CostEstimate",
    "ModelFamily",
    # Protocols - Contracts (v1.2.9)
    "AgentContract",
    "AgentCapability",
    "CapabilityDomain",
    "QoSLevel",
    "CapabilityMatcher",
    "ContractRegistry",
    "MatchScore",
    # Memory - Compressor (v1.2.9)
    "ContextCompressor",
    # Tools extensions (v1.2.9)
    "BaseTool",
    "PermissionLevel",
    "BaseToolCall",
    "BaseToolResult",
    "ToolRegistry",
    "ToolSchema",
    "FCToolCall",
    "FCToolResult",
    "FCToolRegistry",
    "OpenAPIToolGenerator",
    "GeneratedTool",
    # SubAgent Manager (v1.2.9) + Parent-Child (v1.3.15)
    "SubAgentManager",
    "SubAgentMode",
    "SubAgentSpec",
    "SubAgentResult",
    "ChildStatus",
    "ChildHeartbeat",
    "ChildInfo",
    "SharedState",
    "ChildContext",
    "ChildHandle",
    # Agent Marketplace (v1.3.0)
    "AgentMarket",
    "AgentSkill",
    "AgentCategory",
    # API Middleware (v1.3.0)
    "CORSConfig",
    "CORSMiddleware",
    "AuthConfig",
    "RequestContext",
    "RequestIDMiddleware",
    # API Streaming (v1.3.0)
    "StreamEvent",
    "StreamSession",
    "StreamingAgent",
    # API Versioning (v1.3.0)
    "APIVersion",
    "VersionStrategy",
    "VersionConfig",
    "VersionNegotiator",
    # Benchmark Runner (v1.3.0)
    "BenchmarkRunner",
    "BenchmarkScenario",
    "BenchmarkConfig",
    "BenchmarkReport",
    # Testing Fixtures (v1.3.0)
    "MockLLMClient",
    "MockLLMResponse",
    "mock_openai_client",
    "mock_model_response",
    "sample_config",
    # MCP Server (v1.3.0)
    "MCPServer",
    "MCPServerConfig",
    "MCPTool",
    "MCPResource",
    "MCPPrompt",
    # Concrete Tools (v1.3.0)
    "CodeAgentTool",
    "ShellTool",
    "ReadFileTool",
    "WriteFileTool",
    "ListDirectoryTool",
    "WebFetchTool",
    # CLI Serve (v1.3.0)
    "ServeConfig",
    "start_api_server",
    # Model Route Types (v1.3.1)
    "ModelResponse",
    "ModelSpec",
    "AllModelsFailed",
    # Gemini Backend (v1.3.1)
    "GeminiClient",
    "GeminiConfig",
    "GeminiSafetySetting",
    # Agent Loop (v1.3.2)
    "AgentLoop",
    "LoopConfig",
    "LoopState",
    "AgentResult",
    "MaxIterationsExceeded",
    "HumanInterruptNeeded",
    # API Server (v1.3.2)
    "AgentAPI",
    "RunRequest",
    "RunResponse",
    # CLI Main (v1.0.0)
    "cli_main",
    # CLI Init (v1.3.2)
    "scaffold",
    # Docs Generator (v1.3.2)
    "DocConfig",
    "generate_api_docs",
    "generate_quickstart",
    # Swarm Coordinator extensions (v1.3.2)
    "AgentRole",
    "MessageBus",
    # Model Config (v1.3.2)
    "ModelConfig",
    "RECOMMENDED_CONFIG",
    # OpenAI Backend (v1.3.5)
    "OpenAIClient",
    "OpenAIConfig",
    # Anthropic Claude Backend (v1.3.5)
    "ClaudeClient",
    "ClaudeConfig",
    # Ollama Backend (v1.3.5)
    "OllamaClient",
    "OllamaConfig",
    # RAG Pipeline (v1.3.5)
    "RAGPipeline",
    "TextChunker",
    "ChunkConfig",
    "EmbeddingConfig",
    # MCP Package (v1.3.6)
    "MCPFullClient",
    "MCPConfig",
    "MCPToolInfo",
    "MCPResourceInfo",
    "MCPPromptInfo",
    "MCPError",
    "connect_mcp_servers",
    # MCP Server (v1.5.2)
    "MCPServer",
    "MCPToolDef",
    "MCPResource",
    "MCPPromptDef",
    "create_default_server",
    "start_mcp_server",
    "MCPToolAdapter",
    "MCPToolRegistry",
    # Built-in MCP Servers
    "FilesystemServer",
    "WebFetchServer",
    "MemoryServer",
    "BuiltinMCPRegistry",
    "create_default_registry",
    # Schema Enforcer (v1.3.9)
    "SchemaEnforcer",
    "EnforcerConfig",
    "EnforcerResult",
    "EnforcerStats",
    "FixStrategy",
    # Conversation Manager (v1.3.10)
    "ConversationManager",
    "ConversationConfig",
    "ConversationStats",
    "ConversationSnapshot",
    "Message",
    "MessageRole",
    "TrimStrategy",
    # Prompt Optimizer (v1.3.12)
    "PromptOptimizer",
    "OptimizerConfig",
    "OptimizationStrategy",
    "OptimizationResult",
    "PromptCandidate",
    # Few-Shot Selector (v1.3.12)
    "FewShotSelector",
    "Example",
    "SelectionStrategy",
    "build_examples",
    # SSE Streaming (v1.3.12)
    "SSEEvent",
    "SSEEventType",
    "SSEStream",
    "SSEResponse",
    # A2A Store (v1.3.13)
    "A2ATaskStore",
    "InMemoryTaskStore",
    "SqliteTaskStore",
    # A2A Streaming (v1.3.13)
    "A2AStreamEvent",
    "TaskProgress",
    "A2AStreamSession",
    "A2AStreamManager",
    # LLM Provider Module (v1.3.36)
    "LLMProvider",
    "OpenAIProvider",
    "DeepSeekProvider",
    "AnthropicProvider",
    "CompletionResult",
    "CompletionChoice",
    "CompletionUsage",
    "TokenUsage",
    "LLMMessage",
    "LLMMessageRole",
    "LLMStreamChunk",
    "LLMTool",
    "LLMToolCall",
    "LLMToolFunction",
    "LLMToolParameter",
    "create_llm_provider",
    # Enterprise (v1.5.5)
    "APIKeyManager",
    "APIKey",
    "KeyScope",
    "KeyCreateRequest",
    "KeyCreateResult",
    "TenantManager",
    "Tenant",
    "TenantConfig",
    "TenantUsage",
    "TenantTier",
    "TenantStatus",
    "TIER_QUOTAS",
    "User",
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "RBACEngine",
    "EnterpriseSession",
    "EnterpriseSessionStore",
    "JWTManager",
    "SSOProvider",
    "OIDCConfig",
    "SAMLConfig",
    "SSOUser",
    "AuditLogger",
    "AuditEvent",
    "AuditCategory",
    "AuditSeverity",
    "RetentionPolicy",
    # System Layer (v1.6.0) — P0: OS-level operations
    "SystemPermissionManager",
    "SystemPermission",
    "PermissionTier",
    "PermissionDenied",
    "SAFE_PERMISSIONS",
    "DEV_PERMISSIONS",
    "FULL_PERMISSIONS",
    "FileOperator",
    "FileOpResult",
    "FileListing",
    "ShellExecutor",
    "ShellResult",
    "ShellSandbox",
    "ShellPolicy",
    "READONLY_POLICY",
    "STANDARD_POLICY",
    "FULL_POLICY",
    "CDPBrowser",
    "BrowserSession",
    "BrowserAction",
    "BrowserResult",
    # Desktop Client (v1.7.0) — P1: One-click desktop
    "DesktopServer",
    "DesktopConfig",
    "launch_desktop",
    # v1.10.0: Evaluation (SWE-bench + GAIA)
    "EvalMetric",
    "EvalSuite",
    "EvalCase",
    "EvalSample",
    "EvalResult",
    "EvalReport",
    "Scorer",
    "ExactMatchScorer",
    "F1Scorer",
    "ROUGELScorer",
    "get_scorer",
    "SWEBenchLoader",
    "GAIALoader",
    "EvalRunner",
    "EvalRegistry",
    "evaluate_quick",
    # v1.10.0: Prompt Hub
    "PromptType",
    "PromptTag",
    "PromptVersion",
    "PromptHub",
    "BUILTIN_PROMPTS",
    "create_default_hub",
    # v1.11.0: Background Task Manager
    "BackgroundTaskManager",
    "BackgroundTask",
    "BackgroundTaskStatus",
    "BackgroundTaskConfig",
    "TaskProgress",
    "ProgressPhase",
    # v1.11.0: Agent Supervision Tree
    "AgentSupervisor",
    "SupervisedAgent",
    "SupervisorConfig",
    "AgentQuota",
    "SupervisionEvent",
    "SupervisionEventType",
    # v1.12.0: Virtual Memory Pager
    "MemoryPager",
    "SwapStore",
    "MemoryPage",
    "PagerStats",
    "create_paging_callback",
    "recall_relevant_memories",
    # v1.12.1: Async Parallel Primitives
    "ParallelExecutor",
    "FanOutExecutor",
    "FanOutConfig",
    "TaskThrottler",
    "ParallelTaskResult",
    "ParallelTaskStatus",
    "ParallelGatherResult",
    "parallel_gather",
    "parallel_map",
    "create_parallel_agent_gather",
]

# Enterprise (v1.5.5)
# SSE Streaming (v1.3.12)
from agentos.api.sse import (
    SSEEvent,
    SSEEventType,
    SSEResponse,
    SSEStream,
)

# ── v1.11.0: Agent Supervision Tree ──
from agentos.background.supervisor import (
    AgentQuota,
    AgentSupervisor,
    SupervisedAgent,
    SupervisionEvent,
    SupervisionEventType,
    SupervisorConfig,
)

# ── v1.11.0: Background Task Manager ──
from agentos.background.task_manager import (
    BackgroundTask,
    BackgroundTaskConfig,
    BackgroundTaskManager,
    BackgroundTaskStatus,
    ProgressPhase,
    TaskProgress,
)

# Conversation Manager (v1.3.10)
from agentos.conversation.conversation import (
    ConversationConfig,
    ConversationManager,
    ConversationSnapshot,
    ConversationStats,
    Message,
    MessageRole,
    TrimStrategy,
)

# Desktop Client (v1.7.0) — P1: One-click web desktop (AutoClaw-inspired)
from agentos.desktop.server import (
    DesktopConfig,
    DesktopServer,
    launch_desktop,
)
from agentos.enterprise import (
    ROLE_PERMISSIONS,
    TIER_QUOTAS,
    APIKey,
    APIKeyManager,
    AuditCategory,
    AuditEvent,
    AuditLogger,
    AuditSeverity,
    JWTManager,
    KeyCreateRequest,
    KeyCreateResult,
    KeyScope,
    OIDCConfig,
    Permission,
    RBACEngine,
    RetentionPolicy,
    Role,
    SAMLConfig,
    SSOProvider,
    SSOUser,
    Tenant,
    TenantConfig,
    TenantManager,
    TenantStatus,
    TenantTier,
    TenantUsage,
    User,
)
from agentos.enterprise import (
    Session as EnterpriseSession,
)
from agentos.enterprise import (
    SessionStore as EnterpriseSessionStore,
)

# ── v1.10.0: Evaluation Framework (SWE-bench + GAIA) ──
from agentos.eval.benchmark import (
    EvalCase,
    EvalMetric,
    EvalRegistry,
    EvalResult,
    EvalRunner,
    EvalSample,
    EvalSuite,
    ExactMatchScorer,
    F1Scorer,
    GAIALoader,
    ROUGELScorer,
    SWEBenchLoader,
    evaluate_quick,
    get_scorer,
)

# Guardrails (v1.3.11)
# HITL (v1.3.11)
# LLM Provider Module (v1.3.36)
from agentos.llm import (
    AnthropicProvider,
    CompletionChoice,
    CompletionResult,
    CompletionUsage,
    DeepSeekProvider,
    LLMProvider,
    OpenAIProvider,
    TokenUsage,
)
from agentos.llm import (
    Message as LLMMessage,
)
from agentos.llm import (
    MessageRole as LLMMessageRole,
)
from agentos.llm import (
    StreamChunk as LLMStreamChunk,
)
from agentos.llm import (
    Tool as LLMTool,
)
from agentos.llm import (
    ToolCall as LLMToolCall,
)
from agentos.llm import (
    ToolFunction as LLMToolFunction,
)
from agentos.llm import (
    ToolParameter as LLMToolParameter,
)
from agentos.llm import (
    create_provider as create_llm_provider,
)

# ── v1.12.0: Virtual Memory Pager ──
from agentos.memory.pager import (
    MemoryPage,
    MemoryPager,
    PagerStats,
    SwapStore,
    create_paging_callback,
    recall_relevant_memories,
)

# ── v1.10.0: Prompt Hub (versioned templates) ──
from agentos.prompt.hub import (
    BUILTIN_PROMPTS,
    PromptHub,
    PromptTag,
    PromptType,
    PromptVersion,
    create_default_hub,
)

# Few-Shot Selector (v1.3.12)
from agentos.prompts.few_shot import (
    Example,
    FewShotSelector,
    SelectionStrategy,
    build_examples,
)

# Prompt Optimizer (v1.3.12)
from agentos.prompts.optimizer import (
    OptimizationResult,
    OptimizationStrategy,
    OptimizerConfig,
    PromptCandidate,
    PromptOptimizer,
)

# A2A Store (v1.3.13)
from agentos.protocols.a2a_store import (
    A2ATaskStore,
    InMemoryTaskStore,
    SqliteTaskStore,
)

# A2A Streaming (v1.3.13)
from agentos.protocols.a2a_streaming import (
    A2AStreamEvent,
    A2AStreamManager,
    A2AStreamSession,
)
from agentos.system.browser import (
    BrowserAction,
    BrowserResult,
    BrowserSession,
    CDPBrowser,
)
from agentos.system.file_ops import (
    FileListing,
    FileOperator,
    FileOpResult,
)

# System Layer (v1.6.0) — P0: OS-level operations with tiered permissions
from agentos.system.permissions import (
    DEV_PERMISSIONS,
    FULL_PERMISSIONS,
    SAFE_PERMISSIONS,
    PermissionDenied,
    PermissionTier,
    SystemPermission,
    SystemPermissionManager,
)
from agentos.system.shell_exec import (
    FULL_POLICY,
    READONLY_POLICY,
    STANDARD_POLICY,
    ShellExecutor,
    ShellPolicy,
    ShellResult,
    ShellSandbox,
)

# Schema Enforcer (v1.3.9)
from agentos.validation.schema_enforcer import (
    EnforcerConfig,
    EnforcerResult,
    EnforcerStats,
    FixStrategy,
    SchemaEnforcer,
)
