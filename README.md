# AgentOS - Universal Agent Runtime

[![PyPI version](https://img.shields.io/pypi/v/nexus-agentos.svg)](https://pypi.org/project/nexus-agentos/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**AgentOS** is an open-source universal agent runtime designed for the multi-agent era. It provides a unified execution environment where AI agents can discover, install, and compose skills from a decentralized marketplace, while connecting to any MCP-compatible tool server.

```
pip install nexus-agentos
```

## Why AgentOS?

| Problem | AgentOS Solution |
|---------|-----------------|
| Agents siloed in different frameworks | **Universal runtime** — one env runs OpenClaw, LangChain, custom agents |
| No marketplace for agent skills | **Built-in Skill Market** — devs upload, users install, admins review |
| MCP servers fragmented | **8 built-in MCP servers**, 34 tools out of the box |
| No TUI for agent management | **Terminal UI** (Textual) — file browser, skill manager, task runner |
| Hard to compose multi-agent workflows | **Sub-agent dispatch** — agents delegate to specialists automatically |

## Quick Start

### 1. Install

```bash
pip install nexus-agentos

# Or from source
git clone https://github.com/wuyifeishu/nexus-agentos.git
cd nexus-agentos && pip install -e .
```

### 2. Launch the Skill Marketplace

```bash
python -m agentos.server.marketplace_platform
```

Open `http://localhost:8899/static/platform.html` — you'll see the full marketplace with:
- **Browse**: search/discover 64 built-in skills across 11 categories
- **Login/Register**: JWT auth for developers
- **Upload**: zip your skill with a `skill.yaml` manifest
- **Review**: admin panel for security scanning, approve/reject

### 3. Run the Terminal UI

```bash
python -m agentos.desktop
```

Ctrl+M opens the Market Panel. Ctrl+F opens File Browser. Full keyboard-driven.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    AgentOS Runtime                       │
│  ┌─────────┐  ┌──────────┐  ┌───────────────────────┐  │
│  │   TUI   │  │  Agent   │  │   Sub‑Agent Dispatcher │  │
│  │(Textual)│  │  Engine  │  │  (search/browser/file) │  │
│  └─────────┘  └──────────┘  └───────────────────────┘  │
│  ┌─────────┐  ┌──────────┐  ┌───────────────────────┐  │
│  │  Skill  │  │   MCP    │  │   Marketplace Server   │  │
│  │Registry │  │ Registry │  │  (FastAPI + SQLite)    │  │
│  └─────────┘  └──────────┘  └───────────────────────┘  │
│  64 Skills  │  8 Servers   │  Upload/Review/Download  │
└─────────────────────────────────────────────────────────┘
```

## Built-in MCP Servers

| Server | Tools | Description |
|--------|-------|-------------|
| `filesystem` | 7 | read_file, write_file, list_directory, search_files, get_file_info, create_directory, move_file |
| `webfetch` | 3 | fetch_url, fetch_json, check_url |
| `memory` | 6 | store_memory, retrieve_memory, search_memory, list_categories, delete_memory, update_memory |
| `search` | 4 | web_search, news_search, image_search, suggest |
| `git` | 4 | git_status, git_log, git_diff, git_branch |
| `shell` | 3 | run_command, system_info, disk_usage |
| `code` | 3 | run_python, run_shell, lint_code |
| `text` | 4 | count_tokens, extract_regex, summarize_text, format_json |

All MCP servers are **zero-dependency**, pure Python implementations. No external processes required.

## Skill Categories (64 built-in)

| Category | Count | Examples |
|----------|-------|----------|
| Development | 14 | github, docker, git, kubernetes, terraform, postgres, redis |
| Productivity | 8 | google-workspace, microsoft-365, calendar, email, todoist |
| Communication | 7 | slack, discord, notion, jira, teams, webex, zendesk |
| Data | 8 | sql-query, csv-tools, bigquery, snowflake, mongodb, elasticsearch |
| Document | 5 | docx, xlsx, pptx, pdf, markdown |
| Media | 5 | image-edit, video-process, audio-transcribe, screen-capture, svg-create |
| System | 4 | system-info, file-watch, cron-scheduler, network-tools |
| Security | 4 | secret-manager, threat-scanner, 1password, auth-proxy |
| AI | 5 | prompt-optimizer, token-counter, embedding-service, langchain-tools, rag-pipeline |
| Uncategorized | 4 | weather, translation, currency-converter, timezone |

## Skill Marketplace Platform

A production-ready marketplace for the AgentOS ecosystem:

### For Developers
- Register/login with email & password (bcrypt + JWT)
- Upload `.zip` skill packages with `skill.yaml`/`manifest.json`
- Automatic security scanning on upload: dangerous imports, shell injection, obfuscation, hardcoded keys, excessive permissions
- Track downloads and reviews
- Developer profile pages

### For Users
- Browse/search skills by name, category, tags
- One-click install from any ecosystem source
- Rate and review installed skills

### For Admins
- Review queue with security findings per skill
- Approve/reject with comments
- Skill quality and safety enforcement

### API Endpoints

```
POST   /api/auth/register          - Create developer account
POST   /api/auth/login             - Login, receive JWT
GET    /api/skills                 - Browse/search published skills
GET    /api/skills/{id}            - Skill detail
GET    /api/skills/{id}/download   - Download skill zip
POST   /api/skills/upload          - Upload new skill (auth required)
GET    /api/my/skills              - My uploaded skills
GET    /api/developers/{username}  - Developer profile
POST   /api/admin/review/{id}      - Approve/reject (admin)
GET    /api/admin/review-queue     - Pending reviews (admin)
GET    /api/categories             - Category listing
```

## Security Scanning

Every uploaded skill is automatically scanned for:

| Check | Severity | Description |
|-------|----------|-------------|
| Dangerous imports | Critical | `os.system`, `subprocess`, `socket`, `ctypes` |
| Shell injection | Critical | `os.system()`, `eval()`, `exec()`, `__import__()` |
| Code obfuscation | High | Base64-encoded payloads, eval chains |
| Hardcoded secrets | High | API keys, tokens, passwords in source |
| File permission escalation | Medium | `chmod 777`, `os.chown` |
| Network exfiltration | High | Suspicious `requests.post` to unknown hosts |

## Roadmap

- [x] Universal Agent Runtime
- [x] 64 Built-in Skills
- [x] 8 MCP Servers (34 tools)
- [x] Skill Marketplace with web UI
- [x] Developer registration & upload
- [x] Security scanning pipeline
- [x] Admin review queue
- [x] Terminal UI (TUI)
- [ ] Multi-agent orchestration dashboard
- [ ] Skill dependency resolution
- [ ] Federated marketplace discovery
- [ ] Blockchain-based skill provenance

## Contributing

We welcome contributions! The Skill Marketplace is our highest-priority area.

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/amazing-skill`
3. Write your skill with a `skill.yaml` manifest
4. Upload to the marketplace or submit a PR
5. If you want to contribute to the platform itself, check the issues labeled `good first issue`

### Skill Manifest Format

```yaml
name: my-awesome-skill
version: 0.1.0
description: Does something awesome
author:
  name: Your Name
  url: https://github.com/yourname
category: dev
tags: [python, automation]
entrypoint: main.py
requires:
  python: ">=3.10"
  packages: [requests, httpx]
license: MIT
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=wuyifeishu/nexus-agentos&type=Date)](https://star-history.com/#wuyifeishu/nexus-agentos&Date)

---

Built with ❤️ by the AgentOS community. Let's make the Agent OS ecosystem thrive.
