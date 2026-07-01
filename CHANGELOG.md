# Changelog

All notable changes to NexusAgentOS.

---

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
