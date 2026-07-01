# Changelog

All notable changes to NexusAgentOS.

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
