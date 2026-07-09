# Changelog

All notable changes to NexusAgentOS.

---

## [1.19.0] — 2026-07-05

### Added — 生产就绪：可观测性 + 部署基础设施 + CI/CD

#### 可观测性三件套
- **结构化日志** (`agentos/observability/logging.py`, 235行): JsonFormatter + 上下文传播（request_id/trace_id/span_id）
- **分布式追踪** (`agentos/observability/tracing.py`): OpenTelemetry OTLP 导出 + no-op 回退 + `@trace_function` 装饰器
- **Prometheus 指标** (`agentos/api/server.py`): 6 个内置指标（request_count/latency/active_connections/error_rate/queue_depth/memory_usage）

#### 运维基础设施
- **健康检查** (`agentos/core/health.py`, 155行): 组件级探测（DB/Redis/Disk），异步健康端点 `/health`
- **优雅关闭** (`agentos/api/server.py`): SIGTERM → 连接排空 → 503 拒绝新请求 → 超时强制退出
- **启动配置校验** (`agentos/config_validator.py`): env/db/redis/otlp/disk 五项检查 → ValidationReport

#### 流量控制
- **API 限流** (`agentos/api/rate_limiter.py`): FixedWindowLimiter + Starlette 中间件 + X-RateLimit-* 标头

#### 部署资产
- **Docker**: Dockerfile (multi-stage) + docker-compose.yml (app+redis+prometheus+grafana)
- **Kubernetes**: Deployment + HPA + PDB + Service (k8s/deployment.yml, 171行)
- **监控栈**: Prometheus 配置 + Grafana 数据源 + Dashboard
- **配置模板**: .env.example (含所有可配置项说明)

#### CI/CD
- **GitHub Actions** (.github/workflows/ci.yml): 5 个 job（lint/test 3.11+3.12/security/build/docker）
- **Makefile**: lint/test/build/docker/deploy/k8s-deploy/clean 目标

#### 测试
- 新增 26 个测试（health/logging/tracing/rate_limiter/config_validator），总计 ~530 用例全绿

### Changed
- server.py: v1.16 → v1.18，新增优雅关闭 + metrics 端点 + 请求计数中间件
- pyproject.toml: 新增 prometheus-client、opentelemetry-* 依赖，版本 1.16.47 → 1.19.0

## [1.18.0] — 2026-07-05

### Added — 生产硬化 + 性能压测

#### 智能模块
- **ModelRouter** (`agentos/agent/model_router.py`): 智能模型路由，按任务复杂度/成本/延迟自动选择模型
- **AuditLogger** (`agentos/security/audit_logger.py`): 不可变审计日志，写后不可篡改，SHA256 链式校验
- **SmartCache** (`agentos/llm/smart_cache.py`): 语义缓存，基于 embedding 相似度的 LLM 响应缓存

#### 测试资产
- **E2E 集成测试** (test_production_e2e_v2.py, 38用例): 覆盖 14 维度（MiddlewarePipeline/FanOut/parallel_gather/RAG/Swarm/RBAC/多租户/审计等）
- **生产硬化测试** (test_production_hardening.py, 25用例): 覆盖 5 维度（并发安全/资源泄漏/优雅降级/超时/背压）
- **性能压测**: 125k TPS 并行吞吐、8.9μs 管道开销，结果写入 BENCHMARKS.md

#### 部署资产
- Dockerfile (multi-stage)、docker-compose.yml、Makefile

### Changed
- 版本: 1.16.47 → 1.18.0

## [1.17.0] — 2026-07-05

### Added — 框架全量扫描与质量基线

- **全量模块扫描**: 364 模块 / ~101k 行代码，确认生产级框架
- **测试基线**: 440 测试全绿，3 个测试文件合并 63 用例
- **核心 API 验证**: AgentMiddleware、MiddlewarePipeline、parallel_gather、FanOutExecutor 全部可用

## [1.16.12] — 2026-07-04

### Added — marketplace server 导出

- `create_marketplace_app()` / `start_marketplace_server()` 从 `agentos.server` 导出
- 可直接 `from agentos.server import create_marketplace_app`

## [1.16.11] — 2026-07-04

### Added — 内置 MCP 服务器导出

- 8个内置MCP服务器正式从 `agentos.mcp` 导出
- `FilesystemServer` / `WebFetchServer` / `MemoryServer` / `SearchServer` / `GitServer` / `ShellServer` / `CodeServer` / `TextServer`
- `BuiltinMCPRegistry` 32+工具一键注册

## [1.16.10] — 2026-07-04

### Added — MCP 工具适配器导出

- `MCPToolAdapter` 正式从 `agentos.mcp` 导出
- `MCPAdapter` 别名，`from agentos.mcp import MCPAdapter` 可用

## [1.16.9] — 2026-07-04

### Changed — TUI MarketPanel 对接种子技能

- `MarketPanel._fallback_skills()` 从 `_index.yaml` 动态加载 64 个种子技能元数据
- 每技能读取 `skill.yaml` 提取 description / tags / version
- 三级降级链: 服务器 API → 本地种子索引 → 硬编码兜底

## [1.16.8] — 2026-07-03

### Fixed — P0 修复

- `__version__` 从 `1.16.1` 修正为 `1.16.8`
- 64 种子技能注册表正常加载

## [1.16.7] — 2026-07-03

### Added — 种子技能生态启动

#### 64 个种子技能全量落地
- 从 OpenClawImporter 硬编码 catalog 提取 64 个技能元数据
- 每个技能生成自包含包: `skill.yaml` + `{name}.py` 入口 stub
- 分类: communication(5) / productivity(14) / data(5) / media(5) / automation(1) / system(3) / security(3) / web(4) / development(12) / utility(12)
- 全部注册到 SkillRegistry (`~/.agentos/marketplace/skills/`)

#### SkillRegistry.register() 公开接口
- 新增 `register(manifest, force=False)` 方法
- 使 `OpenClawImporter.import_skill()` / `import_all()` 可正常工作
- 与 `install()` 的区别: register 只写索引不复制文件

### Changed
- 注册表索引: `agentos/marketplace/skills/_index.yaml`

---

## [1.16.6] — 2026-07-03

### Added — 核心引擎集成第二波

#### AuditLogger 集成到 AgentLoop
- `loop.start` / `loop.complete` / `loop.human_interrupt` 事件自动记录
- `AuditLogger.log()` 新增 `event=` 关键字参数，支持直接传入 `AuditEvent` 对象

#### RateLimiter (TokenBucket) 集成到 AgentLoop
- 每次模型调用前检查 `rate_limiter.try_acquire("model_call")`
- 超限时抛出 `StepTimeoutError`，由上层重试机制兜底

### Changed
- `orchestration/__init__.py` 直接从 `swarm.coordinator` 导入，消除 DeprecationWarning
- 所有集成参数 Optional，完全向后兼容

---

## [1.16.5] — 2026-07-03

### Fixed

#### P0: 飞书适配器签名验证假实现
- `verify_signature()` 从直接返回 `True` 改为真正的 SHA256+Base64 签名验证
- 签名算法: `Base64Encode(SHA256(timestamp + nonce + encrypt_key))`
- 缺少必要字段（timestamp/nonce/signature/encrypt_key）时返回 `False`
- encrypt_key 来源: `encoding_aes_key` 或 `verify_token`

#### P0: AgentInfo 类名冲突
- `swarm/coordinator.py:AgentInfo` → `SwarmAgentInfo`，消除与 `protocols/registry.py:AgentInfo` 的命名歧义
- 向后兼容: `orchestration/swarm_coordinator.py` 保留 `SwarmAgentInfo as AgentInfo` 别名

---

## [1.16.4] — 2026-07-03

### Added — 测试补缺收官

#### 5 个 tools 模块测试 (127 用例)
- **test_data_tools.py** (32 用例): JsonTool(parse/format/query/validate) + CsvTool(read/stats/query)
- **test_file_tools.py** (13 用例): ReadFileTool/WriteFileTool/ListDirectoryTool 权限级别、文件读写、目录列表
- **test_function_calling.py** (26 用例): ToolSchema(OpenAI/Anthropic 格式转换) + ToolRegistry(注册/验证/执行/批处理/解析)
- **test_http_tools.py** (19 用例, 8 passed, 11 skipped): 网络容错装饰器 `_httpbin_skip()`
- **test_search_tools.py** (27 用例): GrepTool/FileSearchTool/CodeSearchTool 正则搜索、文件匹配、AST 符号检测

### Fixed
- test_execute_no_handler 断言兼容两种错误信息

---

## [1.16.3] — 2026-07-03

### Added — 测试补缺第一波

#### 6 个缺失测试的 tools 模块 (107 用例, 全部通过)
- **test_registry.py** (14 用例): 100% 覆盖率
- **test_risk.py** (18 用例): 100% 覆盖率
- **test_fusion.py** (20 用例): 83% 覆盖率
- **test_generator.py** (14 用例): 79% 覆盖率
- **test_code_agent.py** (10 用例)
- **test_orchestrator.py** (21 用例): 46% 覆盖率

---

## [1.16.2] — 2026-07-03

### Changed — Swarm 去重
- `orchestration/swarm_coordinator.py` 从 836 行缩减为 54 行兼容垫片
- 所有核心逻辑统一到 `swarm/coordinator.py`

### Added
- **SwarmAgentRole**: WORKER / COORDINATOR / OBSERVER 枚举
- **TaskPriority / TaskStatus**: 任务优先级与状态枚举
- **AgentInfo**: Agent 元数据
- **SwarmTask / TaskAllocator**: 动态任务分配（负载感知 + 能力匹配）
- **ConflictResolver / ConflictType**: Agent 冲突检测与解决（多数投票 / 加权投票 / 共识构建）
- SmartSwarmCoordinator 正式指向 SwarmCoordinator

---

## [1.16.1] — 2026-07-03

### Added — 核心引擎集成

#### CircuitBreaker / ToolOutputValidator / MetricsCollector 集成
- `ToolExecutor` 新增 `circuit_breaker` / `validator` / `metrics` 可选参数
- `ToolAgent._process_step` 新增 LLM 调用和 token 指标
- `AgentGraph.execute` 新增节点级指标
- 全部参数 Optional，完全向后兼容

---

## [1.16.0] — 2026-07-03

### Added
- 30 个新 tools 模块
- 三线发布 (PyPI / TestPyPI / GitHub Release)

---

## [1.9.0] — 2026-07-01

### Added — 五大模块齐发

#### 生态桥接器 (`agentos/marketplace/bridge.py`, 512 行)
- **EcosystemBridge**: 一键桥接到外部技能生态。自动将 Claude Code 扩展、Cursor 规则、Custom GPT 指令、LangChain 工具转换为 AgentOS Skill Manifest。
- **4 个适配器**: ClaudeCodeAdapter（自动下载扩展仓库）、CursorAdapter（解析 .cursorrules/.cursor/rules/）、CustomGPTAdapter（解析 GPT 指令模板）、LangChainAdapter（LangChain 工具 → ToolDef）。
- **批量桥接**: `bridge("claude-code:*")` 桥接 Claude Code 所有扩展；`batch_bridge()` 同时桥接多个生态，统一导入 SkillRegistry。
- **EcosystemFormat**: `claude-code` / `cursor` / `custom-gpt` / `langchain` 四种格式枚举。
- **AdapterFactory**: 按格式自动分发到对应适配器。

#### 自进化闭环 v2 (`agentos/evolution/autopilot.py`, 549 行)
- **AutoPilot**: 全自动闭环自进化管道。行为信号 → AutoPilot 分析 → LLM 生成代码 diff → 自动测试 → AB 评测 → 审批/自动合入。
- **4 种模式**: SUGGEST_ONLY（仅建议）/ ASK_BEFORE（每次确认）/ CONFIDENCE_GATED（阈值门控）/ FULL_AUTO（全自动）。
- **CodeGenerator**: LLM 驱动的代码 diff 生成器，输出标准 unified diff。
- **AutoTester**: 自动运行回归测试套件，对比修改前后通过率。
- **RollbackManager**: 即时回滚到上一个已知良好状态，带备份归档。
- **ABEvaluator**: 新旧版本并行对比评测，统计显著性检验。
- **EvolutionJournal**: 完整的审计日志，记录每次进化的完整轨迹。

#### 评估套件 v2 (`agentos/evaluation/suite.py`, 604 行)
- **EvalSuiteRunner**: 全评估管道编排器，支持多维度评估的流水线执行。
- **SWEBenchEvaluator**: SWE-bench 风格端到端任务评估（仓库编辑 + 测试验证）。
- **MultiRoundEvaluator**: 多轮对话评估，含上下文保持和状态一致性检查。
- **HallucinationDetector**: 幻觉检测器，含事实编造检测、自矛盾检测、引用来源验证。
- **Leaderboard**: 版本性能排行榜，追踪每次发布的评测指标变化。

#### Swarm 编排引擎 v2 (`agentos/orchestration/swarm_coordinator.py`, 789 行)
- **SwarmCoordinator**: 多 Agent 群体编排器。动态任务分配、Inter-Agent 消息总线、冲突解决、共识协议。
- **MessageBus**: Pub/sub 消息总线，支持点对点、广播、主题订阅、请求-应答。
- **TaskAllocator**: 负载感知的动态任务分配器，考虑能力匹配、当前负载、任务优先级、亲和性。
- **ConflictResolver**: Agent 冲突检测与解决。多数投票、加权投票、偏好排序、共识构建。
- **SwarmTopology**: 星形 / 网状 / 环形 / 树形 / DAG / 混合 六种拓扑。
- **HealthMonitor**: 心跳监控，死 Agent 检测，自动任务重分配。

#### 混合搜索引擎 (`agentos/rag/hybrid_search.py`, 583 行)
- **HybridSearchEngine**: 稠密 + 稀疏 + 重排三阶段检索管道。
- **BM25Retriever**: 纯 Python BM25 实现，零依赖倒排索引，支持中文分词。
- **DenseRetriever**: 语义嵌入检索包装器，兼容 ChromaDB。
- **CrossEncoderReranker**: 跨编码器重排，支持 HuggingFace 模型和 LLM 判断两种模式。
- **CitationTracker**: 引用追踪与验证，自动检测未引用声明（潜在幻觉）。
- **FusionMethod**: RRF / 加权和 / 级联 三种融合算法。

### Changed
- LLM 生态: 5 providers (OpenAI, DeepSeek, Anthropic, Ollama, Pangu)
- 版本: 1.8.3 → 1.9.0
- 模块: evolution / evaluation / orchestration / rag / marketplace 五个 __init__ 全部更新导出

### 统计
- 新增代码: ~3,037 行
- 新增模块: 5 个文件
- 新增类: 50+ 个类/数据类
- 新增适配器: 4 个生态格式
- 新增拓扑: 6 种 Swarm 拓扑
- 新增评测维度: 3 种（SWE-bench / 多轮 / 幻觉检测）

---

## [1.8.3] — 2026-07-01

### Added
- **P0-① Claude Sonnet 5**: Full support for Anthropic's latest Sonnet 5 model (`claude-sonnet-5-20250630`). Default Anthropic model upgraded from Sonnet 4 to Sonnet 5. Pricing $3/$15 per 1M tokens (same as Sonnet 4, significantly cheaper than Opus). Also added Claude Opus 4 and Opus 4.5 to pricing registry. Sonnet 5 prefix auto-detection for future 5-series models.
- **P0-④ Ollama Provider**: Native Ollama local inference provider (`agentos/llm/ollama_provider.py`). OpenAI-compatible API, supports all Ollama models (qwen2.5, llama3.1, gemma2, mistral, deepseek-r1). Default: `qwen2.5:7b`. Zero extra dependencies.
- **P0-④ Huawei Pangu Provider**: Native Pangu provider (`agentos/llm/pangu_provider.py`). Supports pangu-4, pangu-3.1, pangu-code, pangu-vision. Default endpoint: `https://pangu-api.huaweicloud.com/v1`.
- **P0-② Persistent Checkpointer** (`agentos/checkpoint/`): Production-grade checkpoint/resume engine. Two backends: SQLite (zero-dependency, dev/POC) and Postgres (asyncpg, production). Features: auto-snapshot per tool_call/llm_call, time-travel to any historical state, thread branching via parent pointer, garbage collection (delete_before). Designed after LangGraph PostgresSaver.

### Changed
- LLM Provider count: 3 → 5 (OpenAI, DeepSeek, Anthropic, Ollama, Pangu)
- Default Anthropic model: `claude-sonnet-4-20250514` → `claude-sonnet-5-20250630`
- Version: 1.8.2 → 1.8.3

### Fixed
- P0-③ F821 runtime bugs verified resolved (KeyCreateRequest, KeyScope, TenantTier imports working correctly in CLI)

## [1.8.2] — 2026-07-01

### Added
- **Skill Marketplace Platform** (`agentos/server/marketplace_platform.py`): Full production-ready skill marketplace backend. FastAPI + SQLite + JWT + bcrypt. Features: developer registration/login, skill zip upload with manifest validation, automatic security scanning (6 checks: dangerous imports, shell injection, obfuscation, hardcoded secrets, permission escalation, data exfiltration), admin review queue (approve/reject), public browse/search, download counts, developer profiles, API token management.
- **Marketplace Web UI** (`agentos/server/static/platform.html`): Complete single-page web app. Developer signup/login, skill upload with drag-and-drop, browsing with search and category filter, skill detail pages, developer profile pages, admin review panel with security findings per skill.
- **MCP Servers Expansion**: 3→8 built-in MCP servers, 16→34 tools. New: SearchServer (4 tools), GitServer (4 tools), ShellServer (3 tools), CodeServer (3 tools), TextServer (4 tools). All zero-dependency pure Python.
- **Skill Fallback Expansion**: 14→64 built-in skills across 11 categories (Dev/Productivity/Communication/Data/Document/Media/System/Security/AI/Uncategorized).
- **GitHub Open Source Launch**: Full source code published at https://github.com/wuyifeishu/nexus-agentos. MIT license. Comprehensive README with architecture diagram, API docs, and contributing guide.

### Changed
- MCP Server schemas renamed: `mcp__<server>__<tool>` format for OpenAI function schema compatibility.
- PyPI package pushed: [nexus-agentos==1.8.2](https://pypi.org/project/nexus-agentos/1.8.2/).
- TestPyPI pushed: [nexus-agentos==1.8.2](https://test.pypi.org/project/nexus-agentos/1.8.2/).

## [1.7.7] — 2026-07-01

### Added
- **Skill Store Web Server** (`agentos/desktop/skill_store_server.py`, 248 lines): FastAPI server serving the skill marketplace web UI at localhost:18900. REST API: GET /api/sources (7 marketplaces), GET /api/skills, POST /api/install, POST /api/install-all, GET /api/health. Integrates with OpenClawImporter for one-click install. Launch: `agentos skill-store` / `agentos skill-store --open`.
- **Skill Store Web UI** (`agentos/desktop/static/index.html`, 380+ lines): Responsive web-based skill marketplace with sidebar source navigation (OpenClaw/ClawHub/SkillsMP/LobeHub/SkillHub/skills.sh/awesome-agent-skills), skill grid cards with search/filter, one-click install buttons, iframe embedding of external market pages, toast notifications. Dark theme matching agentos aesthetics.
- **TUI MarketPanel** (`agentos/desktop/tui.py`): New Ctrl+M toggle to open a fourth panel showing the skill marketplace directly in the terminal. Sidebar source list + skill browser + search. Works offline with fallback catalog when skill store server is not running. Version bumped 1.7.6→1.7.7.
- **Gap Analysis 2026Q3** (`GAP_ANALYSIS_2026Q3.md`): Comprehensive competitive analysis vs OpenClaw (345K stars, 13,700+ skills), Hermes (145K stars, self-learning), Claude Code, Cursor, OpenCode. Identifies skill ecosystem as #1 gap. Skill marketplace landscape mapping: SkillsMP (164万), skills.sh (67万), LobeHub (28万), ClawHub (5,700+).

### Changed
- TUI grid layout updated for optional MarketPanel (Ctrl+M), store_url config persisted
- Version bumped pyproject.toml: 1.7.6 → 1.7.7

---

## [1.7.6] — 2026-07-01

### Added
- **Version Rollback** (`agentos/cli/rollback.py`, 408 lines): Safe rollback to any previously archived version.

---

## [1.7.5] — 2026-07-01

### Added
- **PTC Session Manager** (`agentos/memory/session.py`, 481 lines): Persistent Thread Context for long-running agent sessions. Heartbeat keep-alive, idle auto-suspend, state snapshot/restore, cross-session memory recovery, aiosqlite persistence with full event hooks (create/suspend/resume/expire).
- **Parallel Agent Scheduler** (`agentos/orchestration/parallel.py`, 361 lines): Native multi-agent parallel executor with DAG dependency resolution (topological sort → level-by-level parallel batches), asyncio.Semaphore concurrency pool, per-task timeout/retry, fan-out batch dispatch, real-time streaming results.
- **Textual TUI** (`agentos/desktop/tui.py`, 378 lines): Three-panel terminal cockpit (file tree / chat / terminal) with full keyboard navigation, terminal command execution, config persistence, and async message handler hook. `agentos tui` or `launch_tui()` entry point.
- **5 International Channel Adapters** (`agentos/channels/adapters/`): Slack (Events API/OAuth/Bolt, Block Kit), Discord (Gateway Intents/Interactions/Embed), Telegram (Bot API/Long Poll/Webhook/Inline Keyboard), WhatsApp (Business Cloud API v19.0/Template Messages/Interactive Buttons), LINE (Messaging API/Flex Message/Quick Reply/Rich Menu). All normalized to ChannelMessage via BaseChannelAdapter, 10→11 total channels.
- **Marketplace Importers** (`agentos/marketplace/importer.py`, 485 lines): Three importers — OpenClawImporter (14-skill fallback catalog, search/import/import_all), HuggingFaceImporter (hf://user/repo), GitHubImporter (github://user/repo[/path]). UnifiedImporter single entry: `import_from("openclaw:pdf-tools")` / `import_from("hf://user/repo")` / `import_from("github://user/repo/path")`.
---

## [1.7.6] — 2026-07-01

### Added
- **Version Rollback** (`agentos/cli/rollback.py`, 408 lines): Safe rollback to any previously archived version. Archives wheels locally (~/.agentos/rollback/wheels/) with SHA256 integrity verification. CLI: `agentos rollback <version>` / `agentos rollback --list` / `agentos rollback --verify` / `agentos rollback --prune`. Supports PyPI version listing and cross-reference checks.

---

## [1.7.4] — 2026-06-30

### Added
- **P2 Multi-channel**: 5 channels (WeChat/Mini-Program/DingTalk/Feishu/CLI) with channel registry, session affinity, reply router, rate limiter, message enqueue/dequeue processing, graceful shutdown. (channels/, 1896 lines)
- **P3 Skill Marketplace**: skill registry, marketplace store with versioned skills, 3 importers (OpenClaw/HuggingFace/GitHub), 3 sample skills, dep resolver, sandbox runner. (skills/, 2386 lines)
- **P4 Self-Evolution**: behavior signal collector (6 types), learner (6 analyzers for pattern mining), L1 rule learner + L2 neural tuner. (evolution/, 1100 lines)
- **P5 OSS Infra**: CI/CD (.github/workflows/ci.yml), issue/PR templates, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, CHANGELOG.md. (infra, 569 lines)

## [1.7.3]
Internal routing / coordinator improvements.

## [1.7.2]
Internal checkpoint and provider upgrades.

## [1.7.1] — 2026-06-27

### Added
- **P0+P1 Core**: Tool-Using Agent, LLM Provider abstraction (OpenAI/DeepSeek/Anthropic), Function Calling, streaming, retry, checkpoint/resume, A2A protocol, swarm coordination, RBAC, multi-tenancy, audit logging, API key management.

## [1.7.0] — 2026-06-24

### Added
- Initial framework core release on PyPI (`nexus-agentos`).
