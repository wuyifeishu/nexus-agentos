---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 3e9b297b16411e0e0848fc0302358070_4baa7dcc747011f1897e5254002afed2
    ReservedCode1: /Ms7sVmYRslHIB+Q+6D35t5ugEn+EgkC9mH+2qQnrO7UOm/75/qFFCDdSbOZAi9ro0KcZjURjVCQiFs1KSpGxCmNf+MwQzXFix84jRdVmiePdDoxiBE90I3LsKpdduFwqwCKevCyiUSaCw/idQvfBUIW0GcOOQhU2qRmjCIQvgvkOKKwh26Zb4gCluk=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 3e9b297b16411e0e0848fc0302358070_4baa7dcc747011f1897e5254002afed2
    ReservedCode2: /Ms7sVmYRslHIB+Q+6D35t5ugEn+EgkC9mH+2qQnrO7UOm/75/qFFCDdSbOZAi9ro0KcZjURjVCQiFs1KSpGxCmNf+MwQzXFix84jRdVmiePdDoxiBE90I3LsKpdduFwqwCKevCyiUSaCw/idQvfBUIW0GcOOQhU2qRmjCIQvgvkOKKwh26Zb4gCluk=
---



# AgentOS API Reference

> 自动生成 | 版本 1.4.2 | 141 个模块

---

## 目录

- [plugin_manager](#plugin_manager)
- [plugins](#plugins)
- [conversation.conversation](#conversationconversation)
- [security.auditor](#securityauditor)
- [security.guard](#securityguard)
- [security.sandbox](#securitysandbox)
- [security.sandbox_executor](#securitysandbox_executor)
- [orchestration.a2a_router](#orchestrationa2a_router)
- [orchestration.graph](#orchestrationgraph)
- [orchestration.graph_executor](#orchestrationgraph_executor)
- [evaluation.benchmark](#evaluationbenchmark)
- [evaluation.regression](#evaluationregression)
- [evaluation.scorers](#evaluationscorers)
- [cache.embedder](#cacheembedder)
- [cache.llm_cache](#cachellm_cache)
- [cache.response_cache](#cacheresponse_cache)
- [validation.schema_enforcer](#validationschema_enforcer)
- [workflows.engine](#workflowsengine)
- [workflows.templates](#workflowstemplates)
- [multimodal.manager](#multimodalmanager)
- [api.middleware](#apimiddleware)
- [api.server](#apiserver)
- [api.sse](#apisse)
- [api.streaming](#apistreaming)
- [api.versioning](#apiversioning)
- [api.websocket](#apiwebsocket)
- [plugins.discovery](#pluginsdiscovery)
- [plugins.lifecycle](#pluginslifecycle)
- [plugins.loader](#pluginsloader)
- [plugins.registry](#pluginsregistry)
- [agents.market](#agentsmarket)
- [testing.fixtures](#testingfixtures)
- [experiments.runner](#experimentsrunner)
- [models.resilience](#modelsresilience)
- [models.router](#modelsrouter)
- [models.routing_strategy](#modelsrouting_strategy)
- [models.backends.anthropic](#modelsbackendsanthropic)
- [models.backends.gemini](#modelsbackendsgemini)
- [models.backends.ollama](#modelsbackendsollama)
- [models.backends.openai](#modelsbackendsopenai)
- [evolution.engine](#evolutionengine)
- [agent.tool_agent](#agenttool_agent)
- [agent.examples.weather_agent](#agentexamplesweather_agent)
- [agent.tests.test_integration](#agentteststest_integration)
- [agent.tests.test_tool_agent](#agentteststest_tool_agent)
- [errors.handler](#errorshandler)
- [comm.layer](#commlayer)
- [tools.base](#toolsbase)
- [tools.code_agent](#toolscode_agent)
- [tools.file_tools](#toolsfile_tools)
- [tools.function_calling](#toolsfunction_calling)
- [tools.fusion](#toolsfusion)
- [tools.generator](#toolsgenerator)
- [tools.orchestrator](#toolsorchestrator)
- [tools.registry](#toolsregistry)
- [tools.risk](#toolsrisk)
- [tools.web_tools](#toolsweb_tools)
- [server.mcp_server](#servermcp_server)
- [mcp.adapter](#mcpadapter)
- [log.formatter](#logformatter)
- [queue.rate_limiter](#queuerate_limiter)
- [queue.task_queue](#queuetask_queue)
- [hitl.approver](#hitlapprover)
- [hitl.presets](#hitlpresets)
- [vectorstore.db](#vectorstoredb)
- [storage.base](#storagebase)
- [observability.cost_analytics](#observabilitycost_analytics)
- [observability.metrics](#observabilitymetrics)
- [observability.otel_bridge](#observabilityotel_bridge)
- [observability.tracer](#observabilitytracer)
- [prompts.few_shot](#promptsfew_shot)
- [prompts.manager](#promptsmanager)
- [prompts.optimizer](#promptsoptimizer)
- [llm.anthropic_provider](#llmanthropic_provider)
- [llm.base](#llmbase)
- [llm.deepseek_provider](#llmdeepseek_provider)
- [llm.factory](#llmfactory)
- [llm.openai_provider](#llmopenai_provider)
- [llm.examples.llm_chat_demo](#llmexamplesllm_chat_demo)
- [llm.examples.llm_quickstart](#llmexamplesllm_quickstart)
- [llm.tests.test_providers](#llmteststest_providers)
- [cli.config_panel](#cliconfig_panel)
- [cli.init](#cliinit)
- [cli.main](#climain)
- [cli.serve](#cliserve)
- [concurrency.batch](#concurrencybatch)
- [protocols.a2a](#protocolsa2a)
- [protocols.a2a_store](#protocolsa2a_store)
- [protocols.a2a_streaming](#protocolsa2a_streaming)
- [protocols.agent_card](#protocolsagent_card)
- [protocols.contracts](#protocolscontracts)
- [protocols.mcp](#protocolsmcp)
- [protocols.output](#protocolsoutput)
- [subagent.collaboration](#subagentcollaboration)
- [subagent.manager](#subagentmanager)
- [subagent.parent_child](#subagentparent_child)
- [deployment.docker](#deploymentdocker)
- [config.loader](#configloader)
- [config.presets](#configpresets)
- [config.validator](#configvalidator)
- [monitoring.alerts](#monitoringalerts)
- [guardrails.engine](#guardrailsengine)
- [guardrails.policy](#guardrailspolicy)
- [guardrails.rules](#guardrailsrules)
- [benchmarks.runner](#benchmarksrunner)
- [tests.test_1_1_4_features](#teststest_1_1_4_features)
- [tests.test_a2a](#teststest_a2a)
- [tests.test_conversation](#teststest_conversation)
- [tests.test_guardrails](#teststest_guardrails)
- [tests.test_hitl](#teststest_hitl)
- [tests.test_mcp](#teststest_mcp)
- [tests.test_sandbox_executor](#teststest_sandbox_executor)
- [tests.test_schema_enforcer](#teststest_schema_enforcer)
- [tests.test_subagent_parent_child](#teststest_subagent_parent_child)
- [memory.compressor](#memorycompressor)
- [memory.conversation](#memoryconversation)
- [memory.long_term](#memorylong_term)
- [memory.pyramid](#memorypyramid)
- [memory.retriever](#memoryretriever)
- [memory.short_term](#memoryshort_term)
- [memory.summarizer](#memorysummarizer)
- [memory.working](#memoryworking)
- [swarm.coordinator](#swarmcoordinator)
- [swarm.patterns](#swarmpatterns)
- [core.async_loop](#coreasync_loop)
- [core.code_agent](#corecode_agent)
- [core.context](#corecontext)
- [core.di](#coredi)
- [core.handoff](#corehandoff)
- [core.loop](#coreloop)
- [core.middleware](#coremiddleware)
- [core.session](#coresession)
- [core.state_machine](#corestate_machine)
- [core.streaming](#corestreaming)
- [cost.token_counter](#costtoken_counter)
- [cost.tracker](#costtracker)
- [feedback.learner](#feedbacklearner)
- [rag.citation](#ragcitation)
- [rag.hybrid](#raghybrid)
- [rag.reranker](#ragreranker)
- [docs.generator](#docsgenerator)

---

## plugin_manager

AgentOS v0.20 插件系统。
支持动态加载第三方工具、Agent、工作流。

### 类

#### `PluginInfo`

插件信息。

#### `PluginManager`

插件管理器 — 动态发现、加载、卸载插件。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, plugin_dirs: list[str] | None) -> None` |
| `discover` | `def (self) -> list[PluginInfo]` |
| `register` | `def (self, info: PluginInfo) -> None` |
| `load` | `def (self, name: str) -> Any` |
| `unload` | `def (self, name: str) -> None` |
| `add_hook` | `def (self, hook_name: str, callback: Callable) -> None` |
| `call_hook` | `def (self, hook_name: str, *args, **kwargs) -> None` |
| `loaded_plugins` | `def (self) -> list[str]` |

---

## plugins

plugins.py - backward compatibility shim for agentos.plugins

All actual implementation has moved to agentos.plugin_manager.
This module re-exports for existing import paths.

---

## conversation.conversation

AgentOS v1.3.10 - Conversation Manager 模块。

多轮对话上下文管理：滑动窗口、自动摘要、对话分支、token 感知裁剪。
适用于长会话场景，防止上下文溢出，同时保持关键信息不丢失。

### 类

#### `MessageRole(str, Enum)`

消息角色。

#### `TrimStrategy(Enum)`

裁剪策略。

#### `Message`

单条对话消息。

#### `ConversationConfig`

对话管理配置。

#### `ConversationStats`

对话统计。

#### `ConversationSnapshot`

对话快照（用于分支/恢复）。

#### `ConversationManager`

多轮对话上下文管理器。

核心功能：
- 滑动窗口：超出 max_messages/max_tokens 时自动裁剪
- 自动摘要：超出阈值时压缩历史消息为摘要
- 对话分支：支持 fork 创建分支，切换/合并分支
- Token 感知：按 token 预算精确裁剪

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: ConversationConfig | None) -> None` |
| `add` | `def (self, role: MessageRole | str, content: str, **meta) -> Message` |
| `add_many` | `def (self, messages: list[tuple[str, str]]) -> list[Message]` |
| `get_context` | `def (self, include_summary: bool, limit: int | None) -> list[dict]` |
| `get_system_prompt` | `def (self) -> str` |
| `set_summarizer` | `def (self, callback: Callable[[list[Message]], str]) -> None` |
| `fork` | `def (self, label: str) -> ConversationSnapshot` |
| `switch_branch` | `def (self, snapshot_id: str) -> None` |
| `merge_branch` | `def (self, snapshot_id: str, strategy: str) -> None` |
| `list_branches` | `def (self) -> dict[str, ConversationSnapshot]` |
| `clear` | `def (self, keep_system: bool) -> None` |
| `message_count` | `def (self) -> int` |
| `token_count` | `def (self) -> int` |
| `__repr__` | `def (self) -> str` |

---

## security.auditor

AgentOS Security Auditor — automated vulnerability scanning and code analysis.

Audits dependencies and source patterns for common security issues.

### 类

#### `AuditSeverity(Enum)`

Severity level for security audit findings.

#### `AuditFinding`

A single security finding from an audit scan.

Attributes:
    id: Unique finding identifier.
    category: Finding category (e.g., injection, hardcoded_secret).
    severity: Severity level.
    message: Human-readable description.
    location: File path and line reference.
    recommendation: Suggested remediation.
    cve: Optional CVE identifier if known.

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |

#### `AuditReport`

Aggregated report of all audit findings across scanned resources.

Attributes:
    findings: List of individual findings.
    scanned_files: Number of files scanned.
    scanned_deps: Number of dependencies checked.

| 方法 | 签名 |
|------|------|
| `critical` | `def (self) -> int` |
| `high` | `def (self) -> int` |
| `medium` | `def (self) -> int` |
| `low` | `def (self) -> int` |
| `passed` | `def (self) -> bool` |
| `summary` | `def (self) -> str` |
| `to_dict` | `def (self) -> dict` |
| `to_json` | `def (self) -> str` |
| `to_markdown` | `def (self) -> str` |

#### `SecurityAuditor`

High-level security auditor that orchestrates dependency and source scanning.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, req_path: Optional[str | Path], source_dir: Optional[str | Path]) -> None` |
| `scan_dependencies` | `def (self, req_path: Optional[str | Path]) -> AuditReport` |
| `scan_source` | `def (self, paths: Optional[list[str | Path]]) -> AuditReport` |
| `full_audit` | `def (self, source_dir: Optional[str | Path], req_path: Optional[str | Path]) -> AuditRep` |

### 函数

| 函数 | 签名 |
|------|------|
| `scan_dependencies` | `def (req_path: str | Path) -> AuditReport` |
| `scan_source` | `def (source_dir: str | Path) -> AuditReport` |
| `full_audit` | `def (source_dir: str | Path, req_path: str | Path) -> AuditReport` |
| `export_report` | `def (report: AuditReport, fmt: str) -> str` |

---

## security.guard

AgentOS v0.60 Guardrails — 安全护栏。
输入过滤（提示注入/PII/敏感词）+ 输出审核（内容策略/有害内容）+ 沙箱执行。

### 类

#### `ContentRisk(str, Enum)`

Content safety risk level for input/output guard analysis.

#### `GuardResult`

Result of a guardrail check on input or output content.

Attributes:
    passed: Whether the content passed all guard checks.
    risk: Highest risk level detected.
    reason: Human-readable explanation.
    flagged_patterns: List of pattern names that triggered.
    action: Recommended action (allow/warn/block/sanitize).

#### `Guardrails`

统一安全护栏：输入过滤 + 输出审核。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, block_pii: bool, block_injection: bool, moderation_threshold: ContentRisk) ->` |
| `check_input` | `def (self, text: str) -> GuardResult` |
| `check_output` | `def (self, text: str) -> GuardResult` |
| `validate` | `def (self, user_input: str, model_output: Optional[str]) -> tuple[GuardResult, GuardResu` |

#### `PIISanitizer`

PII脱敏工具。

| 方法 | 签名 |
|------|------|
| `@classmethod sanitize` | `def (cls, text: str) -> tuple[str, int]` |
| `@classmethod is_sanitized` | `def (cls, text: str) -> bool` |

#### `ContentHasher`

内容指纹：用于检测重复/回放攻击。

| 方法 | 签名 |
|------|------|
| `@staticmethod hash` | `def (text: str) -> str` |
| `@staticmethod similar` | `def (a: str, b: str, threshold: float) -> bool` |

---

## security.sandbox

安全沙箱 — Docker隔离 + LLM操作级分析。
基因来源: OpenHands + Claude Code

v1.2.1: SandboxExecutor 提升为一级导出，提供真正的代码隔离执行。

### 类

#### `RiskLevel(str, Enum)`

Safety risk classification for sandboxed operations.

#### `SafetyReport`

Result of a safety analysis for a sandboxed operation.

Attributes:
    risk: Classified risk level.
    reason: Explanation of the risk assessment.

#### `Sandbox`

安全沙箱 — 每个Agent会话对应一个隔离环境。
生产环境使用Docker容器，当前为本地简化实现。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, session_id: str, workspace: str) -> None` |
| `is_allowed` | `def (self, tool_name: str, arguments: dict) -> bool` |
| `execute_code` | `async def (self, code: str, language: str) -> Any` |

#### `SandboxManager`

沙箱管理器 — 创建和销毁沙箱。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `get_sandbox` | `def (self, session_id: str) -> Sandbox` |
| `destroy` | `def (self, session_id: str) -> None` |

#### `LLMSafetyAnalyzer`

操作级LLM安全分析 — 执行前用轻量模型评估风险。
生产环境: 调用轻量模型分析每次代码执行的安全性。
当前为规则匹配简化实现。

| 方法 | 签名 |
|------|------|
| `analyze` | `async def (self, code: str) -> SafetyReport` |

---

## security.sandbox_executor

AgentOS v1.2.1 — 沙箱执行器。

基因来源: OpenHands Docker Sandbox + Claude Code subprocess isolation

提供真正的代码/命令隔离执行能力：
- Process模式: 子进程隔离（轻量，零依赖）
- Docker模式: 容器隔离（强隔离，需Docker）
- 资源限制：内存、CPU、时间、磁盘
- 文件桥接：自动复制输入文件到沙箱，提取输出文件
- 与 CodeAgent / ToolOrchestrator 集成

### 类

#### `SandboxMode(str, Enum)`

沙箱模式枚举。

#### `SandboxConfig`

沙箱执行配置

#### `SandboxResult`

沙箱执行结果

#### `ProcessSandbox`

进程级隔离沙箱。使用 subprocess + 临时目录隔离文件系统。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: SandboxConfig | None) -> None` |
| `setup` | `def (self) -> str` |
| `copy_in` | `def (self, src: str, dst_filename: str | None) -> str` |
| `copy_out` | `def (self, sandbox_path: str, local_path: str) -> str` |
| `collect_output_files` | `def (self, patterns: List[str] | None) -> Dict[str, str]` |
| `execute_code` | `def (self, code: str, language: str, input_files: Dict[str, str] | None) -> SandboxResul` |
| `execute_command` | `def (self, command: str | List[str]) -> SandboxResult` |
| `cleanup` | `def (self) -> None` |

#### `DockerSandbox`

Docker 容器隔离沙箱。更强的隔离性和可重现性。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: SandboxConfig | None) -> None` |
| `setup` | `def (self) -> str` |
| `copy_in` | `def (self, src: str, dst_filename: str | None) -> str` |
| `execute_code` | `def (self, code: str, language: str, input_files: Dict[str, str] | None) -> SandboxResul` |
| `execute_command` | `def (self, command: str | List[str]) -> SandboxResult` |
| `collect_output_files` | `def (self, patterns: List[str] | None) -> Dict[str, str]` |
| `cleanup` | `def (self) -> None` |

#### `SandboxExecutor`

统一沙箱执行器。根据 SandboxConfig.mode 自动选择 Process/Docker。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: SandboxConfig | None) -> None` |
| `execute_code` | `async def (self, code: str, language: str, input_files: Dict[str, str] | None) -> Sandbo` |
| `execute_command` | `async def (self, command: str | List[str]) -> SandboxResult` |
| `collect_output_files` | `def (self, patterns: List[str] | None) -> Dict[str, str]` |
| `cleanup` | `async def (self) -> None` |

---

## orchestration.a2a_router

A2A协议路由 — 跨框架Agent互操作。
基因来源: Google ADK A2A Protocol

### 类

#### `TaskStatus(str, Enum)`

任务状态枚举。

#### `AgentCard`

Agent名片 — A2A协议中Agent互相发现的基础。

#### `Task`

结构化任务 — A2A协议的任务定义。

#### `TaskResult`

Result of an A2A routed task execution.

#### `A2ARouter`

A2A协议路由 — 让不同框架构建的Agent相互通信。

核心流程:
1. Agent Card 注册 → 互相发现
2. Task 委派 → 结构化任务传递
3. Message 协商 → 多轮异步通信
4. Artifact 返回 → 产物传递

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `register_local` | `def (self, card: AgentCard) -> None` |
| `discover_remote` | `def (self, cards: list[AgentCard]) -> None` |
| `find_agent` | `def (self, capability: str) -> AgentCard | None` |
| `delegate` | `def (self, task: Task, agent_id: str | None) -> TaskResult` |
| `list_agents` | `def (self) -> list[AgentCard]` |

---

## orchestration.graph

Graph Orchestrator for NexusAgent.

DAG-based workflow orchestration. Allows defining
complex workflows as graphs with nodes and edges.

### 类

#### `NodeStatus(str, Enum)`

Node execution status.

#### `GraphNode`

Node in execution graph.

Attributes:
    id: Unique identifier
    name: Node name
    func: Node function
    inputs: Input parameters
    outputs: Output values
    status: Execution status
    duration: Execution duration
    error: Error message (if failed)
    metadata: Additional metadata

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `GraphEdge`

Edge in execution graph.

Attributes:
    source: Source node ID
    target: Target node ID
    condition: Optional condition function
    metadata: Additional metadata

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `GraphResult`

Result of graph execution.

Attributes:
    id: Unique identifier
    node_results: Node execution results
    total_duration: Total execution duration
    success: Whether execution succeeded
    error: Error message (if failed)

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `GraphOrchestrator`

DAG-based workflow orchestrator.

Allows defining complex workflows as graphs:
- Nodes represent tasks
- Edges represent dependencies
- Conditions for branching

Usage:
    orchestrator = GraphOrchestrator()

    # Add nodes
    orchestrator.add_node("step1", step1_func)
    orchestrator.add_node("step2", step2_func)

    # Add edges
    orchestrator.add_edge("step1", "step2")

    # Execute
    result = await orchestrator.execute({"input": "data"})

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `add_node` | `def (self, name: str, func: Callable[..., Any], **metadata) -> GraphNode` |
| `remove_node` | `def (self, name: str) -> bool` |
| `add_edge` | `def (self, source: str, target: str, condition: Optional[Callable[[dict[str, Any]], bool` |
| `remove_edge` | `def (self, source: str, target: str) -> bool` |
| `get_node` | `def (self, name: str) -> Optional[GraphNode]` |
| `list_nodes` | `def (self) -> list[str]` |
| `list_edges` | `def (self) -> list[tuple[str, str]]` |
| `execute` | `async def (self, inputs: dict[str, Any], **metadata) -> GraphResult` |
| `get_execution_order` | `def (self) -> list[str]` |
| `validate` | `def (self) -> bool` |
| `clear` | `def (self) -> None` |

---

## orchestration.graph_executor

Agent Graph — DAG-based multi-agent execution engine.

Build complex agent pipelines as directed acyclic graphs where each node
is an agent invocation and edges define data flow dependencies.

### 类

#### `GraphNodeState(Enum)`

Execution state of a graph orchestrator node.

#### `GraphNode`

A single node in the agent execution graph.

| 方法 | 签名 |
|------|------|
| `resolve_task` | `def (self, node_outputs: dict[str, Any]) -> str` |

#### `GraphResult`

Result of graph execution.

#### `AgentGraph`

DAG-based multi-agent execution engine.

Define execution graphs declaratively, resolve dependencies automatically,
execute nodes in topological order with parallelism for independent nodes.

Example::

    graph = AgentGraph()
    graph.add_node(GraphNode(
        name="research",
        agent_type="researcher",
        task_template="Research: {input}"
    ))
    graph.add_node(GraphNode(
        name="summarize",
        agent_type="summarizer",
        task_template="Summarize: {research.output}",
        depends_on=["research"]
    ))
    result = graph.execute("quantum computing advances")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, executor: Optional[Callable[[str, str], Any]]) -> None` |
| `add_node` | `def (self, node: GraphNode) -> None` |
| `remove_node` | `def (self, name: str) -> None` |
| `validate` | `def (self) -> list[str]` |
| `execute` | `def (self, input_data: str) -> GraphResult` |
| `to_mermaid` | `def (self) -> str` |
| `node_count` | `def (self) -> int` |
| `edge_count` | `def (self) -> int` |

#### `GraphRecipe`

Declarative graph definition (YAML-friendly).

| 方法 | 签名 |
|------|------|
| `@classmethod from_dict` | `def (cls, data: dict) -> 'GraphRecipe'` |
| `build` | `def (self, executor: Optional[Callable]) -> AgentGraph` |

---

## evaluation.benchmark

AgentOS v0.20 评测框架。
支持 SWE-bench、Tool-use 等基准测试。

### 类

#### `BenchmarkCase`

A single benchmark evaluation case.

#### `EvalResult`

Result of a benchmark evaluation run.

#### `Evaluator`

评测运行器。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, agent_loop: Any) -> None` |
| `evaluate` | `async def (self, benchmark: list[BenchmarkCase]) -> list[EvalResult]` |
| `pass_rate` | `def (self) -> float` |
| `avg_score` | `def (self) -> float` |
| `summary` | `def (self) -> str` |

### 函数

| 函数 | 签名 |
|------|------|
| `builtin_benchmarks` | `def () -> list[BenchmarkCase]` |

---

## evaluation.regression

Evaluation regression testing for AgentOS.

Compare evaluation runs, detect regressions, generate CI artifacts.
Builds on top of agentos.evaluation core (GoldenDataset, Evaluator, EvalReport).

### 类

#### `RegressionCheck`

A single regression check result.

#### `RegressionReport`

Comparison report between baseline and current evaluation.

| 方法 | 签名 |
|------|------|
| `to_markdown` | `def (self) -> str` |

#### `RegressionRunner`

Detect regressions by comparing baseline and current evaluation runs.

Usage:
    runner = RegressionRunner(evaluator, baseline=report)
    report = await runner.check(current_report)
    # or sync:
    report = runner.check_sync(current_report)

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, evaluator: Evaluator, baseline: Optional[EvalReport], threshold: float, sever` |
| `run_baseline` | `async def (self) -> EvalReport` |
| `check` | `async def (self, current: Optional[EvalReport]) -> RegressionReport` |
| `check_sync` | `def (self, current: EvalReport) -> RegressionReport` |

#### `StatResult`

Statistical summary of N evaluation runs.

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |

#### `StatisticalRunner`

Run evaluation N times and compute statistics.

Usage:
    srunner = StatisticalRunner(evaluator, trials=10)
    stats = await srunner.run()

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, evaluator: Evaluator, trials: int) -> None` |
| `run` | `async def (self) -> StatResult` |

### 函数

| 函数 | 签名 |
|------|------|
| `to_junit_xml` | `def (report: EvalReport, suite_name: str) -> str` |
| `to_json` | `def (report: EvalReport, indent: int) -> str` |
| `save_report` | `def (report: EvalReport, path: str, format: str) -> None` |

---

## evaluation.scorers

AgentOS v0.70 — 评测打分系统。
基因来源: ROUGE/BLEU 经典算法 + 语义相似度

评分策略:
- ROUGE-L: 最长公共子序列召回率 (摘要质量)
- BLEU: n-gram精确率 (翻译质量)
- Semantic: 基于embedding的语义相似度
- Exact: 精确匹配
- Contains: 包含匹配

### 类

#### `ScoringStrategy`

评分配置策略。

#### `ScoreResult`

评分结果。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |

#### `CompositeScorer`

复合评分器 — 多策略加权。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, strategy: ScoringStrategy | None) -> None` |
| `score` | `def (self, reference: str, candidate: str, embedder: Any) -> ScoreResult` |
| `batch_score` | `def (self, pairs: list[tuple[str, str]], embedder: Any) -> list[ScoreResult]` |

### 函数

| 函数 | 签名 |
|------|------|
| `rouge_l` | `def (reference: str, candidate: str) -> float` |
| `bleu` | `def (reference: str, candidate: str, max_n: int) -> float` |
| `semantic_similarity` | `def (candidate: str, reference: str, embedder: Any) -> float` |
| `exact_match` | `def (reference: str, candidate: str) -> float` |
| `contains_match` | `def (reference: str, candidate: str) -> float` |

---

## cache.embedder

Embedding实现层 — 多种embedding provider的真实调用。
v0.50: 新增模块。为语义缓存/向量数据库提供embedding实现。

### 类

#### `EmbeddingResult`

Result of an embedding generation request.

#### `BaseEmbedder(ABC)`

Embedding提供者抽象基类。

| 方法 | 签名 |
|------|------|
| `embed` | `async def (self, text: str) -> EmbeddingResult` |
| `embed_batch` | `async def (self, texts: list[str]) -> list[EmbeddingResult]` |
| `dimension` | `def (self) -> int` |

#### `OpenAIEmbedder(BaseEmbedder)`

OpenAI text-embedding-3-small / text-embedding-3-large.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, model: str, api_key: str, base_url: str) -> None` |
| `dimension` | `def (self) -> int` |
| `embed` | `async def (self, text: str) -> EmbeddingResult` |
| `embed_batch` | `async def (self, texts: list[str]) -> list[EmbeddingResult]` |
| `close` | `async def (self) -> None` |

#### `LocalEmbedder(BaseEmbedder)`

本地sentence-transformers模型。无API调用，零成本。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, model_name: str) -> None` |
| `dimension` | `def (self) -> int` |
| `embed` | `async def (self, text: str) -> EmbeddingResult` |
| `embed_batch` | `async def (self, texts: list[str]) -> list[EmbeddingResult]` |

#### `CohereEmbedder(BaseEmbedder)`

Cohere Embed API.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, model: str, api_key: str) -> None` |
| `dimension` | `def (self) -> int` |
| `embed` | `async def (self, text: str) -> EmbeddingResult` |
| `embed_batch` | `async def (self, texts: list[str]) -> list[EmbeddingResult]` |
| `close` | `async def (self) -> None` |

### 函数

| 函数 | 签名 |
|------|------|
| `async get_embedder` | `async def (provider: str, **kwargs) -> BaseEmbedder` |
| `async cosine_similarity` | `async def (a: list[float], b: list[float]) -> float` |

---

## cache.llm_cache

AgentOS v0.40 LLM Cache — 语义缓存减少API调用成本。
支持：精确匹配缓存、语义相似度缓存、LRU淘汰、TTL过期。

### 类

#### `CacheEntry`

A cached LLM response with metadata.

Attributes:
    key: Cache lookup key (typically hash of prompt + model).
    value: Cached response content.
    tokens_saved: Tokens saved by serving from cache.
    cost_saved: Estimated cost saved.
    created_at: Unix timestamp of cache insertion.
    ttl: Time-to-live in seconds.
    hit_count: Number of cache hits.
    tags: Optional tags for cache invalidation.

| 方法 | 签名 |
|------|------|
| `expired` | `def (self) -> bool` |

#### `LRUCache`

LRU淘汰的内存缓存。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_size: int) -> None` |
| `get` | `def (self, key: str) -> Optional[CacheEntry]` |
| `put` | `def (self, key: str, entry: CacheEntry) -> None` |
| `invalidate` | `def (self, key: str | None, tag: str | None) -> None` |
| `size` | `def (self) -> int` |
| `clear` | `def (self) -> None` |

#### `SemanticCache`

语义缓存 — 基于embedding相似度的缓存匹配。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, similarity_threshold: float, embedder: Any) -> None` |
| `@staticmethod cosine_sim` | `def (a: list[float], b: list[float]) -> float` |
| `search` | `def (self, query: str) -> Optional[CacheEntry]` |
| `add` | `def (self, query: str, entry: CacheEntry) -> None` |
| `clear` | `def (self) -> None` |

#### `CacheStats`

缓存统计。

| 方法 | 签名 |
|------|------|
| `hit_rate` | `def (self) -> float` |

#### `LLMCache`

LLM响应缓存 — 减少API调用成本。

三层策略:
1. 精确匹配缓存 (LRU + TTL)
2. 语义相似度缓存
3. 透传 (无缓存命中)

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, lru_size: int, semantic_threshold: float, enable_semantic: bool) -> None` |
| `get` | `def (self, prompt: str, model: str, **kwargs) -> Optional[Any]` |
| `set` | `def (self, prompt: str, value: Any, model: str, tokens: int, cost: float, ttl: float, **` |
| `invalidate` | `def (self, key: str, tag: str) -> None` |
| `clear` | `def (self) -> None` |
| `snapshot` | `def (self) -> dict` |

---

## cache.response_cache

Response Cache with TTL — Cached LLM responses with configurable expiry.

Supports in-memory LRU cache with TTL, disk persistence, and cache key
strategies (exact match, semantic similarity, template-based).

### 类

#### `CacheKeyStrategy(Enum)`

Strategy for generating cache lookup keys.

#### `CacheEntry`

A single cache entry.

| 方法 | 签名 |
|------|------|
| `is_expired` | `def (self) -> bool` |
| `age_seconds` | `def (self) -> float` |

#### `CacheStats`

Cache performance statistics.

| 方法 | 签名 |
|------|------|
| `hit_rate` | `def (self) -> float` |
| `utilization` | `def (self) -> float` |

#### `ResponseCache`

Response cache with TTL and LRU eviction.

Supports:
- In-memory LRU cache with configurable TTL
- Multiple cache key strategies (exact, normalized, template)
- Statistics tracking (hit rate, evictions, expirations)
- Optional disk persistence (planned)

Example::

    cache = ResponseCache(max_entries=1000, default_ttl=3600)
    cache.put("What is 2+2?", "4")
    result = cache.get("What is 2+2?")  # "4" (cache hit)

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_entries: int, default_ttl: float, key_strategy: CacheKeyStrategy) -> None` |
| `get` | `def (self, prompt: str, **context) -> Optional[Any]` |
| `put` | `def (self, prompt: str, value: Any, ttl: Optional[float], **context) -> str` |
| `invalidate` | `def (self, prompt: str, **context) -> bool` |
| `clear` | `def (self) -> None` |
| `clear_expired` | `def (self) -> int` |
| `get_stats` | `def (self) -> CacheStats` |
| `get_entry` | `def (self, prompt: str, **context) -> Optional[CacheEntry]` |
| `size` | `def (self) -> int` |
| `is_full` | `def (self) -> bool` |

---

## validation.schema_enforcer

AgentOS v1.3.9 - Schema Enforcer 模块。

对 Agent 输出执行 Pydantic schema 校验，校验失败时自动修复/重试。
支持 JSON 修复、字段回退、LLM 辅助修正三种修复策略。

### 类

#### `FixStrategy(Enum)`

修复策略枚举。

#### `EnforcerResult`

校验执行结果。

#### `EnforcerConfig`

Schema Enforcer 配置。

#### `EnforcerStats`

校验统计。

#### `SchemaEnforcer`

对 Agent 输出执行 Pydantic schema 校验与自动修复。

核心流程：
1. 尝试直接 model_validate
2. 失败时按 strategy_order 依次尝试修复
3. 所有策略耗尽仍失败则降级为 FIELD_FALLBACK（最佳努力）

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: EnforcerConfig | None) -> None` |
| `enforce` | `async def (self, output: dict | str | Any, schema_model: type, context: dict | None) -> ` |
| `enforce_batch` | `async def (self, outputs: list[dict | str], schema_model: type, context: dict | None) ->` |

---

## workflows.engine

AgentOS v0.20 预设工作流模板。
开箱即用的 Agent 协作模式。

### 类

#### `WorkflowType(str, Enum)`

工作流类型枚举。

#### `WorkflowStep`

工作流步骤定义。

#### `Workflow`

预设工作流定义。

#### `WorkflowEngine`

工作流引擎 — 按预设步骤调度多个Agent协作。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, workflow: Workflow, agent_factory: Callable[[str], Any]) -> None` |
| `execute` | `async def (self, input_text: str, context: dict | None) -> str` |

---

## workflows.templates

Workflow Templates — Declarative, reusable multi-step agent workflows.

Define workflows as YAML/JSON templates with conditional branching,
parallel execution, retry policies, and human-in-the-loop checkpoints.

### 类

#### `StepType(Enum)`

步骤类型枚举。

#### `RetryPolicy(Enum)`

重试策略类。

#### `WorkflowStep`

Single step in a workflow template.

#### `WorkflowTemplate`

Declarative workflow template.

Example (YAML)::

    name: research_report
    description: Research a topic and generate a report
    steps:
      - name: research
        step_type: agent
        agent_type: researcher
        task_template: "Research: {{input.topic}}"
        output_key: research_result
      - name: review
        step_type: human_review
        review_prompt: "Review the research: {{research_result}}"
        depends_on: [research]
      - name: write_report
        step_type: agent
        agent_type: writer
        task_template: "Write report based on: {{research_result}}"
        depends_on: [review]
        output_key: final_report

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |
| `@classmethod from_dict` | `def (cls, data: dict[str, Any]) -> 'WorkflowTemplate'` |
| `to_yaml` | `def (self) -> str` |
| `to_json` | `def (self, indent: int) -> str` |
| `@classmethod from_yaml` | `def (cls, yaml_str: str) -> 'WorkflowTemplate'` |
| `@classmethod from_json` | `def (cls, json_str: str) -> 'WorkflowTemplate'` |
| `get_step` | `def (self, name: str) -> Optional[WorkflowStep]` |
| `flatten_steps` | `def (self) -> list[WorkflowStep]` |
| `step_count` | `def (self) -> int` |

---

## multimodal.manager

AgentOS v0.40 Multimodal — 多模态输入支持。
支持：图片理解、语音转文字、PDF/文档解析。

### 类

#### `Modality(str, Enum)`

模态类型枚举。

#### `MultimodalBlock`

多模态输入块 — 遵循OpenAI/Anthropic content block格式。

| 方法 | 签名 |
|------|------|
| `@classmethod text_block` | `def (cls, text: str) -> 'MultimodalBlock'` |
| `@classmethod image_url` | `def (cls, url: str, detail: str) -> 'MultimodalBlock'` |
| `@classmethod image_base64` | `def (cls, data: bytes, mime: str) -> 'MultimodalBlock'` |
| `@classmethod audio` | `def (cls, data: bytes, mime: str) -> 'MultimodalBlock'` |
| `to_openai_format` | `def (self) -> dict` |

#### `ImageProcessor`

图片处理器 — 压缩、格式转换、OCR预处理。

| 方法 | 签名 |
|------|------|
| `@staticmethod encode_file` | `def (path: str) -> tuple[str, str]` |
| `@staticmethod encode_bytes` | `def (data: bytes, mime: str) -> str` |
| `@staticmethod estimate_tokens` | `def (width: int, height: int, detail: str) -> int` |
| `@staticmethod purge_metadata` | `def (data: bytes) -> bytes` |

#### `AudioProcessor`

音频处理器 — 转文字、格式转换。

| 方法 | 签名 |
|------|------|
| `@staticmethod transcribe` | `def (path: str, whisper_model: str) -> str` |
| `@staticmethod encode_file` | `def (path: str) -> tuple[str, str]` |

#### `DocumentParser`

文档解析器 — PDF/Word/Markdown。

| 方法 | 签名 |
|------|------|
| `@staticmethod parse_pdf` | `def (path: str) -> str` |
| `@staticmethod parse_docx` | `def (path: str) -> str` |
| `@staticmethod parse_auto` | `def (path: str) -> tuple[str, str]` |

#### `MultimodalManager`

多模态管理器 — 统一入口。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `prepare_input` | `def (self, blocks: list[MultimodalBlock]) -> list[dict]` |
| `from_files` | `def (self, paths: list[str]) -> list[MultimodalBlock]` |
| `stats` | `def (self) -> dict` |

---

## api.middleware

AgentOS API middleware — request/response processing pipeline.

Provides authentication, CORS, request tracing, request-ID injection,
and rate-limiting middleware for the AgentOS API server.

### 类

#### `RequestContext`

请求上下文。

| 方法 | 签名 |
|------|------|
| `elapsed_ms` | `def (self) -> float` |

#### `RequestIDMiddleware`

Inject X-Request-ID into every request and propagate it.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, header: str) -> None` |
| `process_request` | `def (self, headers: dict) -> RequestContext` |

#### `CORSConfig`

CORS 配置。

#### `CORSMiddleware`

Add CORS headers to every response.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[CORSConfig]) -> None` |
| `apply` | `def (self, response_headers: dict) -> dict` |

#### `AuthConfig`

认证配置。

#### `AuthMiddleware`

Simple API-key authentication middleware.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[AuthConfig]) -> None` |
| `authenticate` | `def (self, headers: dict) -> tuple[bool, str]` |

#### `RequestLogMiddleware`

Log every request with method, path, status, and elapsed time.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, logger: Optional[Callable[[str], None]]) -> None` |
| `log` | `def (self, ctx: RequestContext, status: int) -> str` |

#### `MiddlewareStack`

Ordered middleware pipeline for the AgentOS API.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, cors: Optional[CORSMiddleware], auth: Optional[AuthMiddleware], req_log: Opti` |

---

## api.server

AgentOS v0.30 FastAPI REST服务 — 暴露Agent能力。

### 类

#### `RunRequest(BaseModel)`

Agent 运行请求体。

#### `RunResponse(BaseModel)`

Agent 运行响应体。

#### `AgentAPI`

AgentOS REST API 服务。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, loop: AgentLoop) -> None` |
| `serve` | `def (self, host: str, port: int) -> None` |

---

## api.sse

SSE (Server-Sent Events) Streaming — production-grade async streaming endpoint.

Provides an ASGI-compatible SSE stream with automatic reconnection,
client heartbeat, backpressure control, and typed event dispatching.

### 类

#### `SSEEventType(str, Enum)`

Standard SSE event types plus AgentOS extensions.

#### `SSEEvent`

A single SSE event to be serialized to the wire.

| 方法 | 签名 |
|------|------|
| `serialize` | `def (self) -> str` |
| `@classmethod token` | `def (cls, text: str, seq: int) -> 'SSEEvent'` |
| `@classmethod tool_call` | `def (cls, name: str, args: dict) -> 'SSEEvent'` |
| `@classmethod tool_result` | `def (cls, name: str, result: Any) -> 'SSEEvent'` |
| `@classmethod error` | `def (cls, message: str, code: str) -> 'SSEEvent'` |
| `@classmethod done` | `def (cls, metadata: dict[str, Any] | None) -> 'SSEEvent'` |
| `@classmethod metadata` | `def (cls, meta: dict[str, Any]) -> 'SSEEvent'` |

#### `SSEStream`

SSE stream with heartbeats and backpressure handling.

Usage::

    stream = SSEStream(retry_ms=3000)
    # Producer
    await stream.queue.put(SSEEvent.token("Hello"))
    await stream.queue.put(SSEEvent.done())
    await stream.close()

    # Consumer (ASGI)
    async for chunk in stream.iter_chunks():
        yield chunk

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, retry_ms: int, heartbeat_s: float, max_queue: int) -> None` |
| `start` | `async def (self) -> None` |
| `send` | `async def (self, event: SSEEvent) -> None` |
| `close` | `async def (self) -> None` |
| `iter_events` | `async def (self) -> AsyncIterator[SSEEvent]` |
| `iter_chunks` | `async def (self) -> AsyncIterator[str]` |

#### `SSEResponse`

Factory for generating ASGI-compatible SSE HTTP responses.

Usage (Starlette / FastAPI)::

    from starlette.responses import StreamingResponse

    sse = SSEResponse(stream)
    return StreamingResponse(
        sse.body(),
        media_type="text/event-stream",
        headers=sse.headers(),
    )

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, stream: SSEStream) -> None` |
| `headers` | `def (self) -> dict[str, str]` |
| `body` | `async def (self) -> AsyncIterator[str]` |

---

## api.streaming

Streaming SSE (Server-Sent Events) endpoint for agent interactions.

Provides real-time streaming of agent outputs via HTTP SSE, enabling
browser-based chat UIs and real-time monitoring dashboards.

### 类

#### `StreamEvent`

Single SSE event emitted by the stream.

| 方法 | 签名 |
|------|------|
| `to_sse` | `def (self) -> str` |

#### `StreamSession`

Track an active streaming session.

#### `StreamingAgent`

Agent that emits Server-Sent Events for real-time streaming.

Example (FastAPI integration)::

    streaming = StreamingAgent(agent_loop)

    @app.get("/agent/stream")
    async def stream():
        return StreamingResponse(
            streaming.stream_chat("What is quantum computing?", "session-1"),
            media_type="text/event-stream"
        )

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, agent_loop: Any, heartbeat_interval: float) -> None` |
| `stream_chat` | `async def (self, message: str, session_id: str) -> AsyncIterator[str]` |
| `stream_chat_sync` | `def (self, message: str, session_id: str) -> None` |
| `emit_tool_call` | `def (self, session_id: str, tool_name: str, args: dict) -> str` |
| `emit_tool_result` | `def (self, session_id: str, tool_name: str, result: Any) -> str` |
| `emit_error` | `def (self, session_id: str, error: str) -> str` |
| `get_session` | `def (self, session_id: str) -> Optional[StreamSession]` |
| `list_sessions` | `def (self) -> dict[str, StreamSession]` |

---

## api.versioning

AgentOS API version negotiation.

Supports header-based and URL-path-based versioning for the AgentOS REST API.

### 类

#### `VersionStrategy(Enum)`

版本策略枚举。

#### `APIVersion`

API 版本记录。

| 方法 | 签名 |
|------|------|
| `__str__` | `def (self) -> str` |
| `@classmethod parse` | `def (cls, raw: str) -> APIVersion` |

#### `VersionConfig`

版本管理配置。

#### `VersionNegotiator`

Negotiate and validate API version from incoming requests.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[VersionConfig]) -> None` |
| `extract_from_headers` | `def (self, headers: dict) -> Optional[APIVersion]` |
| `extract_from_path` | `def (self, path: str) -> Optional[APIVersion]` |
| `extract_from_query` | `def (self, query: str) -> Optional[APIVersion]` |
| `negotiate` | `def (self, headers: dict, path: str, query: str) -> tuple[APIVersion, list[str]]` |

---

## api.websocket

WebSocket 双向流式通信 — Agent 实时交互层。

基于 websockets 库，提供 Agent 与客户端之间的全双工实时通信。
支持流式进度报告、Agent 状态广播、父子 Agent 监控、暂停/恢复/取消。

协议（JSON，双向）:

    Client → Server:
        {"type": "run",      "task": "...", "session_id": "..."}
        {"type": "cancel",   "session_id": "..."}
        {"type": "pause",    "session_id": "..."}
        {"type": "resume",   "session_id": "..."}
        {"type": "ping"}

    Server → Client:
        {"type": "token",        "text": "...", "seq": N}
        {"type": "progress",     "value": 0.5, "step": "..."}
        {"type": "tool_call",    "name": "...", "args": {...}}
        {"type": "tool_result",  "name": "...", "result": ...}
        {"type": "status",       "status": "running"|"paused"|"..."}
        {"type": "done",         "output": "...", "iterations": N}
        {"type": "error",        "message": "..."}
        {"type": "heartbeat"}
        {"type": "child_update", "agent_id": "...", "status": "..."}

使用示例::

    from agentos.api.websocket import AgentWebSocket, serve_ws

    mgr = SubAgentManager()

    async def my_run(spec, ctx):
        await ctx.report_progress(0.5, "thinking")
        return "answer", 1

    ws = AgentWebSocket(manager=mgr, run_func=my_run)
    await serve_ws(ws.handler, port=8765)

### 类

#### `WSMsgType(str, Enum)`

WebSocket 消息类型。

#### `WSMessage`

WebSocket 消息体。

| 方法 | 签名 |
|------|------|
| `@classmethod parse` | `def (cls, raw: str | bytes) -> 'WSMessage'` |
| `serialize` | `def (self) -> str` |
| `@classmethod token` | `def (cls, text: str, seq: int) -> 'WSMessage'` |
| `@classmethod progress` | `def (cls, value: float, step: str, agent_id: str) -> 'WSMessage'` |
| `@classmethod tool_call` | `def (cls, name: str, args: dict) -> 'WSMessage'` |
| `@classmethod tool_result` | `def (cls, name: str, result: Any) -> 'WSMessage'` |
| `@classmethod status` | `def (cls, status: str, agent_id: str) -> 'WSMessage'` |
| `@classmethod done` | `def (cls, output: str, iterations: int, agent_id: str) -> 'WSMessage'` |
| `@classmethod error` | `def (cls, message: str, code: str) -> 'WSMessage'` |
| `@classmethod heartbeat` | `def (cls) -> 'WSMessage'` |
| `@classmethod child_update` | `def (cls, agent_id: str, status: str, progress: float, step: str) -> 'WSMessage'` |

#### `WSSession`

单个 WebSocket 连接的会话。

| 方法 | 签名 |
|------|------|
| `is_busy` | `def (self) -> bool` |
| `touch` | `def (self) -> None` |

#### `AgentWebSocket`

Agent WebSocket 服务。

Args:
    manager: SubAgentManager 实例
    run_func: 自定义执行函数 (spec, ctx) -> (output, iterations)
    heartbeat_interval: WebSocket 心跳间隔（秒）
    poll_interval: 子 Agent 状态轮询间隔（秒）
    max_message_size: 最大消息大小（字节）

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, manager: SubAgentManager | None, run_func: Callable[[SubAgentSpec, ChildConte` |
| `handler` | `async def (self, websocket: WebSocketServerProtocol) -> None` |
| `broadcast` | `async def (self, msg: WSMessage, exclude_session: str) -> None` |
| `broadcast_to_session` | `async def (self, session: WSSession, msg: WSMessage) -> None` |
| `broadcast_child_status` | `async def (self) -> None` |
| `manager` | `def (self) -> SubAgentManager` |
| `active_connections` | `def (self) -> int` |
| `active_sessions` | `def (self) -> int` |

### 函数

| 函数 | 签名 |
|------|------|
| `async serve_ws` | `async def (ws_handler, host: str, port: int, **kwargs) -> None` |

---

## plugins.discovery

Plugin Discovery — entry_points based plugin auto-discovery for AgentOS.

Scans installed packages for entry_points registered under the
'agentos.plugins' group and loads them without manual registration.

### 类

#### `PluginProtocol(Protocol)`

Minimal protocol that discovered plugins must satisfy.

| 方法 | 签名 |
|------|------|
| `initialize` | `def (self) -> None` |
| `shutdown` | `def (self) -> None` |

#### `DiscoveredPlugin`

Represents a plugin discovered via entry_points.

| 方法 | 签名 |
|------|------|
| `is_loaded` | `def (self) -> bool` |

#### `DiscoveryResult`

Result of a plugin discovery scan.

#### `PluginDiscovery`

Scans installed packages for AgentOS plugins via entry_points.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, groups: Optional[List[str]]) -> None` |
| `discovered` | `def (self) -> Dict[str, DiscoveredPlugin]` |
| `groups` | `def (self) -> List[str]` |
| `register_loader` | `def (self, group: str, loader: Callable) -> None` |
| `scan` | `def (self, groups: Optional[List[str]]) -> DiscoveryResult` |
| `load_plugin` | `def (self, name: str, group: str) -> Optional[DiscoveredPlugin]` |
| `load_all` | `def (self, group: Optional[str]) -> Dict[str, DiscoveredPlugin]` |
| `get_by_package` | `def (self, package_name: str) -> List[DiscoveredPlugin]` |
| `get_by_group` | `def (self, group: str) -> List[DiscoveredPlugin]` |
| `summary` | `def (self) -> Dict[str, Any]` |
| `clear` | `def (self) -> None` |

---

## plugins.lifecycle

AgentOS v0.70 — 插件生命周期管理器。
基因来源: Kubernetes Pod Lifecycle + Spring Boot Actuator

生命周期钩子:
- on_load()       → 插件加载完成
- on_init(config) → 初始化配置
- on_start()      → 开始工作
- on_stop()       → 优雅关闭
- on_error(e)     → 异常处理
- health_check()  → 健康检查

### 类

#### `LifecyclePlugin(ABC)`

插件基类 — 实现标准生命周期钩子。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: dict | None) -> None` |
| `uptime_seconds` | `def (self) -> float` |
| `on_load` | `async def (self) -> None` |
| `on_init` | `async def (self, config: dict) -> None` |
| `on_start` | `async def (self) -> None` |
| `on_stop` | `async def (self) -> None` |
| `on_error` | `async def (self, error: Exception) -> bool` |
| `health_check` | `async def (self) -> HealthStatus` |

#### `PluginHealth`

插件健康状态摘要。

#### `HealthStatus`

插件健康状态。

| 方法 | 签名 |
|------|------|
| `is_healthy` | `def (self) -> bool` |
| `to_dict` | `def (self) -> dict` |

#### `LifecycleReport`

插件生命周期报告。

#### `LifecycleManager`

生命周期管理器 — 协调所有插件的init/start/stop。
支持: 批量初始化、健康检查轮询、优雅降级。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, registry: PluginRegistry) -> None` |
| `init_all` | `async def (self, configs: dict[str, dict] | None) -> None` |
| `start_all` | `async def (self) -> None` |
| `start_one` | `async def (self, name: str) -> LifecycleReport` |
| `stop_all` | `async def (self, graceful: bool) -> None` |
| `stop_one` | `async def (self, name: str, graceful: bool) -> None` |
| `health_check_all` | `async def (self) -> dict[str, HealthStatus]` |
| `start_health_polling` | `def (self, interval_seconds: float) -> None` |
| `stop_health_polling` | `def (self) -> None` |
| `report` | `def (self) -> list[LifecycleReport]` |
| `summary` | `def (self) -> str` |

---

## plugins.loader

AgentOS v0.70 — 插件发现与加载器。
基因来源: Python entry_points + Docker plugin discovery

加载策略:
1. 入口点扫描 (entry_points.txt / pyproject.toml)
2. 目录扫描 (plugins/ 下的 manifest.json)
3. 环境变量指定 (AGENTOS_PLUGINS)

### 类

#### `PluginLoadError(Exception)`

插件加载错误。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, plugin_name, reason) -> None` |

#### `PluginLoader`

插件加载器 — 发现、验证、实例化、热加载。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, registry: PluginRegistry | None, search_dirs: list[str] | None) -> None` |
| `discover` | `def (self) -> list[PluginManifest]` |
| `load_all` | `def (self, manifests: list[PluginManifest] | None, auto_start: bool) -> PluginRegistry` |
| `load_one` | `def (self, manifest: PluginManifest, auto_start: bool) -> RegisteredPlugin` |
| `hot_reload` | `def (self, name: str) -> RegisteredPlugin` |

---

## plugins.registry

AgentOS v0.70 — 插件系统: 注册中心。
基因来源: Docker插件体系 + VSCode扩展市场

插件清单格式:
- manifest.json: 插件元数据
- 入口点: Python类路径
- 依赖声明: 插件间依赖

### 类

#### `PluginType(str, Enum)`

插件类型枚举。

#### `PluginStatus(str, Enum)`

插件状态。

#### `PluginManifest`

插件清单 — 描述插件能力与依赖。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |

#### `RegisteredPlugin`

已注册的插件实例。

#### `PluginRegistry`

插件注册中心 — 统一管理所有已注册插件。
支持: CRUD、查询、按标签/类型检索、依赖解析。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `register` | `def (self, manifest: PluginManifest, instance: Any) -> RegisteredPlugin` |
| `unregister` | `def (self, name: str) -> bool` |
| `get` | `def (self, name: str) -> RegisteredPlugin | None` |
| `get_instance` | `def (self, name: str) -> Any` |
| `list_all` | `def (self) -> list[RegisteredPlugin]` |
| `list_names` | `def (self) -> list[str]` |
| `by_type` | `def (self, plugin_type: PluginType) -> list[RegisteredPlugin]` |
| `by_tag` | `def (self, tag: str) -> list[RegisteredPlugin]` |
| `by_status` | `def (self, status: PluginStatus) -> list[RegisteredPlugin]` |
| `resolve_order` | `def (self, names: list[str]) -> list[str]` |
| `check_requirements` | `def (self, name: str) -> list[str]` |
| `register_hook` | `def (self, event: str, callback: Callable) -> None` |
| `emit_hook` | `async def (self, event: str, **kwargs) -> list[Any]` |
| `hook_names` | `def (self) -> list[str]` |
| `count` | `def (self) -> int` |
| `summary` | `def (self) -> str` |

#### `DependencyCycleError(Exception)`

插件依赖循环异常。

---

## agents.market

AgentOS v0.30 Agent技能市场 — 可复用的Agent技能模板。
预置24个专业Agent技能。

### 类

#### `AgentCategory(str, Enum)`

Agent 分类。

#### `AgentSkill`

Agent 技能定义。

#### `AgentMarket`

v0.30 Agent技能市场 — 24个预置技能。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `skills` | `def (self) -> dict[str, AgentSkill]` |
| `get` | `def (self, name: str) -> AgentSkill | None` |
| `list_by_category` | `def (self, category: AgentCategory) -> list[AgentSkill]` |
| `search` | `def (self, query: str) -> list[AgentSkill]` |
| `register` | `def (self, skill: AgentSkill) -> None` |
| `stats` | `def (self) -> dict` |

---

## testing.fixtures

AgentOS v0.95 Testing Fixtures — 可复用测试基础设施。

提供 mock 对象工厂、预设配置 fixtures、临时文件上下文，
供单元测试和集成测试共用。

### 类

#### `MockLLMResponse`

Mock LLM 响应。

#### `MockLLMClient`

可配置的 Mock LLM 客户端，支持预设响应序列和工具调用。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, responses: Optional[List[MockLLMResponse]]) -> None` |
| `chat` | `async def (self, messages: List[Dict], **kwargs) -> MockLLMResponse` |
| `reset` | `def (self) -> None` |

### 函数

| 函数 | 签名 |
|------|------|
| `mock_openai_client` | `def () -> None` |
| `mock_model_response` | `def (content: str, model: str) -> None` |
| `sample_config` | `def (overrides: Optional[Dict]) -> Dict[str, Any]` |
| `sample_loop_config` | `def (overrides: Optional[Dict]) -> Dict[str, Any]` |
| `temp_workspace` | `def (suffix: str) -> None` |
| `mock_memory_store` | `def () -> None` |
| `sample_agent_state` | `def (state: str, context: Optional[Dict]) -> None` |
| `sample_audit_report` | `def () -> None` |
| `sample_health_status` | `def (healthy: bool) -> None` |
| `sample_docker_config` | `def () -> None` |
| `sample_middleware_stack` | `def () -> None` |
| `sample_alert_config` | `def () -> None` |

---

## experiments.runner

AgentOS v0.40 Experiments — A/B测试与Prompt实验框架。
支持：Prompt变体对比、A/B/n测试、结果统计显著性分析、实验报告生成。

### 类

#### `PromptVariant`

Prompt变体。

#### `TrialResult`

单次试验结果。

#### `ExperimentConfig`

实验配置。

#### `ExperimentReport`

实验报告。

#### `Evaluator`

评估器 — 自动评分模型输出。

| 方法 | 签名 |
|------|------|
| `@staticmethod llm_judge` | `def (output: str, expected: str, criteria: str) -> float` |
| `@staticmethod exact_match` | `def (output: str, expected: str) -> float` |
| `@staticmethod contains_all` | `def (output: str, keywords: list[str]) -> float` |

#### `ExperimentRunner`

实验执行器。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, router, cache) -> None` |
| `run` | `async def (self, config: ExperimentConfig) -> ExperimentReport` |
| `get_report` | `def (self, report_id: str) -> Optional[ExperimentReport]` |
| `list_reports` | `def (self) -> list[dict]` |
| `generate_markdown_report` | `def (self, report: ExperimentReport) -> str` |

---

## models.resilience

AgentOS v1.1.5 Resilience — 韧性层。
Retry with jitter + Circuit Breaker + Timeout + Fallback chain + Cancellation-aware retry。

### 类

#### `CircuitState(str, Enum)`

熔断器状态枚举。

#### `CircuitBreakerConfig`

熔断器配置。

#### `CircuitBreakerStats`

熔断器运行统计。

#### `CircuitBreaker`

熔断器：检测连续失败，自动熔断/恢复。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, name: str, config: CircuitBreakerConfig | None) -> None` |
| `call` | `async def (self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T` |
| `stats` | `def (self) -> CircuitBreakerStats` |
| `reset` | `def (self) -> None` |

#### `CircuitBreakerOpenError(Exception)`

熔断器打开异常。

#### `RetryConfig`

重试策略配置。

#### `CancellationSource(str, Enum)`

取消来源，区分用户主动取消与系统取消。

#### `CancelledError(Exception)`

带取消来源的取消异常。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, message: str, source: CancellationSource) -> None` |

#### `RetryExhaustedError(Exception)`

重试耗尽异常。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, attempts: int, last_error: Exception) -> None` |

#### `TimeoutError(Exception)`

超时异常。

#### `FallbackExhaustedError(Exception)`

回退耗尽异常。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, errors: list[Exception]) -> None` |

#### `ResilienceConfig`

弹性总配置。

#### `ResilientCall`

组合韧性调用器：重试 + 熔断 + 超时 + 降级。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: ResilienceConfig | None) -> None` |
| `call` | `async def (self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T` |

### 函数

| 函数 | 签名 |
|------|------|
| `async retry_with_backoff` | `async def (fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T` |
| `async with_timeout` | `async def (fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T` |
| `async with_fallback` | `async def (primary: Callable[..., Awaitable[T]], fallbacks: list[Callable[..., Awaitable` |

---

## models.router

AgentOS v1.2.7 — Minimal ModelRouter for CodeAgent.

Lightweight LLM call wrapper using httpx to OpenAI-compatible endpoints.
Designed as a self-contained module with zero internal dependencies.

### 类

#### `ModelResponse`

LLM 响应：文本内容 + 函数调用列表。

| 方法 | 签名 |
|------|------|
| `has_tool_calls` | `def (self) -> bool` |

#### `ModelSpec`

单个模型的规格定义。

#### `AllModelsFailed(Exception)`

所有模型均失败异常。

#### `ModelConfig`

模型路由配置。

#### `ModelRouter`

Minimal LLM router for code generation tasks.

| 方法 | 签名 |
|------|------|
| `chat` | `async def (self, model: str, messages: list[dict[str, Any]], temperature: float, max_tok` |

---

## models.routing_strategy

智能路由策略 — 按任务复杂度自动选择模型。

### 类

#### `Complexity(str, Enum)`

复杂度评估结果。

#### `Budget(str, Enum)`

成本预算配置。

#### `RoutingStrategy`

根据任务描述自动决定使用哪个模型。

| 方法 | 签名 |
|------|------|
| `@staticmethod assess_complexity` | `def (task: str) -> Complexity` |
| `@staticmethod assess_budget` | `def (task: str) -> Budget` |
| `@classmethod route` | `def (cls, task: str, budget: Budget | None) -> str` |

---

## models.backends.anthropic

Anthropic Claude backend for AgentOS.

Supports Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku.
Uses Anthropic Messages API.

### 类

#### `ClaudeConfig`

Configuration for Anthropic Claude backend.

#### `ClaudeClient`

Anthropic Claude LLM client.

Supports:
- Claude Opus 4 / Claude Sonnet 4 / Claude Haiku 3.5
- Streaming and non-streaming
- Tool use (function calling)
- System prompts

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[ClaudeConfig]) -> None` |
| `chat` | `async def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Dic` |
| `chat_stream` | `async def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Asy` |
| `sync_chat` | `def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Dict[str,` |

---

## models.backends.gemini

AgentOS v0.70 — Google Gemini Provider 全集成。
基因来源: Google AI Studio SDK + Vertex AI
支持: Gemini 2.5 Pro/Flash、Vision、System Instruction、Streaming、Token Counting、Safety Settings。

### 类

#### `GeminiSafetySetting`

安全过滤配置。

#### `GeminiConfig`

Gemini调用配置。

#### `GeminiClient`

Google Gemini API 客户端。
支持: chat/completions、Vision多模态、Streaming、System Instruction。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: GeminiConfig | None, http_client: httpx.AsyncClient | None) -> None` |
| `api_key` | `def (self) -> str` |
| `close` | `async def (self) -> None` |
| `call` | `async def (self, spec: ModelSpec, context: AgentContext) -> ModelResponse` |
| `call_stream` | `async def (self, spec: ModelSpec, context: AgentContext) -> AsyncIterator[dict]` |
| `call_with_image` | `async def (self, spec: ModelSpec, prompt: str, image_data: bytes, mime_type: str) -> Mod` |
| `count_tokens` | `async def (self, spec: ModelSpec, context: AgentContext) -> dict` |

---

## models.backends.ollama

Ollama backend for AgentOS.

Supports local LLM inference via Ollama.
Models: llama3, mistral, codellama, phi3, gemma2, deepseek-r1, etc.

### 类

#### `OllamaConfig`

Configuration for Ollama backend.

#### `OllamaClient`

Ollama LLM client for local model inference.

Supports:
- Chat completions (streaming and non-streaming)
- Tool calling (function calling)
- Model listing and management
- Custom system prompts

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[OllamaConfig]) -> None` |
| `chat` | `async def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Dic` |
| `chat_stream` | `async def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Asy` |
| `sync_chat` | `def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Dict[str,` |
| `list_models` | `async def (self) -> List[Dict[str, Any]]` |
| `pull_model` | `async def (self, model_name: str) -> AsyncIterator[Dict[str, Any]]` |

---

## models.backends.openai

OpenAI backend for AgentOS.

Supports OpenAI, Azure OpenAI, and any OpenAI-compatible API (DeepSeek, Groq, etc.).

### 类

#### `OpenAIConfig`

Configuration for OpenAI backend.

#### `OpenAIClient`

OpenAI-compatible LLM client.

Works with:
- OpenAI (GPT-4o, GPT-4, GPT-3.5)
- Azure OpenAI
- DeepSeek
- Groq
- Together AI
- Any OpenAI-compatible endpoint

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[OpenAIConfig]) -> None` |
| `headers` | `def (self) -> Dict[str, str]` |
| `chat` | `async def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Dic` |
| `chat_stream` | `async def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Asy` |
| `sync_chat` | `def (self, messages: List[Dict[str, str]], system: Optional[str], **kwargs) -> Dict[str,` |

---

## evolution.engine

Evolution Engine for NexusAgent.

Approval-based self-evolution system. Agents can propose
improvements, but changes require human approval before
being applied.

### 类

#### `EvolutionStatus(str, Enum)`

Status of an evolution proposal.

#### `EvolutionProposal`

A proposed evolution/improvement.

Attributes:
    id: Unique identifier
    agent_name: Name of agent to evolve
    change_type: Type of change (prompt/tools/params)
    description: Human-readable description
    old_value: Current value
    new_value: Proposed new value
    status: Approval status
    created_at: Creation timestamp
    approved_at: Approval timestamp
    approved_by: Who approved
    applied_at: Application timestamp
    metadata: Additional metadata

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `EvolutionEngine`

Approval-based self-evolution engine.

Manages the lifecycle of evolution proposals:
1. Agent proposes improvement
2. Human reviews and approves/rejects
3. Approved changes are applied

Usage:
    engine = EvolutionEngine()

    # Agent proposes improvement
    proposal = engine.propose(
        agent_name="SupportAgent",
        change_type="prompt",
        description="Improve greeting",
        old_value="Hello!",
        new_value="Hi there! How can I help?",
    )

    # Human approves
    engine.approve(proposal.id, approved_by="human")

    # Apply changes
    engine.apply(proposal.id)

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `propose` | `def (self, agent_name: str, change_type: str, description: str, old_value: Any, new_valu` |
| `get_proposal` | `def (self, proposal_id: str) -> Optional[EvolutionProposal]` |
| `list_proposals` | `def (self, status: Optional[EvolutionStatus], agent_name: Optional[str]) -> list[Evoluti` |
| `approve` | `def (self, proposal_id: str, approved_by: str) -> bool` |
| `reject` | `def (self, proposal_id: str, reason: str) -> bool` |
| `apply` | `def (self, proposal_id: str) -> bool` |
| `register_approver` | `def (self, agent_name: str, approver: Callable[[EvolutionProposal], bool]) -> None` |
| `auto_approve` | `def (self, proposal_id: str) -> bool` |
| `get_stats` | `def (self) -> dict[str, Any]` |

---

## agent.tool_agent

Tool-Using Agent — 基于 LLM Function Calling 的自主 Agent 循环。

核心模式:
    用户任务 → LLM 推理(tool_calls) → 工具执行 → 结果回传 → 循环直到完成

v1.3.38: +streaming, retry, checkpoint/resume, tool error handling, mock provider.

### 类

#### `AgentConfig`

#### `AgentStep`

#### `AgentResult`

#### `ToolExecutor`

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `register` | `def (self, tool: Tool, handler: Callable[..., str]) -> None` |
| `get_schemas` | `def (self) -> list[Tool]` |
| `execute` | `def (self, tool_call: ToolCall) -> str` |

#### `MockLLMProvider(LLMProvider)`

可编程响应的 Mock Provider，供集成测试使用。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, responses: list[dict]) -> None` |
| `chat` | `def (self, messages, **kwargs) -> None` |
| `achat` | `async def (self, *args, **kwargs) -> None` |
| `provider_name` | `def (self) -> str` |
| `@staticmethod text_response` | `def (content: str, finish_reason: str) -> dict` |
| `@staticmethod tool_response` | `def (name: str, arguments: dict, tool_call_id: str) -> dict` |

#### `ToolAgent`

基于 LLM Function Calling 的自主 Agent。

用法:
    from agentos.agent import ToolAgent, ToolExecutor
    from agentos.llm import create_provider, Tool

    provider = create_provider("openai")
    executor = ToolExecutor()
    executor.register(
        Tool.from_function("get_weather", "获取天气", {"city": ...}),
        lambda city: f"{city}: 22°C sunny"
    )
    agent = ToolAgent(provider, executor)
    result = agent.run("北京天气怎么样？")
    print(result.final_answer)

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, provider: LLMProvider, tool_executor: ToolExecutor) -> None` |
| `run` | `def (self, task: str) -> AgentResult` |
| `run_stream` | `def (self, task: str) -> Generator[AgentStep, None, AgentResult]` |
| `arun` | `async def (self, task: str) -> AgentResult` |
| `resume` | `def (self) -> AgentResult` |

---

## agent.examples.weather_agent

Tool-Using Agent 端到端示例: 天气助手 Agent。

演示:
    - 定义工具(get_weather, get_stock_price)
    - 注册到 ToolExecutor
    - ToolAgent 多步推理
    - 成本追踪

运行:
    python agentos/agent/examples/weather_agent.py

### 函数

| 函数 | 签名 |
|------|------|
| `get_weather` | `def (city: str) -> str` |
| `get_stock_price` | `def (symbol: str) -> str` |
| `main` | `def () -> None` |

---

## agent.tests.test_integration

ToolAgent 集成测试 — 使用 MockLLMProvider 测试完整 Agent 流程。

### 类

#### `TestIntegrationFullFlow`

完整 Agent 流程集成测试。

| 方法 | 签名 |
|------|------|
| `test_single_call_no_tools` | `def (self) -> None` |
| `test_single_tool_call_then_answer` | `def (self) -> None` |
| `test_two_tool_calls` | `def (self) -> None` |
| `test_max_steps_exceeds` | `def (self) -> None` |
| `test_tool_execution_error_stops` | `def (self) -> None` |
| `test_tool_error_continues` | `def (self) -> None` |
| `test_streaming_yields_steps` | `def (self) -> None` |
| `test_multiple_tools_registered` | `def (self) -> None` |

#### `TestCheckpointResume`

Checkpoint / Resume 集成测试。

| 方法 | 签名 |
|------|------|
| `test_checkpoint_saved_and_resumed` | `def (self) -> None` |
| `test_resume_no_checkpoint_raises` | `def (self) -> None` |
| `test_resume_no_checkpoint_dir_raises` | `def (self) -> None` |

#### `TestRetry`

重试逻辑集成测试。

| 方法 | 签名 |
|------|------|
| `test_failing_provider_triggers_retry` | `def (self) -> None` |
| `test_all_retries_exhausted` | `def (self) -> None` |

#### `TestAgentResult`

AgentResult 统计正确性。

| 方法 | 签名 |
|------|------|
| `test_statistics_accumulate` | `def (self) -> None` |

---

## agent.tests.test_tool_agent

agentos/agent/tool_agent.py 单元测试。

### 类

#### `TestToolExecutor`

| 方法 | 签名 |
|------|------|
| `test_register_and_list_schemas` | `def (self) -> None` |
| `test_execute_success` | `def (self) -> None` |
| `test_execute_unknown_tool` | `def (self) -> None` |
| `test_execute_error` | `def (self) -> None` |
| `test_multiple_register` | `def (self) -> None` |

#### `TestAgentConfig`

| 方法 | 签名 |
|------|------|
| `test_defaults` | `def (self) -> None` |
| `test_custom` | `def (self) -> None` |

#### `TestAgentStep`

| 方法 | 签名 |
|------|------|
| `test_empty_step` | `def (self) -> None` |
| `test_full_step` | `def (self) -> None` |

#### `TestAgentResult`

| 方法 | 签名 |
|------|------|
| `test_success_result` | `def (self) -> None` |
| `test_failure_result` | `def (self) -> None` |

---

## errors.handler

v0.80 — 用户友好错误处理：分类 + 格式化 + 建议。

### 类

#### `ErrorCategory(Enum)`

错误分类枚举。

#### `ErrorContext`

错误上下文信息。

#### `HumanError(Exception)`

包装原始异常，附带用户友好的上下文。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, original: Exception, context: ErrorContext) -> None` |
| `__str__` | `def (self) -> str` |

#### `ErrorFormatter`

将 Python 异常转换为用户友好的格式化输出。

| 方法 | 签名 |
|------|------|
| `@staticmethod categorize` | `def (exc: Exception) -> ErrorCategory` |
| `@staticmethod extract_recovery` | `def (original: Exception, category: ErrorCategory) -> list[str]` |
| `@classmethod format` | `def (cls, exc: Exception, trace_id: str) -> ErrorContext` |

### 函数

| 函数 | 签名 |
|------|------|
| `format_error` | `def (exc: Exception, trace_id: str) -> str` |
| `friendly_error` | `def (func) -> None` |

---

## comm.layer

Communication Layer for NexusAgent.

Provides multiple communication patterns for multi-agent systems:
- Blackboard: Shared memory space
- EventBus: Publish-subscribe events
- Mailbox: Direct point-to-point messaging

### 类

#### `Message`

Communication message.

Attributes:
    id: Unique identifier
    sender: Sender name
    receiver: Receiver name
    content: Message content
    metadata: Additional metadata
    timestamp: Message timestamp

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `Blackboard`

Shared memory space for agents.

Agents can read/write to a shared blackboard.
Useful for collaborative problem solving.

Usage:
    blackboard = Blackboard()
    blackboard.write("agent1", "status", "working")
    status = blackboard.read("agent1", "status")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `write` | `def (self, agent_name: str, key: str, value: Any) -> None` |
| `read` | `def (self, agent_name: str, key: str, default: Any) -> Any` |
| `read_all` | `def (self, key: str) -> dict[str, Any]` |
| `get_agent_data` | `def (self, agent_name: str) -> dict[str, Any]` |
| `get_history` | `def (self, agent_name: Optional[str], limit: int) -> list[dict[str, Any]]` |
| `clear` | `def (self, agent_name: Optional[str]) -> None` |

#### `EventBus`

Publish-subscribe event system.

Agents can subscribe to events and publish events.
Useful for event-driven architectures.

Usage:
    bus = EventBus()

    # Subscribe
    bus.subscribe("task_completed", callback)

    # Publish
    bus.publish("task_completed", {"task_id": "123"})

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `subscribe` | `def (self, event_type: str, callback: Callable[[Any], None]) -> None` |
| `unsubscribe` | `def (self, event_type: str, callback: Callable[[Any], None]) -> bool` |
| `publish` | `def (self, event_type: str, data: Any, sender: str) -> int` |
| `publish_async` | `async def (self, event_type: str, data: Any, sender: str) -> int` |
| `get_history` | `def (self, event_type: Optional[str], limit: int) -> list[dict[str, Any]]` |
| `clear` | `def (self) -> None` |

#### `Mailbox`

Point-to-point messaging system.

Agents have mailboxes and can send/receive messages.
Useful for direct communication.

Usage:
    mailbox = Mailbox()
    mailbox.send("agent1", "agent2", "Hello")
    messages = mailbox.receive("agent2")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `send` | `def (self, sender: str, receiver: str, content: Any, **metadata) -> Message` |
| `receive` | `def (self, receiver: str, limit: int) -> list[Message]` |
| `receive_and_clear` | `def (self, receiver: str, limit: int) -> list[Message]` |
| `get_sent` | `def (self, sender: Optional[str], limit: int) -> list[Message]` |
| `clear` | `def (self, receiver: Optional[str]) -> None` |

#### `CommunicationLayer`

Unified communication layer.

Combines Blackboard, EventBus, and Mailbox into
a single interface.

Usage:
    comm = CommunicationLayer()

    # Use blackboard
    comm.blackboard.write("agent1", "status", "working")

    # Use event bus
    comm.event_bus.subscribe("task_completed", callback)

    # Use mailbox
    comm.mailbox.send("agent1", "agent2", "Hello")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `clear` | `def (self) -> None` |

---

## tools.base

工具基类 — 所有工具的抽象父类。

### 类

#### `PermissionLevel(str, Enum)`

工具权限等级。

#### `ToolCall`

工具调用请求。

#### `ToolResult`

工具调用返回结果。

| 方法 | 签名 |
|------|------|
| `@classmethod ok` | `def (cls, call_id: str, output: str) -> 'ToolResult'` |
| `@classmethod fail` | `def (cls, call_id: str, error: str) -> 'ToolResult'` |

#### `BaseTool(ABC)`

工具基类 — 所有工具必须实现的接口。

| 方法 | 签名 |
|------|------|
| `parameters` | `def (self) -> dict` |
| `execute` | `async def (self, arguments: dict, sandbox) -> ToolResult` |
| `to_openai_schema` | `def (self) -> dict` |
| `to_anthropic_schema` | `def (self) -> dict` |
| `is_write_operation` | `def (self, arguments: dict) -> bool` |
| `is_read_operation` | `def (self, arguments: dict) -> bool` |
| `extract_target_path` | `def (self, arguments: dict) -> str | None` |

---

## tools.code_agent

CodeAgent 工具 — Agent直接写代码执行，不输出JSON。
基因来源: Smolagents
核心洞察: 代码的表达力远超JSON（循环/条件/异常/变量作用域）。

### 类

#### `CodeAgentTool(BaseTool)`

代码执行工具 — Agent不输出JSON，直接写Python代码。

| 方法 | 签名 |
|------|------|
| `parameters` | `def (self) -> dict` |
| `execute` | `async def (self, arguments: dict, sandbox) -> ToolResult` |
| `is_write_operation` | `def (self, arguments: dict) -> bool` |

#### `ShellTool(BaseTool)`

Shell命令执行工具。

| 方法 | 签名 |
|------|------|
| `parameters` | `def (self) -> dict` |
| `execute` | `async def (self, arguments: dict, sandbox) -> ToolResult` |
| `is_write_operation` | `def (self, arguments: dict) -> bool` |

---

## tools.file_tools

文件操作工具集。

### 类

#### `ReadFileTool(BaseTool)`

文件读取工具。

| 方法 | 签名 |
|------|------|
| `parameters` | `def (self) -> dict` |
| `execute` | `async def (self, arguments: dict, sandbox) -> ToolResult` |

#### `WriteFileTool(BaseTool)`

文件写入工具。

| 方法 | 签名 |
|------|------|
| `parameters` | `def (self) -> dict` |
| `execute` | `async def (self, arguments: dict, sandbox) -> ToolResult` |
| `is_write_operation` | `def (self, arguments: dict) -> bool` |

#### `ListDirectoryTool(BaseTool)`

目录列表工具。

| 方法 | 签名 |
|------|------|
| `parameters` | `def (self) -> dict` |
| `execute` | `async def (self, arguments: dict, sandbox) -> ToolResult` |

---

## tools.function_calling

Function Calling Pipeline — Schema-validated tool invocation.

Provides a complete function calling lifecycle: schema registration, LLM
tool_choice dispatch, argument validation, execution, and result formatting.

### 类

#### `ToolSchema`

OpenAI-compatible tool/function schema.

| 方法 | 签名 |
|------|------|
| `to_openai` | `def (self) -> dict[str, Any]` |
| `to_anthropic` | `def (self) -> dict[str, Any]` |

#### `ToolCall`

A parsed tool call from an LLM response.

#### `ToolResult`

Result of executing a tool call.

#### `ToolRegistry`

Registry of callable tools with schema validation.

Example::

    registry = ToolRegistry()
    registry.register(
        ToolSchema(name="get_weather", description="Get weather", parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}}
        }, required=["city"]),
        handler=lambda city: f"Weather in {city}: sunny"
    )

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `register` | `def (self, schema: ToolSchema, handler: Callable[..., Any]) -> None` |
| `unregister` | `def (self, name: str) -> None` |
| `get_schema` | `def (self, name: str) -> Optional[ToolSchema]` |
| `list_schemas` | `def (self) -> list[ToolSchema]` |
| `to_openai_tools` | `def (self) -> list[dict[str, Any]]` |
| `to_anthropic_tools` | `def (self) -> list[dict[str, Any]]` |
| `validate_arguments` | `def (self, name: str, arguments: dict) -> list[str]` |
| `execute` | `def (self, call: ToolCall) -> ToolResult` |
| `execute_batch` | `def (self, calls: list[ToolCall]) -> list[ToolResult]` |
| `parse_tool_calls` | `def (self, raw_tool_calls: list[dict[str, Any]]) -> list[ToolCall]` |
| `tool_count` | `def (self) -> int` |

---

## tools.fusion

Fusion Toolkit for NexusAgent.

Multi-tool coordination system. Allows agents to use
multiple tools in sequence or parallel, with automatic
result fusion and conflict resolution.

### 类

#### `FusionMode(str, Enum)`

Tool fusion modes.

#### `ToolSpec`

Tool specification.

Attributes:
    name: Tool name
    description: Tool description
    func: Tool function
    parameters: Parameter schema
    timeout: Execution timeout
    retry_count: Number of retries

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `ToolResult`

Result of a single tool execution.

Attributes:
    tool_name: Name of the tool
    success: Whether execution succeeded
    output: Tool output
    error: Error message (if failed)
    duration: Execution duration

#### `FusionResult`

Result of tool fusion.

Attributes:
    id: Unique identifier
    mode: Fusion mode used
    results: List of individual tool results
    fused_output: Fused final output
    total_duration: Total execution duration
    success: Whether fusion succeeded

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `FusionToolkit`

Multi-tool coordination system.

Allows agents to use multiple tools in different modes:
- Sequential: Run tools one by one
- Parallel: Run tools in parallel
- Chain: Output of one feeds into next

Usage:
    toolkit = FusionToolkit()
    toolkit.register(ToolSpec(name="search", func=search_func))
    toolkit.register(ToolSpec(name="summarize", func=summarize_func))

    # Sequential execution
    result = await toolkit.execute(["search", "summarize"], {"query": "AI"})

    # Parallel execution
    result = await toolkit.execute_parallel(["search", "summarize"], {"query": "AI"})

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, default_timeout: float) -> None` |
| `register` | `def (self, tool: ToolSpec) -> None` |
| `unregister` | `def (self, tool_name: str) -> bool` |
| `get_tool` | `def (self, tool_name: str) -> Optional[ToolSpec]` |
| `list_tools` | `def (self) -> list[ToolSpec]` |
| `execute` | `async def (self, tool_names: list[str], inputs: dict[str, Any], mode: FusionMode) -> Fus` |

---

## tools.generator

OpenAPI工具自动生成器 — 从OpenAPI/Swagger spec自动生成Agent工具包装器。
v0.50: 新增模块。将REST API端点自动转换为Agent可调用的ToolCall格式。

### 类

#### `GeneratedTool`

单个生成的工具描述。

| 方法 | 签名 |
|------|------|
| `to_openai_function` | `def (self) -> dict` |
| `to_tool_dict` | `def (self) -> dict` |

#### `OpenAPIToolGenerator`

从OpenAPI 3.x / Swagger 2.0 spec生成Agent工具。

用法:
    gen = OpenAPIToolGenerator("https://api.example.com/openapi.json")
    tools = await gen.generate()
    # tools是GeneratedTool列表，可直接注入Agent context

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, spec_url: str, spec_path: str, api_base: str, auth_header: str, auth_value: s` |
| `load_spec` | `async def (self) -> dict` |
| `generate` | `async def (self, filter_tag: str, max_tools: int) -> list[GeneratedTool]` |
| `invoke` | `async def (self, tool: GeneratedTool, params: dict) -> dict` |
| `close` | `async def (self) -> None` |

---

## tools.orchestrator

AgentOS v1.1.7 — 工具链编排引擎（Checkpoint/恢复）。
基因来源: Airflow DAG + LangChain Tool Composition

支持:
- 顺序链 (chain): 工具A → 工具B → 工具C
- 并行分支 (parallel): A + B 同时 → C
- 条件执行 (conditional): if X then A else B
- 重试策略 (retry): 指数退避 / 固定间隔
- 超时控制 (timeout): 单工具 / 全链
- Checkpoint/恢复: 长时间DAG断点保存与续跑

### 类

#### `NodeState(str, Enum)`

DAG 节点状态。

#### `NodeResult`

DAG 节点执行结果。

#### `DAGResult`

DAG 执行结果。

#### `RetryPolicy`

重试策略类。

#### `ToolNode`

工具执行节点。

#### `ConditionNode`

条件分支节点。

#### `ParallelGroup`

并行执行组 — 所有节点同时执行。

#### `DAGSpec`

DAG编排规格。

#### `CheckpointData`

DAG执行快照，支持断点续跑。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `@classmethod from_dict` | `def (cls, data: dict) -> 'CheckpointData'` |
| `to_json` | `def (self) -> str` |
| `@classmethod from_json` | `def (cls, json_str: str) -> 'CheckpointData'` |

#### `ToolOrchestrator`

工具链编排引擎 — DAG执行、并行调度、条件分支、Checkpoint恢复。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, tool_registry: Any) -> None` |
| `execute` | `async def (self, dag: DAGSpec) -> DAGResult` |
| `results` | `def (self) -> dict[str, NodeResult]` |
| `checkpoint` | `def (self, dag: DAGSpec) -> CheckpointData` |
| `restore_from_checkpoint` | `def (self, dag: DAGSpec, cp: CheckpointData) -> dict[str, NodeResult]` |
| `execute_with_checkpoint` | `async def (self, dag: DAGSpec, checkpoint_callback: Callable[[CheckpointData], None], ch` |

#### `DAGBuilder`

流式构建DAG。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, name: str) -> None` |
| `node` | `def (self, node_id: str, tool_name: str, tool_args: dict | None, depends_on: list[str] |` |
| `parallel` | `def (self, node_ids: list[str], depends_on: list[str] | None, max_concurrency: int) -> '` |
| `condition` | `def (self, cond_id: str, condition: Callable, depends_on: list[str]) -> 'DAGBuilder'` |
| `build` | `def (self, global_timeout: float) -> DAGSpec` |

### 函数

| 函数 | 签名 |
|------|------|
| `chain_builder` | `def (name: str, tool_names: list[str]) -> DAGSpec` |
| `parallel_then_merge` | `def (name: str, parallel_tools: list[str], merge_tool: str) -> DAGSpec` |
| `if_then_else` | `def (name: str, check_tool: str, true_tool: str, false_tool: str) -> DAGSpec` |

---

## tools.registry

统一工具注册表 — 核心循环不关心具体实现。

### 类

#### `ToolRegistry`

统一工具注册表。所有工具在这里注册，核心循环不关心具体实现。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `register` | `def (self, tool: BaseTool) -> None` |
| `register_many` | `def (self, tools: list[BaseTool]) -> None` |
| `get` | `def (self, name: str) -> BaseTool | None` |
| `list_names` | `def (self) -> list[str]` |
| `get_schemas_for_model` | `def (self, model_type: str) -> list[dict]` |
| `execute_batch` | `async def (self, calls: list[ToolCall], sandbox) -> list[ToolResult]` |
| `@staticmethod make_call_id` | `def () -> str` |

---

## tools.risk

AgentOS v1.1.4 Tool Risk Rating — 工具风险分级。

给每个工具标注低/中/高风险，触发对应级别的 guard 检查。
灵感来自 OpenAI Agents SDK 的 Tool Risk Rating 设计。

### 类

#### `ToolRiskLevel(str, Enum)`

工具操作风险等级。

LOW:     只读查询、信息检索，无副作用
MEDIUM:  写入/修改操作，可逆或有审计
HIGH:    删除、支付、发消息等不可逆操作
CRITICAL: 系统级操作（格式化、重置、权限变更）

#### `ToolRiskRating`

工具风险评定元数据。

| 方法 | 签名 |
|------|------|
| `requires_user_confirm` | `def (self) -> bool` |

### 函数

| 函数 | 签名 |
|------|------|
| `get_risk_preset` | `def (tool_name: str) -> Optional[ToolRiskRating]` |
| `infer_risk_level` | `def (tool_name: str, tool_description: str, arguments: Optional[dict]) -> ToolRiskRating` |

---

## tools.web_tools

网络工具 — 搜索与网页抓取。

### 类

#### `WebFetchTool(BaseTool)`

网页抓取工具。

| 方法 | 签名 |
|------|------|
| `parameters` | `def (self) -> dict` |
| `execute` | `async def (self, arguments: dict, sandbox) -> ToolResult` |

---

## server.mcp_server

AgentOS v0.40 MCP Server — 将AgentOS暴露为MCP Server。
支持工具列表、资源、提示模板的MCP协议暴露。

### 类

#### `MCPServerConfig`

MCP 服务端配置。

#### `MCPTool`

MCP工具定义。

#### `MCPResource`

MCP资源定义。

#### `MCPPrompt`

MCP提示模板。

#### `MCPServer`

MCP Server核心 — 将AgentOS能力以MCP协议暴露。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: MCPServerConfig | None) -> None` |
| `register_tool` | `def (self, tool: MCPTool) -> None` |
| `register_resource` | `def (self, resource: MCPResource) -> None` |
| `register_prompt` | `def (self, prompt: MCPPrompt) -> None` |
| `handle_request` | `def (self, raw: dict) -> dict` |
| `stats` | `def (self) -> dict` |

#### `MCPClient`

MCP客户端 — AgentOS中Agent连接到外部MCP Server。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, server_url: str, transport: str) -> None` |
| `connect` | `async def (self) -> None` |
| `list_tools` | `async def (self) -> list[dict]` |
| `call_tool` | `async def (self, name: str, arguments: dict) -> dict` |
| `disconnect` | `def (self) -> None` |

---

## mcp.adapter

MCP Tool Adapter for AgentOS.

Wraps MCP tools as AgentOS BaseTool instances, enabling seamless
integration with the AgentOS tool system and permission model.

### 类

#### `MCPToolAdapter(BaseTool)`

Adapts an MCP tool to the AgentOS BaseTool interface.

Wraps a remote MCP tool call in the standard BaseTool protocol,
handling execution, schema export, and permission routing.

Usage:
    adapter = MCPToolAdapter(
        client=mcp_client,
        tool_info=tool_info,
        permission_level=PermissionLevel.MODERATE,
    )
    result = await adapter.execute({"path": "/tmp/test.txt"})

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, client: MCPClient, tool_info: MCPToolInfo, permission_level: PermissionLevel,` |
| `name` | `def (self) -> str` |
| `description` | `def (self) -> str` |
| `parameters` | `def (self) -> dict` |
| `execute` | `async def (self, arguments: dict, sandbox) -> ToolResult` |
| `to_openai_schema` | `def (self) -> dict` |
| `to_anthropic_schema` | `def (self) -> dict` |
| `is_write_operation` | `def (self, arguments: dict) -> bool` |
| `is_read_operation` | `def (self, arguments: dict) -> bool` |
| `extract_target_path` | `def (self, arguments: dict) -> Optional[str]` |

#### `MCPToolRegistry`

Registry that adapts all tools from an MCPClient into BaseTool instances.

Creates MCPToolAdapter wrappers for each discovered tool, with
appropriate permission level assignment.

Usage:
    registry = MCPToolRegistry(client)
    tools = registry.get_all_tools()
    # tools can now be used with any AgentOS agent

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, client: MCPClient, default_permission: PermissionLevel) -> None` |
| `get_all_tools` | `def (self) -> Dict[str, BaseTool]` |
| `get_tool` | `def (self, name: str) -> Optional[BaseTool]` |
| `get_tool_schemas` | `def (self, format: str) -> list` |
| `refresh` | `def (self) -> None` |

---

## log.formatter

AgentOS logging — structured JSON formatter with trace context.

### 类

#### `TraceContext`

Carries trace_id and span_id through a request lifecycle.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, trace_id: Optional[str], span_id: Optional[str]) -> None` |

#### `JSONFormatter(_stdlib_logging.Formatter)`

Emits log records as JSON with trace context fields.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, fmt, datefmt, style, trace_ctx: Optional[TraceContext]) -> None` |
| `format` | `def (self, record: _stdlib_logging.LogRecord) -> str` |

### 函数

| 函数 | 签名 |
|------|------|
| `audit_log` | `def (logger: _stdlib_logging.Logger, action: str, user_id: str, result: str, details: Op` |
| `setup_structured_logging` | `def (name: str, level: int, stream: Optional[IO], trace_ctx: Optional[TraceContext]) -> ` |
| `get_logger` | `def (name: str) -> _stdlib_logging.Logger` |

---

## queue.rate_limiter

AgentOS v0.60 Rate Limiter — 流量控制。
Token Bucket + Sliding Window + Concurrency Limiter + 多级配额。

### 类

#### `RateLimitStrategy(str, Enum)`

限流策略枚举。

#### `RateLimitConfig`

限流配置。

#### `RateLimitResult`

限流检查结果。

#### `TokenBucket`

令牌桶算法实现。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, rate: float, capacity: int) -> None` |
| `consume` | `async def (self, tokens: int) -> bool` |
| `available` | `def (self) -> float` |

#### `SlidingWindow`

滑动窗口计数器。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_requests: int, window_seconds: float) -> None` |
| `allow` | `async def (self) -> bool` |
| `current_count` | `def (self) -> int` |

#### `ConcurrencyLimiter`

并发请求限制器。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_concurrent: int) -> None` |
| `acquire` | `async def (self) -> bool` |
| `release` | `def (self) -> None` |
| `available` | `def (self) -> int` |

#### `RateLimiter`

组合限流器：Token Bucket + Concurrency Limiter + 多级配额。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: RateLimitConfig | None) -> None` |
| `acquire` | `async def (self, weight: int) -> RateLimitResult` |
| `release` | `async def (self) -> None` |
| `model_quota` | `def (self, model: str) -> RateLimitConfig` |

#### `QuotaManager`

多租户配额管理。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `get` | `def (self, key: str, config: RateLimitConfig | None) -> RateLimiter` |
| `add_quota` | `def (self, key: str, config: RateLimitConfig) -> None` |
| `clear_expired` | `def (self, ttl: float) -> None` |

---

## queue.task_queue

AgentOS v0.40 Task Queue — 异步任务调度与重试。
支持：内存队列（开发）/ Redis队列（生产）、优先级、重试、死信队列。

### 类

#### `TaskState(str, Enum)`

任务状态枚举。

#### `TaskPriority(int, Enum)`

任务优先级枚举。

#### `QueuedTask`

带优先级的任务节点（priority取负以实现最大堆）。

#### `ScheduledTask`

调度任务。

#### `MemoryQueue`

基于堆内存的任务队列 — 开发环境默认。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_size: int) -> None` |
| `enqueue` | `async def (self, task: ScheduledTask) -> str` |
| `dequeue` | `async def (self) -> ScheduledTask | None` |
| `peek` | `async def (self) -> ScheduledTask | None` |
| `pending_count` | `def (self) -> int` |
| `dead_count` | `def (self) -> int` |
| `move_to_dead` | `async def (self, task: ScheduledTask) -> None` |
| `stats` | `def (self) -> dict` |

#### `TaskQueue`

任务队列管理器。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, queue: MemoryQueue | None, concurrency: int) -> None` |
| `register_callback` | `def (self, task_name: str, handler: Callable) -> None` |
| `submit` | `async def (self, task: ScheduledTask) -> str` |
| `start` | `async def (self) -> None` |
| `stop` | `def (self) -> None` |
| `cancel` | `def (self, task_id: str) -> None` |
| `stats` | `def (self) -> dict` |

---

## hitl.approver

Human-in-the-Loop approval engine — request construction, risk assessment,
policy evaluation, and decision processing.

### 类

#### `ApprovalStatus(str, Enum)`

Status of an approval request.

#### `RiskLevel(str, Enum)`

Risk classification for approval decisions.

#### `ApprovalRequest`

A structured request for human approval.

#### `ApprovalDecision`

Human decision on an approval request.

| 方法 | 签名 |
|------|------|
| `is_approved` | `def (self) -> bool` |
| `is_rejected` | `def (self) -> bool` |

#### `ApprovalPolicy`

Configures which actions require human approval.

#### `HumanInTheLoop`

Manages the human approval workflow for tool calls and mutations.

Supports synchronous callbacks (CLI prompt, webhook, etc.) and
configurable auto-approval rules based on risk and domain.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, policy: Optional[ApprovalPolicy], callback: Optional[ApprovalCallback]) -> No` |
| `request_approval` | `def (self, action: str, description: str, risk_level: RiskLevel, tool_name: str, tool_ar` |
| `decide` | `def (self, request_id: str, decision: ApprovalDecision) -> None` |
| `get_decision` | `def (self, request_id: str) -> Optional[ApprovalDecision]` |
| `get_pending` | `def (self) -> list[ApprovalRequest]` |
| `get_history` | `def (self) -> list[tuple[ApprovalRequest, ApprovalDecision]]` |
| `clear_cache` | `def (self) -> None` |
| `request_and_decide` | `def (self, action: str, description: str, risk_level: RiskLevel, tool_name: str, tool_ar` |

---

## hitl.presets

Pre-built HITL approval policies for common deployment scenarios.

### 函数

| 函数 | 签名 |
|------|------|
| `default_approval_policy` | `def () -> ApprovalPolicy` |
| `permissive_approval_policy` | `def () -> ApprovalPolicy` |
| `strict_approval_policy` | `def () -> ApprovalPolicy` |

---

## vectorstore.db

AgentOS v0.30 向量数据库集成 — Chroma + FAISS。
语义记忆检索、知识库索引。

### 类

#### `VectorEntry`

向量条目。

#### `BaseVectorStore`

向量存储基类。

| 方法 | 签名 |
|------|------|
| `add` | `def (self, texts: list[str], metadatas: list[dict] | None, ids: list[str] | None) -> lis` |
| `search` | `def (self, query: str, top_k: int) -> list[VectorEntry]` |
| `delete` | `def (self, ids: list[str]) -> None` |
| `count` | `def (self) -> int` |

#### `FAISSVectorStore(BaseVectorStore)`

基于 FAISS 的轻量向量存储。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, dim: int, index_path: str) -> None` |
| `add` | `def (self, texts: list[str], metadatas: list[dict] | None, ids: list[str] | None) -> lis` |
| `search` | `def (self, query: str, top_k: int) -> list[VectorEntry]` |
| `delete` | `def (self, ids: list[str]) -> None` |
| `count` | `def (self) -> int` |

#### `ChromaVectorStore(BaseVectorStore)`

Chroma 向量存储。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, collection_name: str, persist_dir: str) -> None` |
| `add` | `def (self, texts: list[str], metadatas: list[dict] | None, ids: list[str] | None) -> lis` |
| `search` | `def (self, query: str, top_k: int) -> list[VectorEntry]` |
| `delete` | `def (self, ids: list[str]) -> None` |
| `count` | `def (self) -> int` |

---

## storage.base

AgentOS v0.20 持久化存储层。
Base + SQLite实现，支持Checkpoint持久化。

### 类

#### `CheckpointStore(ABC)`

检查点存储基类。

| 方法 | 签名 |
|------|------|
| `save` | `async def (self, session_id: str, snapshot: dict) -> None` |
| `load` | `async def (self, session_id: str) -> dict | None` |
| `delete` | `async def (self, session_id: str) -> None` |
| `list_sessions` | `async def (self, limit: int) -> list[str]` |

#### `SqliteStore(CheckpointStore)`

SQLite 持久化存储。

| 方法 | 签名 |
|------|------|
| `save` | `async def (self, session_id: str, snapshot: dict) -> None` |
| `load` | `async def (self, session_id: str) -> dict | None` |
| `delete` | `async def (self, session_id: str) -> None` |
| `list_sessions` | `async def (self, limit: int) -> list[str]` |

---

## observability.cost_analytics

AgentOS v0.70 — 成本分析与运营仪表板。
基因来源: OpenAI Usage Dashboard + Grafana

提供:
- 按模型/按天/按session的多维度成本统计
- Token消耗趋势分析
- 预算预警系统
- 成本预测（简单滑动平均）

### 类

#### `CostEntry`

单次调用的成本记录。

#### `DailySummary`

日成本摘要。

#### `CostBreakdown`

单次调用的详细成本分解。

#### `CostSession`

单次会话的成本摘要。

#### `BudgetAlert`

预算告警。

#### `CostAnalytics`

成本分析引擎 — 多维度聚合、趋势、预算管理。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, cost_tracker: CostTracker, budget_monthly: float, warn_threshold: float, pers` |
| `record` | `def (self, model: str, session_id: str, input_tokens: int, output_tokens: int, duration_` |
| `by_model` | `def (self, hours: float) -> list[dict]` |
| `daily_breakdown` | `def (self, days: int) -> list[DailySummary]` |
| `by_session` | `def (self, top_n: int) -> list[dict]` |
| `trend` | `def (self, metric: str, window: int) -> list[dict]` |
| `check_budget` | `def (self) -> BudgetAlert` |
| `total_cost` | `def (self) -> float` |
| `total_calls` | `def (self) -> int` |
| `summary` | `def (self) -> str` |
| `get_breakdown` | `def (self, session_id: str, hours: float) -> list[CostBreakdown]` |
| `get_session` | `def (self, session_id: str) -> CostSession | None` |
| `cost_by_score_tier` | `def (self, scores: dict[float, list[str]]) -> dict[str, float]` |

---

## observability.metrics

AgentOS v0.70 — 性能指标与可观测性增强。
基因来源: Prometheus metrics + OpenTelemetry

提供:
- 延迟分位数 (p50/p95/p99)
- 吞吐量统计 (RPS)
- 错误率追踪
- 缓存命中率
- TTL-based环形缓冲区

### 类

#### `MetricSnapshot`

指标快照 — 用于导出/序列化。

| 方法 | 签名 |
|------|------|
| `to_json` | `def (self) -> str` |
| `@classmethod from_collector` | `def (cls, collector: 'MetricsCollector') -> 'MetricSnapshot'` |

#### `MetricPoint`

指标数据点。

#### `Histogram`

滑动窗口直方图 — 计算分位数。

| 方法 | 签名 |
|------|------|
| `observe` | `def (self, value: float, **labels) -> None` |
| `count` | `def (self) -> int` |
| `quantile` | `def (self, q: float) -> float` |
| `p50` | `def (self) -> float` |
| `p95` | `def (self) -> float` |
| `p99` | `def (self) -> float` |
| `avg` | `def (self) -> float` |
| `min_val` | `def (self) -> float` |
| `max_val` | `def (self) -> float` |
| `stats` | `def (self) -> dict` |

#### `Counter`

单调递增计数器。

| 方法 | 签名 |
|------|------|
| `inc` | `def (self, amount: int) -> None` |
| `value` | `def (self) -> int` |

#### `Gauge`

可增可减的仪表值。

| 方法 | 签名 |
|------|------|
| `set` | `def (self, value: float) -> None` |
| `inc` | `def (self, amount: float) -> None` |
| `dec` | `def (self, amount: float) -> None` |
| `value` | `def (self) -> float` |

#### `MetricsCollector`

统一指标收集器。
内置: latency, throughput, error_rate, cache_hit_rate。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, window_seconds: float) -> None` |
| `record_step_latency` | `def (self, duration_ms: float) -> None` |
| `record_model_latency` | `def (self, duration_ms: float, model: str) -> None` |
| `record_tool_latency` | `def (self, duration_ms: float, tool: str) -> None` |
| `record_error` | `def (self) -> None` |
| `record_cache_hit` | `def (self) -> None` |
| `record_cache_miss` | `def (self) -> None` |
| `uptime_seconds` | `def (self) -> float` |
| `rps` | `def (self) -> float` |
| `error_rate` | `def (self) -> float` |
| `cache_hit_rate` | `def (self) -> float` |
| `snapshot` | `def (self) -> dict` |
| `summary` | `def (self) -> str` |

---

## observability.otel_bridge

AgentOS OpenTelemetry - OTLP/Jaeger/Zipkin trace/metric export (v1.3.14).

### 类

#### `OTelExporter(str, Enum)`

OpenTelemetry exporter backend.

#### `OtelStatus(str, Enum)`

Span status codes.

#### `SpanKind(str, Enum)`

Span kind for semantic conventions.

#### `OtelConfig`

OpenTelemetry configuration.

| 方法 | 签名 |
|------|------|
| `with_env_overrides` | `def (self) -> 'OtelConfig'` |

#### `SpanHandle`

Wrapper around OTel span for attribute/event/exception API.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, span: Any) -> None` |
| `set_attribute` | `def (self, key: str, value: Any) -> None` |
| `set_attributes` | `def (self, attrs: Dict[str, Any]) -> None` |
| `add_event` | `def (self, name: str, attributes: Optional[Dict[str, Any]]) -> None` |
| `record_exception` | `def (self, exception: Exception) -> None` |
| `set_status` | `def (self, status: OtelStatus, description: str) -> None` |

#### `OtelTracer`

OpenTelemetry tracer with span management and W3C context propagation.

Usage:
    OtelTracer.init(OtelConfig(service_name="my-agent"))

    with OtelTracer.span("llm_call", kind=SpanKind.CLIENT) as span:
        span.set_attribute("model", "gpt-4")
        result = llm.generate(prompt)

    @OtelTracer.trace("process")
    async def process(input): ...

| 方法 | 签名 |
|------|------|
| `@classmethod init` | `def (cls, config: Optional[OtelConfig]) -> None` |
| `@classmethod get_tracer` | `def (cls, name: str) -> Any` |
| `@classmethod span` | `def (cls, name: str, kind: SpanKind, attributes: Optional[Dict[str, Any]], parent: Any) ` |
| `@classmethod trace` | `def (cls, name: str, kind: SpanKind, extract_attrs: Optional[Callable]) -> None` |
| `@classmethod async_span` | `async def (cls, name: str, kind: SpanKind, **attrs) -> None` |
| `@classmethod shutdown` | `def (cls) -> None` |

#### `OtelMeter`

Bridge MetricsCollector to OpenTelemetry metrics.

| 方法 | 签名 |
|------|------|
| `@classmethod init` | `def (cls, config: Optional[OtelConfig]) -> None` |
| `@classmethod record_counter` | `def (cls, name: str, value: float, attrs: Optional[Dict[str, str]]) -> None` |
| `@classmethod record_histogram` | `def (cls, name: str, value: float, attrs: Optional[Dict[str, str]]) -> None` |
| `@classmethod record_gauge` | `def (cls, name: str, value: float, attrs: Optional[Dict[str, str]]) -> None` |
| `@classmethod bridge` | `def (cls, collector: 'MetricsCollector') -> None` |

#### `OtelMiddleware`

W3C TraceContext propagation for multi-agent pipelines.

| 方法 | 签名 |
|------|------|
| `@staticmethod inject_context` | `def (headers: Optional[Dict[str, str]]) -> Dict[str, str]` |
| `@staticmethod extract_context` | `def (headers: Optional[Dict[str, str]]) -> None` |
| `@staticmethod get_trace_id` | `def () -> str` |
| `@staticmethod get_span_id` | `def () -> str` |

---

## observability.tracer

全链路追踪 — 每一步可追溯。
基因来源: LangSmith + OpenAI Tracing

### 类

#### `StepTrace`

单步追踪记录。

#### `TokenStats`

Token 使用统计。

#### `ObservabilityReport`

可观测性报告。

| 方法 | 签名 |
|------|------|
| `summary` | `def (self) -> str` |

#### `Tracer`

全链路追踪器。每步记录耗时、token消耗、工具调用。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, session_id: str) -> None` |
| `@classmethod noop` | `def (cls) -> 'Tracer'` |
| `step` | `def (self, name: str, model: str) -> None` |
| `track_tokens` | `def (self, model: str, input_tokens: int, output_tokens: int) -> None` |
| `track_tool_call` | `def (self) -> None` |
| `report` | `def (self) -> ObservabilityReport` |
| `token_summary` | `def (self) -> dict[str, int]` |

#### `NoopTracer(Tracer)`

空追踪器 — 生产环境中关闭追踪时使用。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `step` | `def (self, name: str, model: str) -> None` |
| `track_tokens` | `def (self, model: str, input_tokens: int, output_tokens: int) -> None` |
| `track_tool_call` | `def (self) -> None` |
| `report` | `def (self) -> ObservabilityReport` |
| `token_summary` | `def (self) -> dict[str, int]` |

---

## prompts.few_shot

Few-Shot Example Management — intelligent few-shot selection strategies.

Supports similarity-based, random, diversity-maximizing, and
custom selection algorithms for constructing optimal few-shot prompts.

### 类

#### `SelectionStrategy(str, Enum)`

Strategy for selecting few-shot examples.

#### `Example`

A single training example for few-shot learning.

#### `FewShotSelector`

Selects and formats the best few-shot examples for a given query.

Usage::

    examples = [
        Example(input="What is 2+2?", output="4", label="math"),
        Example(input="Capital of France?", output="Paris", label="geo"),
    ]
    selector = FewShotSelector(examples, strategy=SelectionStrategy.SIMILARITY)
    prompt = selector.build_prompt("What is 3+5?", base_instruction="Answer:")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, examples: Sequence[Example], strategy: SelectionStrategy, max_examples: int, ` |
| `select` | `def (self, query: str, k: Optional[int]) -> list[Example]` |
| `build_prompt` | `def (self, query: str, base_instruction: str, k: Optional[int]) -> str` |
| `add_example` | `def (self, example: Example) -> None` |
| `remove_example` | `def (self, example_id: str) -> None` |
| `set_score` | `def (self, example_id: str, score: float) -> None` |

### 函数

| 函数 | 签名 |
|------|------|
| `build_examples` | `def (pairs: Iterable[tuple[str, str]], labels: Iterable[str] | None, metadata: list[dict` |

---

## prompts.manager

AgentOS v0.30 Prompt模板管理 — 版本化Prompt仓库。
支持模板继承、变量注入、A/B测试、回滚。

### 类

#### `PromptTemplate`

Prompt 模板。

| 方法 | 签名 |
|------|------|
| `render` | `def (self, **kwargs) -> str` |

#### `PromptRegistry`

Prompt模板注册中心。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, storage_path: str) -> None` |
| `register` | `def (self, template: PromptTemplate) -> None` |
| `get` | `def (self, name: str, version: str) -> PromptTemplate | None` |
| `get_version` | `def (self, name: str, version: str) -> PromptTemplate | None` |
| `list_templates` | `def (self) -> list[dict]` |
| `render` | `def (self, name: str, version: str, **kwargs) -> str` |
| `rollback` | `def (self, name: str, target_version: str) -> None` |
| `stats` | `def (self) -> dict` |

---

## prompts.optimizer

Prompt Optimizer — DSPy-inspired automatic prompt improvement via
iterative refinement, few-shot bootstrapping, and multi-strategy optimization.

### 类

#### `OptimizationStrategy(str, Enum)`

Available optimization approaches.

#### `OptimizerConfig`

Configuration for prompt optimization runs.

#### `PromptCandidate`

A single prompt variant under evaluation.

#### `OptimizationResult`

Final result after optimization converges or exhausts budget.

#### `PromptOptimizer`

Iteratively refines prompts using a pluggable scoring function.

Usage::

    def score(prompt: str) -> float:
        # run your LLM eval and return metric
        return measure(prompt)

    opt = PromptOptimizer(config)
    result = opt.optimize(base_prompt, score_fn=score)
    print(result.best_prompt)

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[OptimizerConfig]) -> None` |
| `optimize` | `def (self, base_prompt: str, score_fn: Callable[[str], float], few_shot_examples: list[s` |

---

## llm.anthropic_provider

Anthropic Claude Provider — 基于 httpx 直接调用 Anthropic Messages API。
零额外依赖，不依赖 anthropic SDK。
v1.3.36: 首个纯 httpx 实现，支持同步/异步/流式/Function Calling。

### 类

#### `AnthropicProvider(LLMProvider)`

Anthropic Claude Provider — 纯 httpx 实现，零 SDK 依赖。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, model: str, api_key: str, base_url: str, timeout: float) -> None` |
| `provider_name` | `def (self) -> str` |
| `chat` | `def (self, messages: list[Message], **kwargs) -> CompletionResult` |
| `achat` | `async def (self, messages: list[Message], **kwargs) -> CompletionResult` |
| `stream` | `def (self, messages: list[Message], **kwargs) -> Iterator[StreamChunk]` |
| `astream` | `async def (self, messages: list[Message], **kwargs) -> None` |

---

## llm.base

LLM Provider 抽象层。
为 Nexus AgentOS 提供统一的 LLM 调用接口，实现 Provider 无关性。
v1.3.36: +Function Calling / Tool Use 抽象。

### 类

#### `MessageRole(str, Enum)`

#### `TokenUsage`

#### `CompletionUsage(TokenUsage)`

#### `Message`

| 方法 | 签名 |
|------|------|
| `as_dict` | `def (self) -> dict[str, Any]` |

#### `ToolParameter`

JSON Schema 属性定义。

| 方法 | 签名 |
|------|------|
| `as_schema` | `def (self) -> dict[str, Any]` |

#### `ToolFunction`

函数定义。

| 方法 | 签名 |
|------|------|
| `as_schema` | `def (self) -> dict[str, Any]` |

#### `Tool`

顶层 Tool 包装。

| 方法 | 签名 |
|------|------|
| `as_schema` | `def (self) -> dict[str, Any]` |
| `@classmethod from_function` | `def (cls, name: str, description: str, parameters: dict[str, ToolParameter] | None, requ` |

#### `ToolCall`

模型请求的工具调用。

| 方法 | 签名 |
|------|------|
| `parsed_arguments` | `def (self) -> dict[str, Any]` |

#### `CompletionChoice`

#### `CompletionResult`

#### `StreamChunk`

#### `LLMProvider(ABC)`

统一 LLM Provider 抽象。实现 OpenAI / Anthropic / 本地模型 的标准化调用。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, model: str, api_key: str, base_url: str) -> None` |
| `chat` | `def (self, messages: list[Message], **kwargs) -> CompletionResult` |
| `achat` | `async def (self, messages: list[Message], **kwargs) -> CompletionResult` |
| `stream` | `def (self, messages: list[Message], **kwargs) -> Iterator[StreamChunk]` |
| `astream` | `async def (self, messages: list[Message], **kwargs) -> None` |
| `provider_name` | `def (self) -> str` |

---

## llm.deepseek_provider

DeepSeek Provider — 基于 OpenAIProvider 子类化，仅换 base_url。
DeepSeek API 完全兼容 OpenAI Chat Completions 格式。
v1.3.36: 首个实现，支持 Function Calling。

### 类

#### `DeepSeekProvider(OpenAIProvider)`

DeepSeek Provider — OpenAI 兼容，零额外代码。

用法:
    provider = DeepSeekProvider(api_key="sk-...")
    result = provider.chat([Message(role=MessageRole.USER, content="Hello")])

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, model: str, api_key: str, base_url: str, timeout: float) -> None` |
| `provider_name` | `def (self) -> str` |

---

## llm.factory

LLM Provider 工厂 — 按名称/配置创建 Provider 实例。
v1.3.36: DeepSeek + Anthropic 硬注册（纯 httpx 实现，零 SDK 依赖）。

用法:
    from agentos.llm.factory import create_provider

    provider = create_provider("openai", model="gpt-4o", api_key="sk-...")
    result = provider.chat([Message(...), Message(...)])

### 函数

| 函数 | 签名 |
|------|------|
| `create_provider` | `def (name: str, **extra) -> LLMProvider` |

---

## llm.openai_provider

OpenAI Provider 实现 — 基于官方 openai SDK 的对话补全。
v1.3.36: +Function Calling / Tool Use 支持。

### 类

#### `OpenAIProvider(LLMProvider)`

OpenAI SDK 提供商。支持 openai、azure、及所有 OpenAI 兼容的三方端点。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, model: str, api_key: str, base_url: str, organization: str, timeout: float) -` |
| `provider_name` | `def (self) -> str` |
| `chat` | `def (self, messages: list[Message], **kwargs) -> CompletionResult` |
| `achat` | `async def (self, messages: list[Message], **kwargs) -> CompletionResult` |
| `stream` | `def (self, messages: list[Message], **kwargs) -> Iterator[StreamChunk]` |

---

## llm.examples.llm_chat_demo

Nexus AgentOS — LLM Provider 端到端示例 v1.3.36。
演示：OpenAI / DeepSeek / Anthropic 多 Provider + Function Calling + 流式。

运行:
    export OPENAI_API_KEY="sk-..."
    python examples/llm_chat_demo.py

多 Provider:
    python examples/llm_chat_demo.py --provider deepseek

Function Calling:
    python examples/llm_chat_demo.py --mode functions

### 函数

| 函数 | 签名 |
|------|------|
| `run_chat` | `def (provider_name: str, model: str, prompt: str) -> None` |
| `run_multi_turn` | `def (provider_name: str, model: str) -> None` |
| `run_streaming` | `def (provider_name: str, model: str) -> None` |
| `run_function_calling` | `def (provider_name: str, model: str) -> None` |
| `main` | `def () -> None` |

---

## llm.examples.llm_quickstart

Nexus AgentOS — LLM 快速入门示例 v1.3.36。
5 行代码启动 LLM 调用，支持多 Provider 与 Function Calling。

运行:
    export OPENAI_API_KEY="sk-..."
    python examples/llm_quickstart.py

---

## llm.tests.test_providers

LLM Provider 模块单元测试 — v1.3.36。
测试范围: factory, base types, Function Calling, DeepSeek, Anthropic (unit/mock)。

### 类

#### `TestTokenUsage`

| 方法 | 签名 |
|------|------|
| `test_defaults` | `def (self) -> None` |
| `test_values` | `def (self) -> None` |

#### `TestCompletionUsage`

| 方法 | 签名 |
|------|------|
| `test_cost_default` | `def (self) -> None` |

#### `TestMessage`

| 方法 | 签名 |
|------|------|
| `test_basic` | `def (self) -> None` |
| `test_with_tool_call_id` | `def (self) -> None` |
| `test_with_tool_calls` | `def (self) -> None` |

#### `TestToolParameter`

| 方法 | 签名 |
|------|------|
| `test_basic_schema` | `def (self) -> None` |
| `test_with_enum` | `def (self) -> None` |

#### `TestTool`

| 方法 | 签名 |
|------|------|
| `test_from_function` | `def (self) -> None` |
| `test_to_openai_format` | `def (self) -> None` |

#### `TestToolCall`

| 方法 | 签名 |
|------|------|
| `test_create_and_parse` | `def (self) -> None` |
| `test_empty_arguments` | `def (self) -> None` |

#### `TestStreamChunk`

| 方法 | 签名 |
|------|------|
| `test_defaults` | `def (self) -> None` |
| `test_with_content` | `def (self) -> None` |

#### `TestCreateProvider`

| 方法 | 签名 |
|------|------|
| `test_openai_default` | `def (self) -> None` |
| `test_deepseek_default` | `def (self) -> None` |
| `test_anthropic_default` | `def (self) -> None` |
| `test_unknown_provider` | `def (self) -> None` |
| `test_api_key_env_openai` | `def (self) -> None` |
| `test_custom_model` | `def (self) -> None` |

#### `TestDeepSeekProvider`

| 方法 | 签名 |
|------|------|
| `test_is_openai_subclass` | `def (self) -> None` |
| `test_provider_name` | `def (self) -> None` |
| `test_default_base_url` | `def (self) -> None` |
| `test_custom_base_url` | `def (self) -> None` |
| `test_default_model` | `def (self) -> None` |
| `test_factory_creates` | `def (self) -> None` |

#### `TestAnthropicProvider`

| 方法 | 签名 |
|------|------|
| `test_provider_name` | `def (self) -> None` |
| `test_default_model` | `def (self) -> None` |
| `test_default_base_url` | `def (self) -> None` |
| `test_custom_base_url` | `def (self) -> None` |
| `test_headers` | `def (self) -> None` |
| `test_tools_conversion` | `def (self) -> None` |
| `test_message_conversion_simple` | `def (self) -> None` |
| `test_message_conversion_with_system` | `def (self) -> None` |
| `test_build_body_includes_tools` | `def (self) -> None` |

---

## cli.config_panel

AgentOS 配置面板 — Web GUI，一键浏览器配置 API Key。

启动: agentos config-panel
访问: http://localhost:18480

### 类

#### `PanelHandler(http.server.BaseHTTPRequestHandler)`

HTTP 请求处理。

| 方法 | 签名 |
|------|------|
| `log_message` | `def (self, format, *args) -> None` |
| `do_GET` | `def (self) -> None` |
| `do_POST` | `def (self) -> None` |

### 函数

| 函数 | 签名 |
|------|------|
| `start_panel` | `def (port: int, open_browser: bool) -> None` |

---

## cli.init

`agentos init` — 交互式配置向导。

功能：
  - 检测当前配置状态
  - 引导选择 Provider + 输入 API Key
  - 写入 ~/.agentos/config.yaml
  - 可选写入 .env 文件（当前或全局）

命令：
  agentos init                 # 交互式引导
  agentos init --quick         # 跳过问答，直接生成 .env.example
  agentos init --reset         # 重置配置

### 函数

| 函数 | 签名 |
|------|------|
| `load_config` | `def () -> dict` |
| `config_status_text` | `def () -> str` |
| `init_cli` | `def (args: list[str]) -> None` |
| `scaffold` | `def (project_dir: str, template: str) -> list[str]` |

---

## cli.main

AgentOS v1.0 CLI — New ToolAgent + LLM Provider backend。

### 函数

| 函数 | 签名 |
|------|------|
| `main` | `def () -> None` |

---

## cli.serve

v0.80 — `agentos serve` API 服务器启动器。

### 类

#### `ServeConfig`

API 服务配置。

### 函数

| 函数 | 签名 |
|------|------|
| `start_api_server` | `def (config: ServeConfig | None) -> None` |
| `async start_api_server_async` | `async def (config: ServeConfig | None) -> None` |

---

## concurrency.batch

AsyncBatchExecutor — Concurrent agent task dispatch with configurable
parallelism, timeout, retry, and result aggregation.

Designed for running multiple AgentOS tasks in parallel (e.g., batch
evaluation, multi-model comparison, bulk processing).

### 类

#### `TaskStatus(Enum)`

任务状态枚举。

#### `BatchStrategy(Enum)`

Execution strategy for batch tasks.

#### `TaskSpec`

Specification for a single task in a batch.

#### `TaskResult`

Result of a single task execution.

| 方法 | 签名 |
|------|------|
| `success` | `def (self) -> bool` |

#### `BatchConfig`

Configuration for AsyncBatchExecutor.

#### `BatchResult`

Aggregated result of a batch execution.

| 方法 | 签名 |
|------|------|
| `success_rate` | `def (self) -> float` |
| `all_success` | `def (self) -> bool` |
| `get_failed_ids` | `def (self) -> List[str]` |

#### `AsyncBatchExecutor`

Concurrently dispatches multiple AgentOS tasks and aggregates results.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[BatchConfig]) -> None` |
| `execute` | `async def (self, tasks: List[TaskSpec]) -> BatchResult` |
| `cancel_all` | `def (self) -> None` |

---

## protocols.a2a

AgentOS v1.2.2 — A2A (Agent-to-Agent) 协议实现。

基因来源: Google A2A Protocol (agent-to-agent-protocol.google.com)

A2A 协议核心概念:
- Task: 异步工作单元，带状态机 (SUBMITTED→WORKING→COMPLETED/FAILED/CANCELLED)
- Message: 多模态消息，支持 text/file/data parts
- Artifact: 任务产生的输出物，带 MIME 类型
- Handoff: Agent 间任务移交
- Session: 多轮对话上下文

协议层:
- REST: GET/POST /tasks, /tasks/{id}
- Future: WebSocket 推送 (v1.3+)

### 类

#### `TaskState(str, Enum)`

A2A 任务状态。

#### `PartType(str, Enum)`

A2A 内容片段类型。

#### `MessageRole(str, Enum)`

A2A 消息角色。

#### `TextPart`

文本消息片段。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `@classmethod from_dict` | `def (cls, d: dict) -> 'TextPart'` |

#### `FilePart`

文件引用消息片段。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `@classmethod from_dict` | `def (cls, d: dict) -> 'FilePart'` |

#### `DataPart`

结构化数据消息片段。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `@classmethod from_dict` | `def (cls, d: dict) -> 'DataPart'` |

#### `A2AArtifact`

任务产出物。
可以是内联数据 (blob) 或外部引用 (url)。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `@classmethod from_dict` | `def (cls, d: dict) -> 'A2AArtifact'` |

#### `A2AMessage`

多模态消息。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `@classmethod from_dict` | `def (cls, d: dict) -> 'A2AMessage'` |
| `@classmethod user_text` | `def (cls, text: str) -> 'A2AMessage'` |
| `@classmethod agent_text` | `def (cls, text: str) -> 'A2AMessage'` |
| `get_text` | `def (self) -> str` |

#### `A2ATask`

A2A 异步任务。

状态机: SUBMITTED → WORKING → COMPLETED / FAILED / CANCELLED

| 方法 | 签名 |
|------|------|
| `start_working` | `def (self) -> None` |
| `complete` | `def (self, output: A2AMessage | None) -> None` |
| `fail` | `def (self, error: str) -> None` |
| `cancel` | `def (self) -> None` |
| `add_artifact` | `def (self, artifact: A2AArtifact) -> None` |
| `is_terminal` | `def (self) -> bool` |
| `to_dict` | `def (self) -> dict` |
| `@classmethod from_dict` | `def (cls, d: dict) -> 'A2ATask'` |
| `to_json` | `def (self) -> str` |
| `@classmethod from_json` | `def (cls, json_str: str) -> 'A2ATask'` |

#### `A2AHandoff`

Agent 间任务移交请求。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `@classmethod from_dict` | `def (cls, d: dict) -> 'A2AHandoff'` |
| `to_json` | `def (self) -> str` |
| `@classmethod from_json` | `def (cls, json_str: str) -> 'A2AHandoff'` |

#### `A2ASession`

A2A 会话上下文。

| 方法 | 签名 |
|------|------|
| `add_message` | `def (self, msg: A2AMessage) -> None` |
| `add_task` | `def (self, task: A2ATask) -> None` |
| `get_last_n_messages` | `def (self, n: int) -> List[A2AMessage]` |
| `to_dict` | `def (self) -> dict` |

#### `A2AClient`

A2A 协议客户端。

向远程 Agent 发送任务，查询状态，获取结果。

v1.3.13: 重试 + 认证头 + 流式订阅 + 持久化连接池。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, base_url: str, timeout: float, max_retries: int, retry_backoff: float, auth_t` |
| `close` | `async def (self) -> None` |
| `send_task` | `async def (self, task: A2ATask) -> A2ATask` |
| `get_task` | `async def (self, task_id: str) -> Optional[A2ATask]` |
| `cancel_task` | `async def (self, task_id: str) -> bool` |
| `handoff` | `async def (self, handoff: A2AHandoff) -> bool` |
| `wait_for_completion` | `async def (self, task_id: str, poll_interval: float, max_wait: float) -> A2ATask` |
| `send_and_wait_for_reply` | `async def (self, text: str, target_agent: str, poll_interval: float, max_wait: float) ->` |
| `subscribe_task_stream` | `async def (self, task_id: str, on_event: Callable[[dict], Any] | None) -> None` |

#### `A2AServer`

A2A 协议服务端。

接收并处理 Agent 间任务请求。

使用方式:
    server = A2AServer()
    server.register_handler("my-agent", my_handler)
    # 集成到 FastAPI:
    app = FastAPI()
    server.mount_routes(app)

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, task_store, stream_manager, require_auth: bool, auth_tokens: List[str] | None` |
| `task_store` | `def (self) -> None` |
| `register_handler` | `def (self, agent_name: str, handler: Callable) -> None` |
| `process_task` | `async def (self, body: dict, auth_token: str) -> dict` |
| `get_task` | `def (self, task_id: str) -> Optional[A2ATask]` |
| `list_tasks` | `def (self, state: TaskState | None) -> list[A2ATask]` |
| `cleanup_old` | `def (self, max_age_seconds: float) -> int` |
| `mount_routes` | `def (self, app, prefix: str) -> None` |

### 函数

| 函数 | 签名 |
|------|------|
| `part_from_dict` | `def (d: dict) -> None` |
| `new_task` | `def (text: str, target_agent: str, **meta) -> A2ATask` |
| `new_handoff` | `def (task: A2ATask, source: str, target: str, reason: str) -> A2AHandoff` |

---

## protocols.a2a_store

A2A Task Store — persistent task and session storage for A2A protocol.

Backends: InMemory (default), SQLite, custom.

### 类

#### `A2ATaskStore(ABC)`

Abstract task store for A2A protocol persistence.

| 方法 | 签名 |
|------|------|
| `save_task` | `def (self, task: A2ATask) -> None` |
| `get_task` | `def (self, task_id: str) -> Optional[A2ATask]` |
| `list_tasks` | `def (self, state: TaskState | None, limit: int, offset: int, agent: str) -> list[A2ATask` |
| `delete_task` | `def (self, task_id: str) -> bool` |
| `cleanup_terminal` | `def (self, max_age_seconds: float) -> int` |
| `count` | `def (self, state: TaskState | None) -> int` |

#### `InMemoryTaskStore(A2ATaskStore)`

Fast, non-persistent task store for development/testing.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `save_task` | `def (self, task: A2ATask) -> None` |
| `get_task` | `def (self, task_id: str) -> Optional[A2ATask]` |
| `list_tasks` | `def (self, state: TaskState | None, limit: int, offset: int, agent: str) -> list[A2ATask` |
| `delete_task` | `def (self, task_id: str) -> bool` |
| `cleanup_terminal` | `def (self, max_age_seconds: float) -> int` |
| `count` | `def (self, state: TaskState | None) -> int` |

#### `SqliteTaskStore(A2ATaskStore)`

Persistent SQLite-backed task store for production use.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, db_path: str) -> None` |
| `save_task` | `def (self, task: A2ATask) -> None` |
| `get_task` | `def (self, task_id: str) -> Optional[A2ATask]` |
| `list_tasks` | `def (self, state: TaskState | None, limit: int, offset: int, agent: str) -> list[A2ATask` |
| `delete_task` | `def (self, task_id: str) -> bool` |
| `cleanup_terminal` | `def (self, max_age_seconds: float) -> int` |
| `count` | `def (self, state: TaskState | None) -> int` |

---

## protocols.a2a_streaming

A2A Streaming — real-time task status updates via SSE for A2A protocol.

Provides push-based task lifecycle notifications so agents don't poll.

### 类

#### `A2AStreamEvent(str, Enum)`

A2A-specific streaming event types.

#### `TaskProgress`

Progress update within a running task.

#### `A2AStreamSession`

Manages a streaming connection for a single task.

Agents subscribe to receive push updates as the task progresses.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, task: A2ATask) -> None` |
| `start` | `async def (self, heartbeat_s: float) -> None` |
| `subscribe` | `def (self) -> asyncio.Queue[dict]` |
| `unsubscribe` | `def (self, sub: asyncio.Queue) -> None` |
| `emit` | `async def (self, event: A2AStreamEvent, data: dict | None) -> None` |
| `close` | `async def (self) -> None` |
| `iter_events` | `async def (self, subscriber: asyncio.Queue) -> AsyncIterator[dict]` |
| `to_sse` | `def (self, event: dict) -> str` |

#### `A2AStreamManager`

Global manager for A2A task streaming sessions.

Tracks all active task streams and dispatches events on state transitions.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `on_state_change` | `def (self, callback: Callable[[A2ATask, TaskState, TaskState], Any]) -> None` |
| `create_session` | `def (self, task: A2ATask) -> A2AStreamSession` |
| `get_session` | `def (self, task_id: str) -> Optional[A2AStreamSession]` |
| `notify_state_change` | `async def (self, task: A2ATask, old_state: TaskState) -> None` |
| `notify_artifact` | `async def (self, task_id: str, artifact_name: str) -> None` |
| `notify_progress` | `async def (self, task_id: str, progress: TaskProgress) -> None` |
| `shutdown` | `async def (self) -> None` |

---

## protocols.agent_card

AgentOS v1.2.0 — Agent Card 服务发现协议。

基因来源: Google A2A (Agent-to-Agent) Agent Card 规范

Agent Card 是标准化的 Agent 自描述卡片，支持:
- 发布/发现: Agent 发布自身能力，其他 Agent 按需发现
- 能力匹配: 按 domain / capability / keyword 搜索匹配
- 本地+远程: 文件系统本地发现 + HTTP 端点远程发现
- JSON 序列化: 完整的 export/import 往返，兼容 A2A 生态

### 类

#### `AgentCard`

Agent 自描述卡片，A2A 兼容。

使用方式:
    card = AgentCard(
        name="data-analyzer",
        description="数据分析Agent，支持SQL/Pandas/可视化",
        version="1.0.0",
        url="http://localhost:8000/agent",
        capabilities=["analysis", "coding"],
        skills=["sql-query", "pandas-transform", "chart-generate"],
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
    )

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> Dict[str, Any]` |
| `to_json` | `def (self, indent: int) -> str` |
| `@classmethod from_dict` | `def (cls, data: Dict[str, Any]) -> 'AgentCard'` |
| `@classmethod from_json` | `def (cls, json_str: str) -> 'AgentCard'` |
| `matches_query` | `def (self, query: str) -> bool` |
| `has_capability` | `def (self, capability: str) -> bool` |
| `has_skill` | `def (self, skill: str) -> bool` |
| `has_tag` | `def (self, tag: str) -> bool` |

#### `AgentCardRegistry`

Agent Card 注册中心。

支持注册、注销、搜索、过滤。

| 方法 | 签名 |
|------|------|
| `register` | `def (self, card: AgentCard) -> None` |
| `unregister` | `def (self, name: str) -> Optional[AgentCard]` |
| `get` | `def (self, name: str) -> Optional[AgentCard]` |
| `list_all` | `def (self) -> List[AgentCard]` |
| `find_by_query` | `def (self, query: str) -> List[AgentCard]` |
| `find_by_capability` | `def (self, capability: str) -> List[AgentCard]` |
| `find_by_skill` | `def (self, skill: str) -> List[AgentCard]` |
| `find_by_tag` | `def (self, tag: str) -> List[AgentCard]` |
| `export_all` | `def (self, filepath: str) -> None` |
| `import_from_file` | `def (self, filepath: str) -> int` |
| `@classmethod from_file` | `def (cls, filepath: str) -> 'AgentCardRegistry'` |

#### `AgentCardDiscovery`

Agent Card 远程发现器。

通过 HTTP GET 获取远程 Agent 的 /agent-card 端点。

| 方法 | 签名 |
|------|------|
| `@staticmethod fetch` | `async def (url: str, timeout: float) -> Optional[AgentCard]` |
| `@staticmethod fetch_all` | `async def (urls: List[str], timeout: float) -> Dict[str, Optional[AgentCard]]` |

### 函数

| 函数 | 签名 |
|------|------|
| `create_card` | `def (name: str, description: str, version: str, url: str, capabilities: List[str] | None` |
| `discover_local` | `def (directory: str, pattern: str) -> List[AgentCard]` |

---

## protocols.contracts

AgentOS v0.70 — Agent能力契约与发现协议。
基因来源: MCP (Model Context Protocol) + OpenAPI Spec

契约系统允许Agent声明自己的能力和限制，其他Agent可以通过
能力匹配引擎找到合适的Agent协作。

契约格式:
- AgentCapability: 单个能力描述（名称、描述、输入输出schema）
- AgentContract: Agent的完整契约（身份、能力列表、QoS、限制）
- CapabilityMatcher: 能力匹配引擎

### 类

#### `CapabilityDomain(str, Enum)`

能力域枚举。

#### `QoSLevel(str, Enum)`

服务质量等级。

#### `AgentCapability`

单个能力声明。

#### `AgentContract`

Agent完整契约 — 身份 + 能力 + 限制。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `has_capability` | `def (self, name: str) -> bool` |
| `has_domain` | `def (self, domain: CapabilityDomain) -> bool` |

#### `MatchScore`

匹配评分结果。

#### `CapabilityMatcher`

能力匹配引擎 — 根据查询找到最合适的Agent。
支持: 语义匹配、标签匹配、领域匹配、QoS权重。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, contracts: list[AgentContract] | None) -> None` |
| `register` | `def (self, contract: AgentContract) -> None` |
| `unregister` | `def (self, agent_id: str) -> None` |
| `find` | `def (self, query: str, domain: CapabilityDomain | None, min_score: float, top_k: int) ->` |
| `find_by_domain` | `def (self, domain: CapabilityDomain) -> list[AgentContract]` |
| `find_by_tag` | `def (self, tag: str) -> list[AgentContract]` |
| `recommend_for_task` | `def (self, task_description: str) -> list[MatchScore]` |

#### `ContractRegistry`

契约注册中心 — 分布式Agent能力发现。
支持心跳检测、自动过期。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `register` | `def (self, contract: AgentContract) -> None` |
| `heartbeat` | `def (self, agent_id: str) -> None` |
| `unregister` | `def (self, agent_id: str) -> None` |
| `prune_stale` | `def (self, max_idle_seconds: float) -> None` |
| `find` | `def (self, query: str, **kwargs) -> list[MatchScore]` |
| `active_count` | `def (self) -> int` |
| `list_contracts` | `def (self) -> list[AgentContract]` |
| `summary` | `def (self) -> str` |

---

## protocols.mcp

AgentOS v0.20 MCP (Model Context Protocol) 客户端。
支持 stdio / SSE / WebSocket 三种传输方式。

### 类

#### `MCPServerConfig`

MCP 服务端配置。

#### `MCPToolSchema`

MCP 工具 Schema。

#### `MCPTransport(ABC)`

MCP 传输协议。

| 方法 | 签名 |
|------|------|
| `connect` | `async def (self, config: MCPServerConfig) -> None` |
| `send` | `async def (self, method: str, params: dict | None) -> dict` |
| `close` | `async def (self) -> None` |

#### `StdioTransport(MCPTransport)`

通过 subprocess 与 MCP Server 通信。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `connect` | `async def (self, config: MCPServerConfig) -> None` |
| `send` | `async def (self, method: str, params: dict | None) -> dict` |
| `close` | `async def (self) -> None` |

#### `SSETransport(MCPTransport)`

通过 HTTP SSE 与远程 MCP Server 通信。

| 方法 | 签名 |
|------|------|
| `connect` | `async def (self, config: MCPServerConfig) -> None` |
| `send` | `async def (self, method: str, params: dict | None) -> dict` |
| `close` | `async def (self) -> None` |

#### `MCPClient`

MCP 协议客户端，管理多个 MCP Server 连接。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `connect_server` | `async def (self, config: MCPServerConfig) -> None` |
| `call_tool` | `async def (self, full_name: str, arguments: dict) -> Any` |
| `get_mcp_tool_schemas` | `def (self) -> list[dict]` |
| `close_all` | `async def (self) -> None` |

---

## protocols.output

Structured output validation for NexusAgent.

Provides Pydantic-style output validation for agents.
When Agent[Deps, Out] has Out as a Pydantic BaseModel,
the output is automatically validated.

### 类

#### `StructuredOutput(BaseModel if PYDANTIC_AVAILABLE else object)`

Agent 结构化输出。

#### `ValidationResult(Generic[T])`

Result of output validation.

Attributes:
    success: Whether validation passed
    output: Validated output (if success)
    error: Validation error (if failed)

#### `OutputValidator(Generic[T])`

Validator for structured outputs.

Usage:
    validator = OutputValidator(MyOutput)
    result = validator.validate({"answer": "42", "confidence": 0.9})
    if result.success:
        output = result.output  # MyOutput instance

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, output_type: type[T]) -> None` |
| `validate` | `def (self, data: Any) -> ValidationResult[T]` |
| `validate_or_raise` | `def (self, data: Any) -> T` |

### 函数

| 函数 | 签名 |
|------|------|
| `validate_output` | `def (output_type: type[T], data: Any) -> ValidationResult[T]` |
| `get_output_type` | `def (agent_class: type) -> type | None` |

---

## subagent.collaboration

Agent 协作模式 — Debate/Vote/Review/Pipeline/Ensemble。
基于 SubAgentManager + 父子通信之上，提供高级多Agent协作原语。

使用示例::

    mgr = SubAgentManager()
    collab = AgentCollaboration(mgr)

    result = await collab.debate("Python vs Rust for web backend", agents=2)
    result = await collab.vote(["方案A", "方案B", "方案C"], agents=5)
    result = await collab.review("写一篇关于AI安全的文章", rounds=2)
    result = await collab.pipeline("分析Q2财报数据", stages=3)
    result = await collab.ensemble("设计系统架构方案", agents=3)

### 类

#### `CollaborationMode(str, Enum)`

#### `VoteStrategy(str, Enum)`

#### `DebateRound`

一轮辩论。

#### `VoteBallot`

一张选票。

#### `ReviewPass`

一轮审查。

#### `CollaborationResult`

协作结果。

#### `AgentCollaboration`

多Agent协作引擎。

参数:
    manager: SubAgentManager 实例
    run_func: 执行函数 (task_str, ctx) -> (output, iterations)
    default_timeout: 每个子Agent默认超时（秒）

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, manager: SubAgentManager | None, run_func: Callable[[SubAgentSpec, ChildConte` |
| `manager` | `def (self) -> SubAgentManager` |
| `shared_state` | `def (self) -> SharedState` |
| `cancel_all` | `async def (self) -> None` |
| `active_agents` | `def (self) -> int` |
| `debate` | `async def (self, topic: str, agents: int, rounds: int, timeout: float | None) -> Collabo` |
| `vote` | `async def (self, options: list[str], agents: int, strategy: VoteStrategy, timeout: float` |
| `review` | `async def (self, task: str, rounds: int, timeout: float | None) -> CollaborationResult` |
| `pipeline` | `async def (self, task: str, stages: int, stage_names: list[str] | None, timeout: float |` |
| `ensemble` | `async def (self, task: str, agents: int, merge_strategy: str, timeout: float | None) -> ` |

---

## subagent.manager

子Agent管理 — Fork隔离 + Swarm并行 + A2A委派 + 父子通信。
基因来源: Claude Code (Fork) + Cursor (Swarm)
v1.3.15: +Parent-Child 通信（状态共享、心跳、生命周期）

### 类

#### `SubAgentMode(str, Enum)`

子 Agent 模式枚举。

#### `SubAgentSpec`

子 Agent 规格。

#### `SubAgentResult`

子 Agent 执行结果。

| 方法 | 签名 |
|------|------|
| `summarize` | `def (self) -> str` |

#### `SubAgentManager`

子Agent管理器 — Fork/Swarm/A2A + 父子通信。

用法::

    mgr = SubAgentManager()

    # Fork 模式
    result = await mgr.spawn_fork("分析这份报告")

    # Swarm 模式
    results = await mgr.spawn_swarm(["任务A", "任务B"])

    # 管控子Agent
    handle = mgr.get_handle(result.agent_id)
    await handle.pause()
    await handle.resume()
    await handle.cancel()
    status = handle.get_status()

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `shared_state` | `def (self) -> SharedState` |
| `active_children` | `def (self) -> int` |
| `get_handle` | `def (self, agent_id: str) -> ChildHandle | None` |
| `list_children` | `def (self) -> list[dict[str, Any]]` |
| `cancel_all` | `async def (self) -> None` |
| `spawn_fork` | `async def (self, task: str, model: str, run_func: Callable[[SubAgentSpec, ChildContext],` |
| `spawn_swarm` | `async def (self, tasks: list[str], model: str, run_func: Callable[[SubAgentSpec, ChildCo` |
| `split_task` | `def (self, task: str) -> list[str]` |
| `monitor_heartbeats` | `async def (self, interval: float) -> None` |
| `cleanup` | `async def (self, max_age_seconds: float) -> int` |

---

## subagent.parent_child

子Agent父子通信 — 状态共享、心跳、生命周期管理。
父Agent通过 ChildHandle 管控子Agent；子Agent通过 ChildContext 向父Agent报告。

### 类

#### `ChildStatus(str, Enum)`

子Agent运行状态。

#### `ChildHeartbeat`

子Agent心跳包。

#### `ChildInfo`

子Agent元信息（父Agent侧）。

#### `SharedState`

父子共享状态（线程安全）。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `set` | `async def (self, key: str, value: Any) -> None` |
| `get` | `async def (self, key: str, default: Any) -> Any` |
| `update` | `async def (self, mapping: dict[str, Any]) -> None` |
| `snapshot` | `async def (self) -> dict[str, Any]` |
| `set_sync` | `def (self, key: str, value: Any) -> None` |
| `get_sync` | `def (self, key: str, default: Any) -> Any` |

#### `ChildContext`

子Agent视角 — 向父Agent报告状态、检查控制信号。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, agent_id: str, heartbeat_callback: Callable[[ChildHeartbeat], Awaitable[None]` |
| `cancelled` | `def (self) -> bool` |
| `paused` | `def (self) -> bool` |
| `progress` | `def (self) -> float` |
| `report_progress` | `async def (self, progress: float, step: str, message: str) -> None` |
| `step` | `async def (self, iteration: int, step: str) -> None` |
| `check_control` | `async def (self) -> ChildStatus` |
| `send_heartbeat` | `async def (self, message: str) -> None` |
| `done` | `async def (self, output: str) -> None` |
| `fail` | `async def (self, error: str) -> None` |

#### `ChildHandle`

父Agent视角 — 管控一个子Agent。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, agent_id: str, task: str, mode: str, timeout: float | None, heartbeat_interva` |
| `agent_id` | `def (self) -> str` |
| `status` | `def (self) -> ChildStatus` |
| `create_context` | `def (self) -> ChildContext` |
| `cancel` | `async def (self) -> None` |
| `pause` | `async def (self) -> None` |
| `resume` | `async def (self) -> None` |
| `check_timeout` | `def (self) -> bool` |
| `check_heartbeat_timeout` | `def (self) -> bool` |
| `get_status` | `def (self) -> dict[str, Any]` |

---

## deployment.docker

AgentOS deployment — Docker and orchestration helpers.

### 类

#### `DockerConfig`

Docker 部署配置。

#### `ComposeService`

Compose 服务定义。

#### `ComposeConfig`

Compose 编排配置。

### 函数

| 函数 | 签名 |
|------|------|
| `generate_dockerfile` | `def (config: Optional[DockerConfig]) -> str` |
| `generate_docker_compose` | `def (config: ComposeConfig) -> str` |
| `write_deployment_files` | `def (output_dir: str | Path, docker_config: Optional[DockerConfig], compose_config: Opti` |

---

## config.loader

AgentOS v0.80 统一配置系统。
v0.80新增: BenchmarkCfg。
v0.70基线: PluginsCfg, GeminiCfg, ContractsCfg, OrchestratorCfg, ScorerCfg。
v0.60基线: GuardrailsCfg, RateLimitCfg, StateMachineCfg, ResilienceCfg。

### 类

#### `ModelConfig`

LLM 模型配置。

#### `LoopCfg`

Agent 主循环配置。

#### `MemoryCfg`

记忆系统配置。

#### `SecurityCfg`

安全策略配置。

#### `ObservabilityCfg`

可观测性配置。

#### `MCPServersCfg`

MCP 服务器列表配置。

#### `ReflectionCfg`

反思循环配置。

#### `CostCfg`

成本控制配置。

#### `FeedbackCfg`

反馈回路配置。

#### `APICfg`

API 服务配置。

#### `SwarmCfg`

Swarm 多 Agent 协作配置。

#### `QueueCfg`

任务队列配置。

#### `CacheCfg`

语义缓存配置。

#### `ExperimentCfg`

A/B 实验配置。

#### `MultimodalCfg`

多模态处理配置。

#### `MCPServerCfg`

MCP 服务端配置。

#### `GuardrailsCfg`

安全护栏配置。

#### `RateLimitCfg`

限流配置。

#### `StateMachineCfg`

状态机配置。

#### `ResilienceCfg`

弹性容错配置。

#### `PluginsCfg`

插件系统配置。

#### `GeminiCfg`

Gemini 模型配置。

#### `ContractsCfg`

能力契约配置。

#### `OrchestratorCfg`

编排器配置。

#### `ScorerCfg`

评分器配置。

#### `BenchmarkCfg`

性能基准配置。

#### `HealthCfg`

健康检查配置。

#### `AuditCfg`

安全审计配置。

#### `DeployCfg`

部署配置。

#### `MiddlewareCfg`

中间件配置。

#### `AgentOSConfig`

AgentOS v0.90 总配置。

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |

### 函数

| 函数 | 签名 |
|------|------|
| `load_config` | `def (path: str | None) -> AgentOSConfig` |

---

## config.presets

Config Presets — Ready-to-use configuration profiles for common AgentOS scenarios.

Each preset provides sensible defaults for specific use cases:
development, production, testing, and budget-constrained environments.

### 类

#### `AgentOSPreset`

A named preset configuration for AgentOS.

### 函数

| 函数 | 签名 |
|------|------|
| `get_preset` | `def (name: str) -> Optional[AgentOSPreset]` |
| `list_presets` | `def () -> list[AgentOSPreset]` |
| `get_preset_names` | `def () -> list[str]` |
| `apply_preset` | `def (preset_name: str, config: dict) -> dict` |

---

## config.validator

AgentOS configuration validation — JSON Schema-based config integrity checks.

Validates agentos.yaml and environment configurations at startup and reload.

### 类

#### `ValidationLevel(Enum)`

校验等级。

#### `ValidationIssue`

校验问题。

#### `ValidationResult`

校验结果。

| 方法 | 签名 |
|------|------|
| `errors` | `def (self) -> list[ValidationIssue]` |
| `warnings` | `def (self) -> list[ValidationIssue]` |
| `add_error` | `def (self, path: str, message: str) -> None` |
| `add_warning` | `def (self, path: str, message: str) -> None` |
| `__str__` | `def (self) -> str` |

### 函数

| 函数 | 签名 |
|------|------|
| `validate_config` | `def (config: dict, schema: Optional[dict]) -> ValidationResult` |
| `validate_config_file` | `def (file_path: str) -> ValidationResult` |
| `generate_schema_json` | `def () -> str` |

---

## monitoring.alerts

AgentOS monitoring — alert rules and webhook notification dispatcher.

### 类

#### `AlertSeverity(str, Enum)`

告警实例。

#### `AlertState(str, Enum)`

告警状态。

#### `AlertRule`

告警规则。

| 方法 | 签名 |
|------|------|
| `evaluate` | `def (self) -> bool` |

#### `Alert`

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict` |
| `to_json` | `def (self) -> str` |

#### `MonitoringConfig`

监控配置。

#### `WebhookConfig`

Webhook 配置。

#### `WebhookDispatcher`

Dispatches Alerts to configured webhook endpoints.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[WebhookConfig]) -> None` |
| `send` | `def (self, alert: Alert) -> bool` |

#### `AlertEvaluator`

Evaluates AlertRules and generates Alerts.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[MonitoringConfig]) -> None` |
| `add_rule` | `def (self, rule: AlertRule) -> None` |
| `evaluate` | `def (self) -> list[Alert]` |

---

## guardrails.engine

Guardrail engine — rule registry, evaluation, and result aggregation.

### 类

#### `GuardrailAction(str, Enum)`

Guardrail disposition for a single rule match.

#### `GuardrailCategory(str, Enum)`

Semantic category of a guardrail rule.

#### `GuardrailResult`

Aggregate result after all guardrails have been evaluated.

| 方法 | 签名 |
|------|------|
| `blocked` | `def (self) -> bool` |

#### `GuardrailRule`

A single guardrail rule definition.

#### `InputGuardrail`

Validates user prompts before they reach the LLM.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, rules: Optional[list[GuardrailRule]]) -> None` |
| `add_rule` | `def (self, rule: GuardrailRule) -> None` |
| `remove_rule` | `def (self, name: str) -> None` |
| `evaluate` | `def (self, text: str) -> GuardrailResult` |

#### `OutputGuardrail`

Validates LLM outputs before they reach the user.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, rules: Optional[list[GuardrailRule]]) -> None` |
| `add_rule` | `def (self, rule: GuardrailRule) -> None` |
| `remove_rule` | `def (self, name: str) -> None` |
| `evaluate` | `def (self, text: str) -> GuardrailResult` |

#### `GuardrailEngine`

Unified guardrail engine managing both input and output pipelines.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, input_rules: Optional[list[GuardrailRule]], output_rules: Optional[list[Guard` |
| `check_input` | `def (self, prompt: str) -> GuardrailResult` |
| `check_output` | `def (self, response: str) -> GuardrailResult` |
| `check` | `def (self, prompt: str, response: str) -> tuple[GuardrailResult, GuardrailResult]` |

---

## guardrails.policy

Guardrail policy enforcement — cumulative violation tracking, rate limiting,
and session-scoped policy decisions.

### 类

#### `PolicyViolation(str, Enum)`

Policy-level violation reasons.

#### `GuardrailPolicy`

Session-scoped policy configuration.

#### `PolicyEnforcer`

Tracks violations per session and enforces cumulative policy.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, policy: Optional[GuardrailPolicy]) -> None` |
| `evaluate` | `def (self, result: GuardrailResult, category: str) -> PolicyViolation | None` |
| `reset` | `def (self) -> None` |
| `is_blocked` | `def (self) -> bool` |
| `total_violations` | `def (self) -> int` |

---

## guardrails.rules

Built-in guardrail rules — PII detection, keyword blocking, length limits, regex,
toxicity heuristics, and code injection detection.

### 函数

| 函数 | 签名 |
|------|------|
| `PIIRule` | `def (name: str, action: GuardrailAction, enabled: bool) -> GuardrailRule` |
| `KeywordBlockRule` | `def (keywords: list[str], name: str, case_sensitive: bool, enabled: bool) -> GuardrailRu` |
| `LengthLimitRule` | `def (max_input: int, max_output: int, name: str, enabled: bool) -> GuardrailRule` |
| `RegexRule` | `def (pattern: str, name: str, action: GuardrailAction, description: str, enabled: bool) ` |
| `ToxicityRule` | `def (name: str, action: GuardrailAction, enabled: bool) -> GuardrailRule` |
| `CodeInjectionRule` | `def (name: str, action: GuardrailAction, enabled: bool) -> GuardrailRule` |
| `build_default_rules` | `def (blocked_keywords: list[str] | None, max_input_length: int, max_output_length: int) ` |

---

## benchmarks.runner

v0.80 — 性能基准测试运行器：延迟/吞吐/并发。

### 类

#### `BenchmarkScenario`

单个基准测试场景。

#### `BenchmarkConfig`

基准测试配置。

#### `BenchmarkReport`

基准测试报告。

| 方法 | 签名 |
|------|------|
| `to_json` | `def (self) -> str` |
| `to_markdown` | `def (self) -> str` |

#### `BenchmarkRunner`

基准测试运行器。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: BenchmarkConfig | None) -> None` |
| `run` | `async def (self, scenario: BenchmarkScenario, callable_fn: Callable[[], Any], async_call` |

### 函数

| 函数 | 签名 |
|------|------|
| `async run_benchmark` | `async def (scenario_name: str, callable_fn: Callable[[], Any], config: BenchmarkConfig |` |

---

## tests.test_1_1_4_features

v1.1.4 新特性集成测试。

### 类

#### `TestToolRiskRating`

| 方法 | 签名 |
|------|------|
| `test_risk_level_enum` | `def (self) -> None` |
| `test_risk_rating_defaults` | `def (self) -> None` |
| `test_requires_confirm_high` | `def (self) -> None` |
| `test_requires_confirm_critical` | `def (self) -> None` |
| `test_requires_confirm_financial` | `def (self) -> None` |
| `test_get_risk_preset_list_files` | `def (self) -> None` |
| `test_get_risk_preset_delete_file` | `def (self) -> None` |
| `test_get_risk_preset_payment` | `def (self) -> None` |
| `test_get_risk_preset_case_insensitive` | `def (self) -> None` |
| `test_infer_risk_level_keyword_delete` | `def (self) -> None` |
| `test_infer_risk_level_keyword_write` | `def (self) -> None` |
| `test_infer_risk_level_default` | `def (self) -> None` |

#### `TestMiddlewarePipeline`

| 方法 | 签名 |
|------|------|
| `test_empty_pipeline_allows` | `async def (self) -> None` |
| `test_blocking_middleware` | `async def (self) -> None` |
| `test_transform_middleware` | `async def (self) -> None` |
| `test_chain_add` | `async def (self) -> None` |
| `test_remove` | `async def (self) -> None` |
| `test_phase_filtering` | `async def (self) -> None` |

#### `TestRunCostSession`

| 方法 | 签名 |
|------|------|
| `test_session_lifecycle` | `def (self) -> None` |
| `test_total_tokens` | `def (self) -> None` |

#### `TestCostTrackerEnhanced`

| 方法 | 签名 |
|------|------|
| `test_start_end_session` | `def (self) -> None` |
| `test_record_with_session` | `def (self) -> None` |
| `test_cost_by_session` | `def (self) -> None` |
| `test_get_session_active_and_completed` | `def (self) -> None` |
| `test_record_with_cache` | `def (self) -> None` |

---

## tests.test_a2a

测试 A2A 协议 — Task, Message, Handoff, Client, Server。

### 类

#### `TestA2AParts`

| 方法 | 签名 |
|------|------|
| `test_text_part_roundtrip` | `def (self) -> None` |
| `test_file_part_roundtrip` | `def (self) -> None` |
| `test_data_part_roundtrip` | `def (self) -> None` |
| `test_part_from_dict_dispatcher` | `def (self) -> None` |

#### `TestA2AArtifact`

| 方法 | 签名 |
|------|------|
| `test_roundtrip` | `def (self) -> None` |
| `test_url_artifact` | `def (self) -> None` |

#### `TestA2AMessage`

| 方法 | 签名 |
|------|------|
| `test_user_text` | `def (self) -> None` |
| `test_agent_text` | `def (self) -> None` |
| `test_multipart_roundtrip` | `def (self) -> None` |

#### `TestA2ATask`

| 方法 | 签名 |
|------|------|
| `test_lifecycle` | `def (self) -> None` |
| `test_fail` | `def (self) -> None` |
| `test_cancel` | `def (self) -> None` |
| `test_cannot_start_non_submitted` | `def (self) -> None` |
| `test_cannot_complete_non_working` | `def (self) -> None` |
| `test_cannot_cancel_completed` | `def (self) -> None` |
| `test_artifact_attachment` | `def (self) -> None` |
| `test_json_roundtrip` | `def (self) -> None` |
| `test_state_history` | `def (self) -> None` |

#### `TestA2AHandoff`

| 方法 | 签名 |
|------|------|
| `test_roundtrip` | `def (self) -> None` |
| `test_json_roundtrip` | `def (self) -> None` |

#### `TestA2ASession`

| 方法 | 签名 |
|------|------|
| `test_basic` | `def (self) -> None` |
| `test_get_last_n` | `def (self) -> None` |

#### `TestA2Server`

| 方法 | 签名 |
|------|------|
| `test_process_task_success` | `async def (self) -> None` |
| `test_process_task_no_handler` | `async def (self) -> None` |
| `test_process_task_handler_error` | `async def (self) -> None` |
| `test_get_task` | `def (self) -> None` |
| `test_list_tasks_by_state` | `def (self) -> None` |
| `test_cleanup` | `def (self) -> None` |

#### `TestConvenience`

| 方法 | 签名 |
|------|------|
| `test_new_task` | `def (self) -> None` |
| `test_new_handoff` | `def (self) -> None` |

---

## tests.test_conversation

Tests for agentos.conversation.conversation.

### 函数

| 函数 | 签名 |
|------|------|
| `conv` | `def () -> None` |
| `test_add_message` | `def (conv) -> None` |
| `test_add_many` | `def (conv) -> None` |
| `test_get_context` | `def (conv) -> None` |
| `test_fifo_trim` | `def (conv) -> None` |
| `test_preserve_system` | `def (conv) -> None` |
| `test_token_tracking` | `def (conv) -> None` |
| `test_fork_and_switch` | `def (conv) -> None` |
| `test_fork_branch_not_found` | `def (conv) -> None` |
| `test_merge_branch_append` | `def (conv) -> None` |
| `test_clear` | `def (conv) -> None` |
| `test_clear_keep_system` | `def (conv) -> None` |
| `test_stats_tracking` | `def (conv) -> None` |
| `test_message_id_unique` | `def (conv) -> None` |
| `test_empty_context` | `def (conv) -> None` |
| `test_get_system_prompt` | `def (conv) -> None` |
| `test_importance_weighted_trim` | `def () -> None` |
| `test_trim_stats_increment` | `def (conv) -> None` |

---

## tests.test_guardrails

Tests for guardrails module — engine, rules, and policy enforcement.

### 类

#### `TestInputGuardrail`

| 方法 | 签名 |
|------|------|
| `test_no_rules_passes` | `def (self) -> None` |
| `test_single_rule_blocks` | `def (self) -> None` |
| `test_single_rule_passes_clean_text` | `def (self) -> None` |
| `test_disabled_rule_skipped` | `def (self) -> None` |
| `test_add_remove_rule` | `def (self) -> None` |

#### `TestOutputGuardrail`

| 方法 | 签名 |
|------|------|
| `test_output_passes` | `def (self) -> None` |
| `test_output_blocks` | `def (self) -> None` |

#### `TestGuardrailEngine`

| 方法 | 签名 |
|------|------|
| `test_both_pipelines` | `def (self) -> None` |
| `test_input_only` | `def (self) -> None` |

#### `TestPIIRule`

| 方法 | 签名 |
|------|------|
| `test_detects_email` | `def (self) -> None` |
| `test_sanitizes_email` | `def (self) -> None` |
| `test_no_pii_passes` | `def (self) -> None` |

#### `TestKeywordBlockRule`

| 方法 | 签名 |
|------|------|
| `test_case_insensitive_default` | `def (self) -> None` |
| `test_case_sensitive` | `def (self) -> None` |

#### `TestLengthLimitRule`

| 方法 | 签名 |
|------|------|
| `test_within_limit` | `def (self) -> None` |
| `test_exceeds_limit` | `def (self) -> None` |

#### `TestRegexRule`

| 方法 | 签名 |
|------|------|
| `test_custom_pattern` | `def (self) -> None` |

#### `TestCodeInjectionRule`

| 方法 | 签名 |
|------|------|
| `test_dan_prompt` | `def (self) -> None` |
| `test_system_tag_injection` | `def (self) -> None` |
| `test_sql_injection` | `def (self) -> None` |
| `test_eval_injection` | `def (self) -> None` |
| `test_normal_prompt_passes` | `def (self) -> None` |

#### `TestBuildDefaultRules`

| 方法 | 签名 |
|------|------|
| `test_returns_list` | `def (self) -> None` |
| `test_with_keywords` | `def (self) -> None` |

#### `TestPolicyEnforcer`

| 方法 | 签名 |
|------|------|
| `test_initial_state` | `def (self) -> None` |
| `test_single_violation_no_block` | `def (self) -> None` |
| `test_cumulative_block` | `def (self) -> None` |
| `test_category_block` | `def (self) -> None` |
| `test_reset` | `def (self) -> None` |
| `test_session_blocked_propagates` | `def (self) -> None` |

---

## tests.test_hitl

Tests for HITL (Human-in-the-Loop) approval module.

### 类

#### `TestApprovalRequest`

| 方法 | 签名 |
|------|------|
| `test_create_request` | `def (self) -> None` |

#### `TestApprovalDecision`

| 方法 | 签名 |
|------|------|
| `test_approved` | `def (self) -> None` |
| `test_modified_is_approved` | `def (self) -> None` |
| `test_rejected` | `def (self) -> None` |

#### `TestHumanInTheLoop`

| 方法 | 签名 |
|------|------|
| `test_low_risk_auto_skipped` | `def (self) -> None` |
| `test_high_risk_needs_approval` | `def (self) -> None` |
| `test_auto_approve_domain` | `def (self) -> None` |
| `test_blocked_domain` | `def (self) -> None` |
| `test_rejected_decision` | `def (self) -> None` |
| `test_history` | `def (self) -> None` |
| `test_pending_queue` | `def (self) -> None` |
| `test_approval_cache` | `def (self) -> None` |
| `test_critical_blocked_automatically` | `def (self) -> None` |
| `test_max_pending` | `def (self) -> None` |

#### `TestApprovalPresets`

| 方法 | 签名 |
|------|------|
| `test_default` | `def (self) -> None` |
| `test_permissive` | `def (self) -> None` |
| `test_strict` | `def (self) -> None` |

---

## tests.test_mcp

Tests for MCP client and tool adapter.

### 类

#### `TestMCPServerConfig`

Server configuration tests.

| 方法 | 签名 |
|------|------|
| `test_defaults` | `def (self) -> None` |
| `test_custom` | `def (self) -> None` |

#### `TestMCPClientLifecycle`

Client init and teardown tests (no real server needed).

| 方法 | 签名 |
|------|------|
| `test_init_empty` | `async def (self) -> None` |
| `test_context_manager` | `async def (self) -> None` |
| `test_connect_unknown_transport` | `async def (self) -> None` |
| `test_sse_requires_url` | `async def (self) -> None` |

#### `TestMCPToolAdapter`

Tool adapter wrapping tests.

| 方法 | 签名 |
|------|------|
| `test_adapt_tool_basic` | `def (self) -> None` |
| `test_to_openai_schema` | `def (self) -> None` |
| `test_to_anthropic_schema` | `def (self) -> None` |
| `test_write_operation_detection` | `def (self) -> None` |
| `test_read_operation_detection` | `def (self) -> None` |
| `test_extract_target_path` | `def (self) -> None` |
| `test_permission_default` | `def (self) -> None` |
| `test_permission_custom` | `def (self) -> None` |

#### `TestMCPToolRegistry`

Tool registry tests.

| 方法 | 签名 |
|------|------|
| `test_empty_registry` | `def (self) -> None` |
| `test_refresh` | `def (self) -> None` |

#### `TestMCPDataModels`

Data model tests.

| 方法 | 签名 |
|------|------|
| `test_tool_info_minimal` | `def (self) -> None` |
| `test_resource_info` | `def (self) -> None` |
| `test_prompt_info` | `def (self) -> None` |

#### `TestMCPError`

Error handling tests.

| 方法 | 签名 |
|------|------|
| `test_error_basic` | `def (self) -> None` |
| `test_error_with_data` | `def (self) -> None` |

#### `TestMCPToolAdapterEdgeCases`

Edge case tests for adapter behavior.

| 方法 | 签名 |
|------|------|
| `test_adapter_empty_schema` | `def (self) -> None` |
| `test_adapter_no_description` | `def (self) -> None` |

---

## tests.test_sandbox_executor

测试 sandbox_executor — 进程级和 Docker 沙箱执行。

### 类

#### `TestProcessSandbox`

| 方法 | 签名 |
|------|------|
| `test_basic_python_execution` | `def (self) -> None` |
| `test_basic_bash_execution` | `def (self) -> None` |
| `test_code_with_error` | `def (self) -> None` |
| `test_timeout` | `def (self) -> None` |
| `test_stdout_truncation` | `def (self) -> None` |
| `test_input_files` | `def (self) -> None` |
| `test_output_collection` | `def (self) -> None` |
| `test_execute_command` | `def (self) -> None` |
| `test_context_manager` | `def (self) -> None` |

#### `TestSandboxConfig`

| 方法 | 签名 |
|------|------|
| `test_defaults` | `def (self) -> None` |
| `test_custom` | `def (self) -> None` |

#### `TestDockerFallback`

Docker 不可用时自动降级到 Process 模式。

| 方法 | 签名 |
|------|------|
| `test_docker_fallback_when_no_docker` | `def (self) -> None` |

---

## tests.test_schema_enforcer

Tests for agentos.validation.schema_enforcer.

### 类

#### `SimpleOutput(BaseModel)`

测试用简单输出 schema。

#### `NestedOutput(BaseModel)`

测试用嵌套输出 schema。

### 函数

| 函数 | 签名 |
|------|------|
| `enforcer` | `def () -> None` |
| `async test_valid_output_passes` | `async def (enforcer) -> None` |
| `async test_missing_field_fallback` | `async def (enforcer) -> None` |
| `async test_json_string_repair` | `async def (enforcer) -> None` |
| `async test_json_markdown_codeblock_repair` | `async def (enforcer) -> None` |
| `async test_single_quote_json_repair` | `async def (enforcer) -> None` |
| `async test_extra_field_ok` | `async def (enforcer) -> None` |
| `async test_completely_invalid_full_fallback` | `async def (enforcer) -> None` |
| `async test_nested_output` | `async def (enforcer) -> None` |
| `async test_stats_tracking` | `async def (enforcer) -> None` |
| `async test_enforce_batch` | `async def (enforcer) -> None` |
| `async test_fix_strategy_order_respected` | `async def () -> None` |

---

## tests.test_subagent_parent_child

测试 SubAgent 父子通信 — 状态共享、心跳、生命周期管理。

### 类

#### `TestSharedState`

| 方法 | 签名 |
|------|------|
| `test_set_get` | `async def (self) -> None` |
| `test_update_snapshot` | `async def (self) -> None` |
| `test_sync_ops` | `async def (self) -> None` |
| `test_concurrent_writes` | `async def (self) -> None` |

#### `TestChildContext`

| 方法 | 签名 |
|------|------|
| `test_progress_report` | `async def (self) -> None` |
| `test_step_and_heartbeat` | `async def (self) -> None` |
| `test_done` | `async def (self) -> None` |
| `test_fail` | `async def (self) -> None` |
| `test_cancel_detection` | `async def (self) -> None` |
| `test_pause_resume` | `async def (self) -> None` |

#### `TestChildHandle`

| 方法 | 签名 |
|------|------|
| `test_create_context` | `async def (self) -> None` |
| `test_pause_resume` | `async def (self) -> None` |
| `test_cancel` | `async def (self) -> None` |
| `test_get_status` | `async def (self) -> None` |
| `test_timeout_detection` | `async def (self) -> None` |
| `test_no_timeout_when_unset` | `async def (self) -> None` |
| `test_heartbeat_timeout` | `async def (self) -> None` |
| `test_heartbeat_updates_info` | `async def (self) -> None` |
| `test_shared_state_parent_child` | `async def (self) -> None` |

#### `TestSubAgentManager`

| 方法 | 签名 |
|------|------|
| `test_spawn_fork_with_child_context` | `async def (self) -> None` |
| `test_spawn_fork_failure` | `async def (self) -> None` |
| `test_spawn_fork_pause_resume_flow` | `async def (self) -> None` |
| `test_swarm_parallel` | `async def (self) -> None` |
| `test_cancel_all` | `async def (self) -> None` |
| `test_list_children` | `async def (self) -> None` |
| `test_cleanup` | `async def (self) -> None` |
| `test_heartbeat_monitoring` | `async def (self) -> None` |

---

## memory.compressor

四级上下文压缩 — Claude Code核心工程洞察。
基因来源: Claude Code的s06 Context Compression

### 类

#### `ContextCompressor`

四级上下文压缩 — 不是一刀切截断，而是分层渐进式压缩。

L1 滑动窗口: 保留最近N轮对话
L2 工具结果摘要: 长输出→结构化摘要
L3 语义压缩: LLM压缩历史并保留关键信息
L4 文件系统卸载: 关键信息写入磁盘按需读取

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, window_size: int, max_tool_output_chars: int, target_tokens: int) -> None` |
| `compress` | `def (self, context: AgentContext) -> AgentContext` |

---

## memory.conversation

Conversation Memory with sliding window management.

Manages multi-turn conversations with configurable window strategies:
- Sliding window (FIFO with max turns)
- Token-aware window (trim by token count)
- Importance-weighted (keep high-importance turns, evict low)
- Hybrid (combine token budget + importance scoring)

### 类

#### `WindowStrategy(Enum)`

#### `ConversationTurn`

Single turn in a conversation.

#### `WindowConfig`

Configuration for conversation window management.

#### `ConversationMemory`

Multi-turn conversation memory with sliding window strategies.

Example::

    mem = ConversationMemory(WindowConfig(strategy=WindowStrategy.HYBRID, max_tokens=4000))
    mem.add_turn(ConversationTurn(role="user", content="Hello"))
    mem.add_turn(ConversationTurn(role="assistant", content="Hi! How can I help?"))
    messages = mem.get_messages()  # [{"role": "user", "content": "Hello"}, ...]

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[WindowConfig]) -> None` |
| `add_turn` | `def (self, turn: ConversationTurn) -> None` |
| `add_user_message` | `def (self, content: str, importance: float) -> None` |
| `add_assistant_message` | `def (self, content: str, importance: float) -> None` |
| `add_system_message` | `def (self, content: str) -> None` |
| `get_messages` | `def (self) -> list[dict[str, str]]` |
| `get_turns` | `def (self) -> list[ConversationTurn]` |
| `turn_count` | `def (self) -> int` |
| `token_count` | `def (self) -> int` |
| `clear` | `def (self) -> None` |
| `to_summary` | `def (self) -> str` |
| `__repr__` | `def (self) -> str` |

---

## memory.long_term

AgentOS v0.20 长期记忆系统。
RAG检索 + 知识图谱双重记忆。

### 类

#### `MemoryEntry`

长期记忆条目。

#### `LongTermMemory`

长期记忆 — RAG + 知识图谱。

功能:
- 语义检索（向量相似度）
- 关键词检索（倒排索引）
- 实体关系图（知识图谱）
- 记忆衰减（时间加权）
- 自动摘要压缩

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, embedding_dim: int, max_entries: int) -> None` |
| `add` | `def (self, entry: MemoryEntry) -> None` |
| `search_by_keyword` | `def (self, query: str, top_k: int) -> list[MemoryEntry]` |
| `search_by_vector` | `def (self, query_embedding: list[float], top_k: int) -> list[MemoryEntry]` |
| `add_relation` | `def (self, entity_a: str, relation: str, entity_b: str) -> None` |
| `query_relations` | `def (self, entity: str, depth: int) -> list[tuple[str, str]]` |

#### `MemoryStore`

三层记忆系统的统一入口。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, long_term: LongTermMemory | None) -> None` |
| `remember` | `def (self, key: str, value: Any, long_term: bool) -> None` |
| `recall` | `def (self, query: str, use_long_term: bool) -> list[Any]` |
| `clear_short_term` | `def (self) -> None` |

---

## memory.pyramid

Memory Pyramid for NexusAgent.

Multi-layer memory management system inspired by human memory:
- Working Memory: Current task context (short-term)
- Episodic Memory: Past experiences and events
- Semantic Memory: Facts and knowledge (long-term)
- Procedural Memory: Skills and procedures

### 类

#### `MemoryType(str, Enum)`

Types of memory in the pyramid.

#### `MemoryLayer(str, Enum)`

Memory layers (L1=fast, L2=persistent).

#### `MemoryItem`

Single memory item.

Attributes:
    id: Unique identifier
    type: Memory type
    layer: Memory layer (L1/L2)
    content: Memory content
    metadata: Additional metadata
    created_at: Creation timestamp
    accessed_at: Last access timestamp
    access_count: Number of accesses
    importance: Importance score (0-1)

| 方法 | 签名 |
|------|------|
| `access` | `def (self) -> None` |
| `to_dict` | `def (self) -> dict[str, Any]` |
| `@classmethod from_dict` | `def (cls, data: dict[str, Any]) -> MemoryItem` |

#### `MemoryPyramid`

Multi-layer memory management system.

Organizes memories into types (working/episodic/semantic/procedural)
and layers (L1=fast/L2=persistent).

Usage:
    pyramid = MemoryPyramid()
    pyramid.store("user_preference", {"theme": "dark"}, MemoryType.SEMANTIC)
    prefs = pyramid.recall("user_preference")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_working: int, max_episodic: int) -> None` |
| `store` | `def (self, key: str, content: Any, memory_type: MemoryType, layer: MemoryLayer, importan` |
| `recall` | `def (self, key: str) -> Optional[MemoryItem]` |
| `search` | `def (self, memory_type: Optional[MemoryType], limit: int) -> list[MemoryItem]` |
| `forget` | `def (self, key: str) -> bool` |
| `get_stats` | `def (self) -> dict[str, Any]` |
| `clear` | `def (self, memory_type: Optional[MemoryType]) -> None` |

---

## memory.retriever

Semantic Memory Retriever — Embedding-based memory retrieval with hybrid search.

Supports semantic (embedding), keyword (BM25), and hybrid search across
conversation memory, long-term memory, and working memory. Aligns with
ConversationMemory window strategies and LongTermMemory persistence.

### 类

#### `RetrievalStrategy(Enum)`

检索策略枚举。

#### `MemoryEntry`

A single memory entry with content and metadata.

#### `RetrievalResult`

A single retrieval result with relevance score.

#### `RetrievalStats`

Statistics for a retrieval operation.

#### `SemanticMemoryRetriever`

Semantic retrieval engine for AgentOS memory systems.

Supports three retrieval strategies:
- **semantic**: Cosine similarity over embeddings (requires embedder)
- **keyword**: BM25-style TF-IDF keyword matching (no embedder needed)
- **hybrid**: Weighted combination of semantic + keyword scores

Example::

    retriever = SemanticMemoryRetriever(embedder=my_embedder)
    results = retriever.retrieve(
        "What did we discuss about deployment?",
        top_k=5,
        strategy=RetrievalStrategy.HYBRID,
    )
    for r in results:
        print(f"[{r.score:.2f}] {r.entry.content[:80]}...")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, embedder: Optional[Callable[[str], list[float]]], hybrid_weight: float, min_k` |
| `index` | `def (self, entries: list[MemoryEntry]) -> None` |
| `remove` | `def (self, entry_ids: list[str]) -> None` |
| `retrieve` | `def (self, query: str, top_k: Optional[int], strategy: RetrievalStrategy, filter_source:` |
| `entry_count` | `def (self) -> int` |
| `clear` | `def (self) -> None` |
| `get_stats` | `def (self) -> dict[str, Any]` |

---

## memory.short_term

短期记忆 — 向量数据库存储，覆盖数天到数周的记忆。

### 类

#### `VectorMemory`

短期记忆 — 基于ChromaDB的向量存储。
存近期对话和重要上下文，按语义相似度检索。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, collection_name: str) -> None` |
| `chroma_client` | `def (self) -> None` |
| `add` | `async def (self, item: MemoryItem) -> None` |
| `search` | `async def (self, query: str, limit: int) -> list[MemoryItem]` |
| `clear` | `def (self) -> None` |

---

## memory.summarizer

AgentOS v0.60 Memory Summarizer — 上下文压缩与记忆管理。
递归摘要 / 重要性评分 / 滑动窗口 / 混合记忆策略。

### 类

#### `MemoryType(str, Enum)`

记忆类型枚举。

#### `MemoryChunk`

记忆块。

#### `ImportanceScorer`

多维度重要性评分。

| 方法 | 签名 |
|------|------|
| `@classmethod score` | `def (cls, chunk: MemoryChunk, task_relevance: float, current_time: float | None) -> floa` |

#### `MemorySummarizer`

记忆摘要器：递归压缩 + 重要性排序 + 滑动窗口裁剪。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_context_tokens: int, summarizer_fn: Callable[[str], str] | None) -> None` |
| `recursive_summarize` | `def (self, chunks: list[MemoryChunk], target_ratio: float) -> list[MemoryChunk]` |
| `rank_and_prune` | `def (self, chunks: list[MemoryChunk], max_chunks: int) -> list[MemoryChunk]` |
| `sliding_window` | `def (self, chunks: list[MemoryChunk], window_size: int) -> list[MemoryChunk]` |
| `build_context` | `def (self, chunks: list[MemoryChunk], strategy: str) -> list[MemoryChunk]` |
| `estimate_tokens` | `def (self, chunks: list[MemoryChunk]) -> int` |

#### `ConversationMemory`

对话记忆：按轮次组织，支持压缩与重置。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_turns: int, summarizer: MemorySummarizer | None) -> None` |
| `add_turn` | `def (self, role: str, content: str, metadata: dict | None) -> None` |
| `compress` | `def (self) -> None` |
| `clear` | `def (self) -> None` |
| `restore` | `def (self) -> None` |
| `total_tokens` | `def (self) -> int` |

---

## memory.working

工作记忆 — 当前会话上下文。

### 类

#### `MemoryItem`

工作记忆项。

#### `WorkingMemory`

工作记忆 — 当前会话内有效，会话结束即销毁。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_items: int) -> None` |
| `add` | `def (self, item: MemoryItem) -> None` |
| `get` | `def (self, key: str) -> MemoryItem | None` |
| `search` | `def (self, query: str, limit: int) -> list[MemoryItem]` |
| `clear` | `def (self) -> None` |

---

## swarm.coordinator

Swarm Coordinator for NexusAgent.

Multi-agent coordination system with different topologies:
- Star: Central coordinator
- Ring: Circular message passing
- Mesh: All-to-all communication
- Tree: Hierarchical structure

### 类

#### `SwarmTopology(str, Enum)`

Swarm topology types.

#### `AgentRole`

Agent 角色定义。

#### `MessageBus`

Agent 间消息总线 — 黑板模式。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `publish` | `def (self, sender: str, topic: str, data: dict) -> None` |
| `subscribe` | `def (self, topic: str, callback: Callable) -> None` |
| `messages` | `def (self) -> list[dict]` |
| `shared_memory` | `def (self) -> dict[str, Any]` |

#### `SwarmMessage`

Message in swarm communication.

Attributes:
    id: Unique identifier
    sender: Sender agent name
    receiver: Receiver agent name (None = broadcast)
    content: Message content
    metadata: Additional metadata
    timestamp: Message timestamp

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `SwarmResult`

Result of swarm execution.

Attributes:
    id: Unique identifier
    topology: Swarm topology
    outputs: Agent outputs
    messages: Communication messages
    duration: Execution duration
    success: Whether execution succeeded

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> dict[str, Any]` |

#### `SwarmCoordinator`

Multi-agent coordination system.

Coordinates multiple agents using different topologies:
- Star: Central coordinator routes all messages
- Ring: Agents pass messages in circular order
- Mesh: All agents can communicate with each other
- Tree: Hierarchical parent-child structure

Usage:
    coordinator = SwarmCoordinator(topology=SwarmTopology.STAR)
    coordinator.register(agent1)
    coordinator.register(agent2)

    result = await coordinator.execute("task")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, topology: SwarmTopology, max_rounds: int) -> None` |
| `register` | `def (self, agent: Agent[Any, Any]) -> None` |
| `unregister` | `def (self, agent_name: str) -> bool` |
| `get_agent` | `def (self, agent_name: str) -> Optional[Agent[Any, Any]]` |
| `list_agents` | `def (self) -> list[str]` |
| `execute` | `async def (self, task: Any, **metadata) -> SwarmResult` |
| `send_message` | `def (self, sender: str, receiver: Optional[str], content: Any, **metadata) -> SwarmMessa` |
| `get_messages` | `def (self, receiver: Optional[str]) -> list[SwarmMessage]` |
| `clear_messages` | `def (self) -> None` |

---

## swarm.patterns

Enhanced Swarm collaboration patterns.

Extends the base SwarmCoordinator with broadcast, pipeline, hierarchical,
and consensus-based collaboration topologies.

### 类

#### `Topology(Enum)`

Swarm collaboration topology.

#### `CollaborationConfig`

Configuration for swarm collaboration.

#### `MemberResult`

Result from a single swarm member.

#### `CollaborationResult`

Aggregated result from a swarm collaboration.

#### `SwarmPatterns`

Higher-order swarm collaboration patterns built on SwarmCoordinator.

Supports five topologies: broadcast, pipeline, hierarchical, consensus, round_robin.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, coordinator: SwarmCoordinator, config: Optional[CollaborationConfig]) -> None` |
| `collaborate` | `def (self, task: str, context: Optional[dict[str, Any]]) -> CollaborationResult` |
| `collaborate_async` | `async def (self, task: str, context: Optional[dict[str, Any]]) -> CollaborationResult` |

---

## core.async_loop

Async agent execution loop with concurrency support.

Provides async/await versions of the core agent loop for high-throughput
scenarios where multiple agents run concurrently.

### 类

#### `AsyncLoopConfig`

Configuration for async agent execution loop.

#### `AsyncInvocationResult`

Result of a single async agent invocation.

#### `AsyncAgentLoop`

Async execution loop for agent invocations.

Supports:
- Concurrent multi-agent execution with semaphore-based throttling
- Per-invocation timeouts via asyncio.wait_for
- Automatic retry with exponential backoff
- Streaming output via async generators
- Metrics collection (p50/p95/p99 latency)

Example::

    loop = AsyncAgentLoop(config=AsyncLoopConfig(max_concurrency=5))
    results = await loop.run_all([task1, task2, task3])

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[AsyncLoopConfig]) -> None` |
| `run_single` | `async def (self, agent_id: str, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> A` |
| `run_all` | `async def (self, tasks: list[tuple[str, Callable[..., Awaitable[Any]], tuple, dict]]) ->` |
| `run_streaming` | `async def (self, agent_id: str, stream_fn: Callable[[], AsyncIterator[StreamChunk]]) -> ` |
| `get_latency_stats` | `def (self) -> dict[str, float]` |
| `reset_metrics` | `def (self) -> None` |

#### `AsyncContextManager`

Async-safe context manager for agent sessions.

Manages async context propagation across concurrent agent invocations.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, context: AgentContext) -> None` |
| `get` | `async def (self, key: str, default: Any) -> Any` |
| `set` | `async def (self, key: str, value: Any) -> None` |
| `update` | `async def (self, mapping: dict[str, Any]) -> None` |
| `snapshot` | `async def (self) -> dict[str, Any]` |

---

## core.code_agent

AgentOS v1.1.9 — CodeAgent 模式。

基因来源: Smolagents CodeAgent (HuggingFace)

CodeAgent 允许 Agent 通过生成和执行 Python 代码来完成子任务，
而非仅调用预定义工具。代码可以调用已注册的 tools + 安全内置函数。

特性:
- 多步执行：生成代码 → 执行 → 观察结果 → 继续
- 安全沙箱：白名单模块、禁止危险操作、超时控制
- Tools 集成：代码中直接调用 `tool_name(args)`
- 内存持久：跨步骤的变量和结果通过 locals 传递

### 类

#### `CodeStep`

CodeAgent 单步执行记录。

#### `CodeResult`

CodeAgent 执行结果。

#### `CodeGuard(ast.NodeVisitor)`

Python 代码 AST 安全扫描器，拦截危险操作。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, allowed_modules: frozenset) -> None` |
| `visit_Import` | `def (self, node: ast.Import) -> None` |
| `visit_ImportFrom` | `def (self, node: ast.ImportFrom) -> None` |
| `visit_Call` | `def (self, node: ast.Call) -> None` |

#### `CodeAgent`

代码执行型 Agent。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, tools: List[Callable] | None, model: str, max_steps: int, timeout_per_step: f` |
| `tools` | `def (self) -> Dict[str, Callable]` |
| `run` | `async def (self, task: str, state: Dict[str, Any] | None) -> CodeResult` |

### 函数

| 函数 | 签名 |
|------|------|
| `scan_code` | `def (code: str, allowed_modules: frozenset) -> List[str]` |
| `safe_exec` | `def (code: str, tools: Dict[str, Callable], state: Dict[str, Any], timeout: float) -> Tu` |

---

## core.context

上下文管理器 — 构建Agent所需的完整上下文。

### 类

#### `ToolCall`

模型请求的工具调用。

#### `ToolResult`

工具调用的返回结果。

| 方法 | 签名 |
|------|------|
| `is_error` | `def (self) -> bool` |

#### `Message`

对话中的单条消息。

#### `AgentContext`

传给模型的完整上下文。

#### `ContextManager`

管理Agent会话的全部消息历史。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, system_prompt: str, max_history: int) -> None` |
| `init_session` | `def (self, session_id: str, task: str) -> None` |
| `build_context` | `def (self, model_type: str, tools: list[dict] | None) -> AgentContext` |
| `append_tool_results` | `def (self, results: list[ToolResult]) -> None` |
| `add_assistant_message` | `def (self, content: str, tool_calls: list[ToolCall] | None) -> None` |
| `add_user_message` | `def (self, content: str) -> None` |
| `message_count` | `def (self) -> int` |
| `estimated_tokens` | `def (self) -> int` |

---

## core.di

Dependency Injection system for NexusAgent.

Provides type-safe Agent[Deps, Out] generic base class,
RunContext for dependency injection, and Depends() for
automatic dependency resolution.

### 类

#### `RunContext(Generic[Deps])`

Runtime context passed to Agent.run().

Contains:
- deps: The dependencies for this agent
- agent_name: Name of the agent
- run_id: Unique ID for this run
- metadata: Additional metadata

| 方法 | 签名 |
|------|------|
| `get` | `def (self, key: str, default: Any) -> Any` |
| `set` | `def (self, key: str, value: Any) -> None` |

#### `Depends`

Dependency marker for automatic injection.

Usage:
    def get_db() -> Database:
        return Database()

    class MyAgent(Agent[Depends(get_db), str]):
        async def run(self, ctx):
            db = ctx.deps  # Database instance

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, callable: Callable[..., Any]) -> None` |
| `resolve` | `def (self) -> Any` |

#### `Agent(Generic[Deps, Out])`

Base class for all agents.

Type-safe generic: Agent[Deps, Out]
- Deps: Type of dependencies
- Out: Type of output

Usage:
    class MyAgent(Agent[str, str]):
        async def run(self, ctx: RunContext[str]) -> str:
            return f"Hello, {ctx.deps}!"

    agent = MyAgent()
    result = await agent.invoke("World")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, name: str) -> None` |
| `run` | `async def (self, ctx: RunContext[Deps]) -> Out` |
| `invoke` | `async def (self, deps: Deps, **metadata) -> Out` |
| `get_tools` | `def (self) -> list[Callable[..., Any]]` |
| `__repr__` | `def (self) -> str` |

### 函数

| 函数 | 签名 |
|------|------|
| `inject_tool` | `def (tool: Callable[..., Any]) -> Callable[..., Any]` |
| `requires_context` | `def (*fields) -> Callable[..., Any]` |

---

## core.handoff

Handoff protocol for NexusAgent.

Provides Swarm-style task transfer between agents.
When an agent cannot handle a request, it can transfer
to another agent that is better suited.

### 类

#### `Handoff`

Represents a handoff request to another agent.

Usage:
    class SupportAgent(Agent[str, str]):
        async def run(self, ctx: RunContext[str]) -> str | Handoff:
            if "billing" in ctx.deps.lower():
                return transfer_to(BillingAgent(), ctx.deps)
            return "General support"

#### `HandoffResult`

Result of a handoff operation.

Contains:
- output: The final output from the target agent
- source_agent: Name of the original agent
- target_agent: Name of the agent that handled it
- handoff_chain: List of agents involved

#### `HandoffAwareAgent(Agent[Any, Any])`

Base class for agents that support handoffs.

Provides can_handle() method for checking if agent
can handle input, and run() can return Handoff.

| 方法 | 签名 |
|------|------|
| `can_handle` | `def (self, input_data: Any) -> bool` |
| `run` | `async def (self, ctx: RunContext[Any]) -> Any` |

### 函数

| 函数 | 签名 |
|------|------|
| `transfer_to` | `def (agent: Agent[Any, Any], input_data: Any, reason: str, **metadata) -> Handoff` |
| `can_handle` | `def (agent: Agent[Any, Any], input_data: Any) -> bool` |
| `async execute_with_handoff` | `async def (agent: Agent[Any, Any], input_data: Any, max_hops: int, **metadata) -> Handof` |

---

## core.loop

AgentOS v0.70 核心循环 — Gemini + Metrics + CostAnalytics 集成版。
v0.40: Swarm多Agent并行、Agent间通信、语义缓存、任务队列。
v0.70: MetricsCollector、CostAnalytics实时监控。

### 类

#### `LoopState(str, Enum)`

主循环状态。

#### `AgentResult`

Agent 主循环的最终运行结果。

#### `LoopConfig`

Agent 主循环的运行时配置。

#### `MaxIterationsExceeded(Exception)`

超出最大迭代次数异常。

#### `HumanInterruptNeeded(Exception)`

需要人工介入异常。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, message: str, context: dict | None) -> None` |

#### `ReflectionResult`

反思结果。

#### `AgentLoop`

v0.30 核心循环 — Reflection + HITL + Self-Critique + 自动路由 + 成本追踪。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, model_router: ModelRouter, tool_registry: ToolRegistry, context_manager: Cont` |
| `run` | `async def (self, task: str, session_id: str) -> AgentResult` |
| `cancel` | `def (self) -> None` |
| `run_swarm` | `async def (self, task: str, roles: list[AgentRole] | None) -> AgentResult` |

#### `StepTimeoutError(Exception)`

步骤超时异常。

#### `StepResult`

步骤执行结果。

---

## core.middleware

AgentOS v1.1.4 Agent Runtime Middleware Pipeline — 可组合的执行生命周期中间件。

在 Agent 执行的每个阶段（pre-LLM / post-LLM / pre-tool / post-tool）
插入策略检查、日志、脱敏、预算控制等拦截逻辑。

灵感来自 Microsoft Agent Framework 1.0 的 Middleware Pipeline 和 CrewAI Runtime Hooks。

### 类

#### `MiddlewarePhase(str, Enum)`

中间件触发阶段。

#### `MiddlewareContext`

中间件执行上下文。

#### `MiddlewareDecision`

中间件决策结果。

#### `AgentMiddleware(ABC)`

Agent 运行时中间件基类。

每个中间件声明自己监听的阶段，通过 process() 返回决策。
返回 MiddlewareDecision(allow=False) 阻断执行链。

| 方法 | 签名 |
|------|------|
| `phases` | `def (self) -> list[MiddlewarePhase]` |
| `process` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |

#### `PIIMaskingMiddleware(AgentMiddleware)`

PII脱敏中间件：在 pre-LLM 阶段对 prompt 脱敏。

| 方法 | 签名 |
|------|------|
| `phases` | `def (self) -> list[MiddlewarePhase]` |
| `process` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |

#### `BudgetGuardMiddleware(AgentMiddleware)`

预算守护中间件：pre-LLM 阶段检查预算。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, tracker, budget_limit: float, warn_ratio: float) -> None` |
| `phases` | `def (self) -> list[MiddlewarePhase]` |
| `process` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |

#### `ToolRiskGuardMiddleware(AgentMiddleware)`

工具风险守护中间件：pre-tool 阶段根据风险等级决定是否阻断。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, max_auto_level: str) -> None` |
| `phases` | `def (self) -> list[MiddlewarePhase]` |
| `process` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |

#### `AuditLogMiddleware(AgentMiddleware)`

审计日志中间件：在所有阶段记录审计轨迹。

| 方法 | 签名 |
|------|------|
| `phases` | `def (self) -> list[MiddlewarePhase]` |
| `process` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |

#### `MiddlewarePipeline`

编排多个中间件按阶段执行。

每个阶段：
1. 筛选监听该阶段的中间件
2. 按注册顺序依次执行
3. 任一返回 allow=False 即阻断
4. 若返回 modified_context 则传递给后续中间件

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, middlewares: Optional[list[AgentMiddleware]]) -> None` |
| `add` | `def (self, middleware: AgentMiddleware) -> MiddlewarePipeline` |
| `remove` | `def (self, name: str) -> None` |
| `middleware_names` | `def (self) -> list[str]` |
| `execute_phase` | `async def (self, phase: MiddlewarePhase, ctx: MiddlewareContext) -> MiddlewareDecision` |
| `on_start` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |
| `pre_llm` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |
| `post_llm` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |
| `pre_tool` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |
| `post_tool` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |
| `on_error` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |
| `on_complete` | `async def (self, ctx: MiddlewareContext) -> MiddlewareDecision` |

---

## core.session

会话管理 — 多会话隔离与状态持久化。

### 类

#### `Session`

Agent 会话记录。

#### `SessionStore`

会话存储后端（内存实现，可替换为SQLite/Postgres）。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `create` | `def (self, task: str, metadata: dict | None) -> Session` |
| `get` | `def (self, session_id: str) -> Session | None` |
| `update_state` | `def (self, session_id: str, state: str) -> None` |
| `list_active` | `def (self) -> list[Session]` |
| `delete` | `def (self, session_id: str) -> None` |

---

## core.state_machine

AgentOS v0.60 State Machine — Agent 生命周期状态管理。
状态：Idle → Thinking → Acting → Observing → (Complete|Failed|Paused)
含转换守卫、超时检测、恢复机制。

### 类

#### `AgentState(str, Enum)`

Agent 状态枚举。

#### `StateTransition`

状态转换事件记录。

#### `StateMachineConfig`

状态机运行时配置。

#### `TransitionError(Exception)`

非法状态转换异常。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, from_state: AgentState, to_state: AgentState) -> None` |

#### `StateTimeoutError(Exception)`

状态超时异常。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, state: AgentState, elapsed: float, limit: float) -> None` |

#### `AgentStateMachine`

Agent有限状态机，带守卫和超时检测。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: StateMachineConfig | None) -> None` |
| `state` | `def (self) -> AgentState` |
| `elapsed_total` | `def (self) -> float` |
| `elapsed_in_state` | `def (self) -> float` |
| `history` | `def (self) -> list[StateTransition]` |
| `transition` | `def (self, to_state: AgentState, reason: str, metadata: dict | None) -> StateTransition` |
| `on_transition` | `def (self, from_state: AgentState, to_state: AgentState) -> None` |
| `start` | `def (self, reason: str) -> None` |
| `think` | `def (self, reason: str) -> None` |
| `act` | `def (self, reason: str) -> None` |
| `observe` | `def (self, reason: str) -> None` |
| `complete` | `def (self, reason: str) -> None` |
| `fail` | `def (self, reason: str) -> None` |
| `pause` | `def (self, reason: str) -> None` |
| `resume` | `def (self, reason: str) -> None` |
| `cancel` | `def (self, reason: str) -> None` |
| `error` | `def (self, reason: str) -> None` |
| `is_active` | `def (self) -> bool` |
| `is_terminal` | `def (self) -> bool` |
| `run_idle` | `def (self) -> None` |
| `summary` | `def (self) -> dict` |

---

## core.streaming

AgentOS v0.20 流式输出系统。
支持 SSE (Server-Sent Events) 格式流式传输。

### 类

#### `StreamEvent(str, Enum)`

流式事件。

#### `StreamChunk`

流式输出的单块数据。

| 方法 | 签名 |
|------|------|
| `to_sse` | `def (self) -> str` |
| `is_terminal` | `def (self) -> bool` |

#### `StreamEmitter`

异步SSE发射器。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `emit` | `def (self, event: StreamEvent, **data) -> StreamChunk` |
| `thinking` | `def (self, text: str) -> StreamChunk` |
| `text` | `def (self, text: str) -> StreamChunk` |
| `tool_call` | `def (self, name: str, args: dict) -> StreamChunk` |
| `tool_result` | `def (self, name: str, result: str) -> StreamChunk` |
| `error` | `def (self, message: str) -> StreamChunk` |

#### `ResponseCollector`

收集流式chunk并拼接为最终响应。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `feed` | `def (self, chunk: StreamChunk) -> None` |
| `full_text` | `def (self) -> str` |

---

## cost.token_counter

Token Counter — Model-aware token counting and cost estimation.

Supports tiktoken-based counting for OpenAI models and approximate
counting for other providers (Anthropic, Google, local models).

### 类

#### `ModelFamily(Enum)`

模型系列枚举。

#### `TokenCount`

Token counts for a message or conversation.

#### `CostEstimate`

Estimated cost for token usage.

#### `TokenCounter`

Model-aware token counting and cost estimation.

Uses tiktoken when available for OpenAI models, falls back to
character-based approximation for other models.

Example::

    counter = TokenCounter()
    tokens = counter.count("Hello, world!", model="gpt-4o")
    cost = counter.estimate_cost(tokens, model="gpt-4o")

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self) -> None` |
| `count` | `def (self, text: str, model: str) -> TokenCount` |
| `count_messages` | `def (self, messages: list[dict[str, str]], model: str) -> TokenCount` |
| `estimate_cost` | `def (self, token_count: TokenCount, model: Optional[str]) -> CostEstimate` |
| `get_total_usage` | `def (self) -> TokenCount` |
| `get_total_cost` | `def (self) -> CostEstimate` |
| `reset_usage` | `def (self) -> None` |
| `@staticmethod format_cost` | `def (cost: CostEstimate) -> str` |
| `@staticmethod format_tokens` | `def (tokens: TokenCount) -> str` |

---

## cost.tracker

AgentOS v1.1.4 成本追踪系统（增强版）。
v1.1.4新增: 实时按Run追踪（RunCostSession），灵感来自 CrewAI Control Plane 的实时成本核算。

### 类

#### `ModelPricing`

模型定价配置。

#### `UsageRecord`

用量记录。

#### `RunCostSession`

单次 Agent 运行的成本会话。

| 方法 | 签名 |
|------|------|
| `total_cost` | `def (self) -> float` |
| `total_tokens` | `def (self) -> dict` |
| `call_count` | `def (self) -> int` |
| `duration_seconds` | `def (self) -> float` |
| `summary` | `def (self) -> str` |

#### `CostTracker`

实时成本追踪器（v1.1.4增强）。

新增能力：
- 按 run 粒度分组追踪（RunCostSession）
- 实时累计成本查询（按 run / 按 model）
- 会话开始/结束生命周期

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, budget_limit: float) -> None` |
| `start_session` | `def (self, run_id: Optional[str]) -> str` |
| `end_session` | `def (self, run_id: str) -> Optional[RunCostSession]` |
| `active_sessions` | `def (self) -> list[RunCostSession]` |
| `get_session` | `def (self, run_id: str) -> Optional[RunCostSession]` |
| `record` | `def (self, model: str, usage: dict | Any, run_id: str) -> float` |
| `record_with_cache` | `def (self, model: str, input_tokens: int, output_tokens: int, run_id: str) -> float` |
| `total_cost` | `def (self) -> float` |
| `total_tokens` | `def (self) -> dict` |
| `cost_by_model` | `def (self) -> dict[str, float]` |
| `cost_by_session` | `def (self) -> dict[str, float]` |
| `summary` | `def (self) -> str` |
| `session_summary` | `def (self) -> str` |
| `@staticmethod noop` | `def () -> None` |
| `reset` | `def (self) -> None` |
| `on_budget_warning` | `def (self, callback) -> None` |

---

## feedback.learner

AgentOS v0.30 反馈学习系统 — Human-in-the-loop + RLHF hooks。
支持人工评分、偏好学习、持续改进。

### 类

#### `FeedbackType(str, Enum)`

反馈类型枚举。

#### `FeedbackRecord`

反馈记录。

#### `FeedbackCollector`

反馈收集器 — HITL反馈入口。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, storage_path: str) -> None` |
| `collect` | `def (self, record: FeedbackRecord) -> None` |
| `collect_thumbs` | `def (self, session_id: str, iteration: int, up: bool) -> None` |
| `collect_rating` | `def (self, session_id: str, iteration: int, rating: int, comment: str) -> None` |
| `collect_corrective` | `def (self, session_id: str, iteration: int, correction: str, original: str) -> None` |
| `on_feedback` | `def (self, callback) -> None` |
| `stats` | `def (self) -> dict` |

#### `PreferenceLearner`

偏好学习器 — 从反馈中提取改进信号。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, window_size: int) -> None` |
| `learn_from_feedback` | `def (self, record: FeedbackRecord) -> None` |
| `get_improvement_hints` | `def (self) -> list[str]` |
| `should_retrain` | `def (self, threshold: float) -> bool` |

---

## rag.citation

Citation tracing for RAG pipeline.

Tracks which source documents contributed to generated text,
enabling answer provenance and fact-checking.

### 类

#### `Citation`

A single citation linking generated text to a source chunk.

#### `CitationReport`

Complete citation analysis for a generated response.

| 方法 | 签名 |
|------|------|
| `to_dict` | `def (self) -> Dict[str, Any]` |

#### `CitationTracer`

Track which retrieved chunks contributed to an answer.

Two modes:
- token_overlap: Match answer spans to chunk texts by token overlap.
- explicit: Parse answer for explicit citation markers like [1], [doc1].

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, mode: str, min_overlap: int, overlap_ratio: float) -> None` |
| `trace` | `def (self, answer: str, sources: List[Dict[str, Any]]) -> CitationReport` |
| `build_attribution_map` | `def (self, answer: str, sources: List[Dict[str, Any]]) -> str` |

### 函数

| 函数 | 签名 |
|------|------|
| `hash_chunk_id` | `def (text: str, index: int) -> str` |

---

## rag.hybrid

Hybrid search (dense + sparse) for RAG pipeline.

Combines dense vector search with BM25 sparse retrieval
using reciprocal rank fusion (RRF) or weighted score fusion.

### 类

#### `HybridConfig`

Configuration for hybrid search.

#### `BM25Retriever`

BM25 sparse retrieval with Okapi BM25 scoring.

Works with pre-chunked documents, builds an in-memory inverted index.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, k1: float, b: float, stop_words: Optional[List[str]]) -> None` |
| `index` | `def (self, documents: List[str]) -> None` |
| `search` | `def (self, query: str, top_k: int) -> List[Tuple[int, float]]` |

#### `HybridRetriever`

Combined dense + sparse retrieval with score fusion.

Usage:
    retriever = HybridRetriever(
        dense_fn=your_dense_search_fn,
        bm25=bm25_retriever,
    )
    results = await retriever.search(query="how to train a model", top_k=5)

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, dense_fn, bm25: Optional[BM25Retriever], config: Optional[HybridConfig]) -> N` |
| `index_documents` | `def (self, documents: List[str]) -> None` |
| `search` | `async def (self, query: str, top_k: int) -> List[Dict[str, Any]]` |

---

## rag.reranker

Re-ranking for RAG pipeline.

Cross-encoder and LLM-based reranking to refine retrieval results.
Supports: cross-encoder (sentence-transformers), LLM reranking,
and simple heuristic reranking (diversity, freshness).

### 类

#### `RerankConfig`

Configuration for reranking.

#### `Reranker`

Re-rank retrieval results for improved relevance.

Methods:
- cross_encoder: Uses sentence-transformers cross-encoder for precision.
- mmr: Maximal Marginal Relevance for diversity.
- llm: Uses an LLM to score relevance of each passage.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: Optional[RerankConfig]) -> None` |
| `rerank` | `async def (self, query: str, passages: List[Dict[str, Any]]) -> List[Dict[str, Any]]` |

#### `DiversityRanker`

Diversity-focused reranker for varied search results.

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, lambda_param: float) -> None` |
| `rerank` | `def (self, passages: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]` |

---

## docs.generator

v0.80 — 从模块源码自动生成 Markdown API 文档。

### 类

#### `DocConfig`

文档生成配置。

#### `DocGenerator`

从 Python 包源码生成 Markdown API 文档。

| 方法 | 签名 |
|------|------|
| `__init__` | `def (self, config: DocConfig | None) -> None` |
| `generate` | `def (self, package_path: str) -> str` |

### 函数

| 函数 | 签名 |
|------|------|
| `generate_api_docs` | `def (package_path: str, output_path: str | None) -> str` |
| `generate_quickstart` | `def (output_path: str) -> str` |

---
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
