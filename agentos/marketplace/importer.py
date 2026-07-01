"""
Marketplace Importer — Import skills from external sources (OpenClaw, HuggingFace, GitHub).

OpenClaw Community: https://github.com/openclaw/skills
  - skill.yaml → SkillManifest (openclaw format)
  - Auto-detect format, convert, register

Usage:
    from agentos.marketplace.importer import OpenClawImporter
    importer = OpenClawImporter(registry)
    skill = await importer.import_skill("pdf-tools")
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any

from agentos.marketplace.manifest import SkillManifest, SkillFormat, ToolDef
from agentos.marketplace.registry import SkillRegistry, SearchResult, InstallResult


# ── OpenClaw Importer ──

OPENCLAW_SKILLS_REPO = "https://github.com/nicepkg/openclaw-skill-store"
OPENCLAW_RAW_BASE = "https://raw.githubusercontent.com/nicepkg/openclaw-skill-store/main"
OPENCLAW_API = "https://api.github.com/repos/nicepkg/openclaw-skill-store"


@dataclass
class RemoteSkill:
    """Skill metadata discovered from a remote source."""
    name: str
    path: str           # Relative path in the repo
    description: str = ""
    author: str = ""
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    download_url: str = ""
    raw_url: str = ""
    source: str = "openclaw"


class OpenClawImporter:
    """Import skills from the OpenClaw community skill store.

    Flow:
      1. list_available() — fetch skill catalog from GitHub API
      2. import_skill(name) — download skill.yaml → parse → register
      3. import_all() — batch import all available skills
    """

    def __init__(self, registry: SkillRegistry, cache_dir: str = ""):
        self._registry = registry
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".agentos" / "marketplace" / "openclaw"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._catalog: list[RemoteSkill] = []
        self._fetch_fn: Optional[Callable[[str], str]] = None  # Injection point for testing

    # ── Catalog ──

    async def list_available(self, refresh: bool = False) -> list[RemoteSkill]:
        """List all available OpenClaw community skills.

        Returns cached catalog unless refresh=True.
        """
        if self._catalog and not refresh:
            return self._catalog

        skills = []

        # Try fetching directory listing from the raw GitHub API
        try:
            import aiohttp
        except ImportError:
            return await self._list_fallback()

        try:
            async with aiohttp.ClientSession() as session:
                # Fetch the top-level directory listing
                url = f"{OPENCLAW_API}/contents/skills"
                async with session.get(url, headers={"Accept": "application/vnd.github.v3+json"}) as resp:
                    if resp.status != 200:
                        return await self._list_fallback()

                    entries = await resp.json()
                    for entry in entries:
                        if entry.get("type") != "dir":
                            continue

                        skill_name = entry["name"]
                        skill_path = f"skills/{skill_name}"
                        raw_url = f"{OPENCLAW_RAW_BASE}/{skill_path}/skill.yaml"
                        download_url = entry.get("url", "")

                        # Try to read skill.yaml for metadata
                        meta = await self._fetch_skill_meta(session, skill_path)
                        skills.append(RemoteSkill(
                            name=meta.get("name", skill_name),
                            path=skill_path,
                            description=meta.get("description", ""),
                            author=meta.get("author", ""),
                            version=meta.get("version", "0.1.0"),
                            tags=meta.get("tags", []),
                            raw_url=raw_url,
                            download_url=download_url,
                        ))

        except Exception:
            return await self._list_fallback()

        self._catalog = skills
        return skills

    async def _list_fallback(self) -> list[RemoteSkill]:
        """Fallback: return a curated list of known OpenClaw skills (60+)."""
        known_skills = [
            # ── Meta & Creator (3) ──
            RemoteSkill(name="skill-creator", path="skills/skill-creator",
                        description="Guide for creating effective skills", tags=["meta", "creator"]),
            RemoteSkill(name="mcp-builder", path="skills/mcp-builder",
                        description="Guide for creating MCP servers and tools", tags=["mcp", "infra"]),
            RemoteSkill(name="coding-agent", path="skills/coding-agent",
                        description="Autonomous coding agent for complex software tasks", tags=["dev", "agent"]),

            # ── Office & Documents (8) ──
            RemoteSkill(name="docx", path="skills/docx",
                        description="Create and edit .docx documents", tags=["document", "office"]),
            RemoteSkill(name="pdf", path="skills/pdf",
                        description="PDF manipulation toolkit: merge, split, extract, annotate", tags=["document", "pdf"]),
            RemoteSkill(name="pptx", path="skills/pptx",
                        description="Create and edit .pptx presentations", tags=["presentation", "office"]),
            RemoteSkill(name="xlsx", path="skills/xlsx",
                        description="Create and edit .xlsx spreadsheets with formulas and charts", tags=["spreadsheet", "office"]),
            RemoteSkill(name="nano-pdf", path="skills/nano-pdf",
                        description="Lightweight PDF reading and text extraction", tags=["document", "pdf"]),
            RemoteSkill(name="notion", path="skills/notion",
                        description="Notion integration: pages, databases, blocks CRUD", tags=["productivity", "notion"]),
            RemoteSkill(name="obsidian", path="skills/obsidian",
                        description="Obsidian vault integration: read/write notes, backlinks", tags=["knowledge", "obsidian"]),
            RemoteSkill(name="bear-notes", path="skills/bear-notes",
                        description="Bear notes app integration for Apple ecosystem", tags=["notes", "apple"]),

            # ── Design & Creative (6) ──
            RemoteSkill(name="brand-guidelines", path="skills/brand-guidelines",
                        description="Applies brand colors and typography to any artifact", tags=["design", "brand"]),
            RemoteSkill(name="canvas-design", path="skills/canvas-design",
                        description="Create beautiful visual art in .png and .pdf", tags=["art", "design"]),
            RemoteSkill(name="algorithmic-art", path="skills/algorithmic-art",
                        description="Creating algorithmic art using p5.js", tags=["art", "creative"]),
            RemoteSkill(name="theme-factory", path="skills/theme-factory",
                        description="Apply visual themes: color schemes, typography, spacing", tags=["design", "theme"]),
            RemoteSkill(name="slack-gif-creator", path="skills/slack-gif-creator",
                        description="Create animated GIFs optimized for Slack", tags=["media", "slack"]),
            RemoteSkill(name="openai-image-gen", path="skills/openai-image-gen",
                        description="Generate images using DALL-E / OpenAI image API", tags=["ai", "image"]),

            # ── Web & Frontend (5) ──
            RemoteSkill(name="frontend-design", path="skills/frontend-design",
                        description="Create distinctive production-grade frontend interfaces", tags=["web", "frontend"]),
            RemoteSkill(name="web-artifacts-builder", path="skills/web-artifacts-builder",
                        description="Build complex multi-file HTML artifacts with CSS/JS", tags=["web", "html"]),
            RemoteSkill(name="web-search", path="skills/web-search",
                        description="Web search with multiple engines and result parsing", tags=["web", "search"]),
            RemoteSkill(name="blogwatcher", path="skills/blogwatcher",
                        description="Monitor blogs and RSS feeds for updates", tags=["web", "monitoring"]),
            RemoteSkill(name="wikipedia", path="skills/wikipedia",
                        description="Search and extract content from Wikipedia", tags=["web", "knowledge"]),

            # ── Developer Tools (10) ──
            RemoteSkill(name="github", path="skills/github",
                        description="GitHub API: repos, issues, PRs, actions, gists", tags=["dev", "github"]),
            RemoteSkill(name="gh-issues", path="skills/gh-issues",
                        description="Deep GitHub issues management and triage", tags=["dev", "github"]),
            RemoteSkill(name="git", path="skills/git",
                        description="Git version control: commit, branch, merge, rebase", tags=["dev", "vcs"]),
            RemoteSkill(name="docker", path="skills/docker",
                        description="Docker container management: build, run, compose", tags=["dev", "infra"]),
            RemoteSkill(name="code-review", path="skills/code-review",
                        description="Automated code review with best-practice suggestions", tags=["dev", "quality"]),
            RemoteSkill(name="database", path="skills/database",
                        description="SQL/NoSQL database query and schema management", tags=["dev", "data"]),
            RemoteSkill(name="api-tester", path="skills/api-tester",
                        description="REST/GraphQL API testing and documentation", tags=["dev", "api"]),
            RemoteSkill(name="tmux", path="skills/tmux",
                        description="Tmux session management and automation", tags=["dev", "terminal"]),
            RemoteSkill(name="node-connect", path="skills/node-connect",
                        description="Node.js runtime integration and package management", tags=["dev", "node"]),
            RemoteSkill(name="model-usage", path="skills/model-usage",
                        description="Track and optimize AI model usage and costs", tags=["dev", "ai"]),

            # ── Communication & Messaging (6) ──
            RemoteSkill(name="internal-comms", path="skills/internal-comms",
                        description="Internal communications: announcements, memos, updates", tags=["writing", "business"]),
            RemoteSkill(name="slack", path="skills/slack",
                        description="Slack integration: messages, channels, reactions", tags=["communication", "slack"]),
            RemoteSkill(name="discord", path="skills/discord",
                        description="Discord bot integration for servers and DMs", tags=["communication", "discord"]),
            RemoteSkill(name="email", path="skills/email",
                        description="Email composition, sending, and inbox management", tags=["communication", "email"]),
            RemoteSkill(name="telegram", path="skills/telegram",
                        description="Telegram bot API: messages, channels, inline queries", tags=["communication", "telegram"]),
            RemoteSkill(name="imsg", path="skills/imsg",
                        description="iMessage integration for Apple ecosystem", tags=["communication", "apple"]),

            # ── Productivity (8) ──
            RemoteSkill(name="calendar", path="skills/calendar",
                        description="Calendar management: events, reminders, scheduling", tags=["productivity", "time"]),
            RemoteSkill(name="task-manager", path="skills/task-manager",
                        description="Task and to-do list management with priorities", tags=["productivity", "tasks"]),
            RemoteSkill(name="notes", path="skills/notes",
                        description="Quick note-taking with search and organization", tags=["productivity", "notes"]),
            RemoteSkill(name="apple-notes", path="skills/apple-notes",
                        description="Apple Notes app integration", tags=["productivity", "apple"]),
            RemoteSkill(name="apple-reminders", path="skills/apple-reminders",
                        description="Apple Reminders app integration", tags=["productivity", "apple"]),
            RemoteSkill(name="things-mac", path="skills/things-mac",
                        description="Things 3 task manager integration for macOS", tags=["productivity", "mac"]),
            RemoteSkill(name="trello", path="skills/trello",
                        description="Trello board management: cards, lists, boards", tags=["productivity", "pm"]),
            RemoteSkill(name="summarize", path="skills/summarize",
                        description="Intelligent text summarization with configurable depth", tags=["productivity", "text"]),

            # ── Data & Analysis (5) ──
            RemoteSkill(name="data-analysis", path="skills/data-analysis",
                        description="Statistical analysis, visualization, and reporting", tags=["data", "analytics"]),
            RemoteSkill(name="spreadsheet", path="skills/spreadsheet",
                        description="Advanced spreadsheet operations and formulas", tags=["data", "office"]),
            RemoteSkill(name="csv-toolkit", path="skills/csv-toolkit",
                        description="CSV parsing, transformation, and export toolkit", tags=["data", "csv"]),
            RemoteSkill(name="json-toolkit", path="skills/json-toolkit",
                        description="JSON manipulation, validation, and transformation", tags=["data", "json"]),
            RemoteSkill(name="markdown-toolkit", path="skills/markdown-toolkit",
                        description="Markdown rendering, conversion, and templating", tags=["writing", "markdown"]),

            # ── Media & Multimedia (5) ──
            RemoteSkill(name="video-frames", path="skills/video-frames",
                        description="Extract and analyze frames from video files", tags=["media", "video"]),
            RemoteSkill(name="audio-transcribe", path="skills/audio-transcribe",
                        description="Speech-to-text transcription with Whisper API", tags=["media", "audio"]),
            RemoteSkill(name="openai-whisper", path="skills/openai-whisper",
                        description="OpenAI Whisper speech recognition integration", tags=["media", "audio"]),
            RemoteSkill(name="openai-whisper-api", path="skills/openai-whisper-api",
                        description="OpenAI Whisper API with batch processing", tags=["media", "audio"]),
            RemoteSkill(name="sherpa-onnx-tts", path="skills/sherpa-onnx-tts",
                        description="Text-to-speech with Sherpa-ONNX engine", tags=["media", "tts"]),

            # ── System & Automation (5) ──
            RemoteSkill(name="automation", path="skills/automation",
                        description="Workflow automation: triggers, actions, scheduling", tags=["automation", "workflow"]),
            RemoteSkill(name="file-organizer", path="skills/file-organizer",
                        description="Smart file organization: sort, rename, deduplicate", tags=["system", "files"]),
            RemoteSkill(name="backup", path="skills/backup",
                        description="Automated backup and restore for files and configs", tags=["system", "backup"]),
            RemoteSkill(name="weather", path="skills/weather",
                        description="Weather forecasts, alerts, and historical data", tags=["utility", "weather"]),
            RemoteSkill(name="healthcheck", path="skills/healthcheck",
                        description="System health monitoring and diagnostics", tags=["system", "monitoring"]),

            # ── Security & Privacy (3) ──
            RemoteSkill(name="1password", path="skills/1password",
                        description="1Password vault integration for secrets management", tags=["security", "password"]),
            RemoteSkill(name="encryption", path="skills/encryption",
                        description="File encryption/decryption with multiple algorithms", tags=["security", "crypto"]),
            RemoteSkill(name="session-logs", path="skills/session-logs",
                        description="Audit and analyze agent session logs", tags=["security", "audit"]),
        ]
        self._catalog = known_skills
        return known_skills

    async def _fetch_skill_meta(self, session, skill_path: str) -> dict:
        """Fetch skill.yaml metadata for a single skill."""
        url = f"{OPENCLAW_API}/contents/{skill_path}/skill.yaml"
        try:
            async with session.get(url, headers={"Accept": "application/vnd.github.v3.raw"}) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    import yaml
                    return yaml.safe_load(text) or {}
        except Exception:
            pass
        return {}

    # ── Import ──

    async def import_skill(self, name: str, force: bool = False) -> Optional[InstallResult]:
        """Import a single skill from OpenClaw by name.

        Pipeline:
          1. Find in catalog
          2. Fetch skill.yaml from raw GitHub
          3. Parse as OpenClaw format → SkillManifest
          4. Register in SkillRegistry
        """
        # Ensure catalog is loaded
        if not self._catalog:
            await self.list_available()

        # Find skill
        skill_ref = None
        for s in self._catalog:
            if s.name == name:
                skill_ref = s
                break

        if not skill_ref:
            return None

        # Fetch skill.yaml
        yaml_url = f"{OPENCLAW_RAW_BASE}/{skill_ref.path}/skill.yaml"
        yaml_text = await self._fetch_url(yaml_url)

        if not yaml_text:
            return None

        # Parse as OpenClaw format
        import yaml
        try:
            raw = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            return None

        if not raw:
            return None

        # Convert to SkillManifest
        raw["format"] = "openclaw"
        manifest = SkillManifest.from_dict(
            raw,
            source=f"openclaw:{name}",
            install_path=str(self._cache_dir / name),
        )

        # Register
        return self._registry.register(manifest, force=force)

    async def import_all(self, max_skills: int = 50) -> list[InstallResult]:
        """Import all available OpenClaw skills."""
        if not self._catalog:
            await self.list_available()

        results = []
        semaphore = asyncio.Semaphore(5)  # Limit concurrent fetches

        async def _import_one(skill: RemoteSkill):
            async with semaphore:
                return await self.import_skill(skill.name)

        tasks = [_import_one(s) for s in self._catalog[:max_skills]]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in raw_results:
            if isinstance(r, Exception):
                pass
            elif r is not None:
                results.append(r)

        return results

    async def search(self, query: str) -> list[RemoteSkill]:
        """Search the catalog by name/description/tag."""
        if not self._catalog:
            await self.list_available()

        q = query.lower()
        results = []
        for s in self._catalog:
            if (q in s.name.lower() or
                q in s.description.lower() or
                any(q in t.lower() for t in s.tags)):
                results.append(s)
        return results

    # ── Internal ──

    async def _fetch_url(self, url: str) -> str:
        """Fetch URL content (supports GitHub API + raw)."""
        if self._fetch_fn:
            return self._fetch_fn(url)

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers={"Accept": "application/vnd.github.v3.raw"}) as resp:
                    if resp.status == 200:
                        return await resp.text()
        except Exception:
            pass

        # Fallback: urllib
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3.raw"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            pass

        return ""


# ── HuggingFace Importer ──

class HuggingFaceImporter:
    """Import skills from HuggingFace.co skill repositories.

    Flow:
      hf://username/skill-repo → download → parse skill.yaml → register
    """

    def __init__(self, registry: SkillRegistry, cache_dir: str = ""):
        self._registry = registry
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".agentos" / "marketplace" / "huggingface"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    async def import_from_hf(self, repo_id: str, force: bool = False) -> Optional[InstallResult]:
        """Import a skill from HuggingFace repo.

        Args:
            repo_id: e.g. 'username/agentos-skill-translator'
        """
        import aiohttp

        # Try fetching skill.yaml from main branch
        yaml_url = f"https://huggingface.co/{repo_id}/resolve/main/skill.yaml"
        yaml_text = ""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(yaml_url, timeout=10) as resp:
                    if resp.status == 200:
                        yaml_text = await resp.text()
        except Exception:
            pass

        if not yaml_text:
            yaml_url = f"https://huggingface.co/{repo_id}/resolve/main/agentos.yaml"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(yaml_url, timeout=10) as resp:
                        if resp.status == 200:
                            yaml_text = await resp.text()
            except Exception:
                pass

        if not yaml_text:
            return None

        import yaml
        try:
            raw = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            return None

        manifest = SkillManifest.from_dict(
            raw,
            source=f"huggingface:{repo_id}",
            install_path=str(self._cache_dir / repo_id.replace("/", "_")),
        )

        return self._registry.register(manifest, force=force)


# ── GitHub Importer ──

class GitHubImporter:
    """Import skills from arbitrary GitHub repositories.

    Flow:
      github://user/repo/path → download skill.yaml → parse → register
    """

    def __init__(self, registry: SkillRegistry, cache_dir: str = ""):
        self._registry = registry
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".agentos" / "marketplace" / "github"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    async def import_from_github(
        self, repo: str, path: str = "", ref: str = "main", force: bool = False,
    ) -> Optional[InstallResult]:
        """Import a skill from a GitHub repo.

        Args:
            repo: 'user/repo'
            path: subdirectory containing skill.yaml (e.g. 'skills/my-skill')
            ref: branch/tag (default 'main')
        """
        raw_base = f"https://raw.githubusercontent.com/{repo}/{ref}"
        manifest_path = f"{raw_base}/{path}/skill.yaml" if path else f"{raw_base}/skill.yaml"

        yaml_text = ""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(manifest_path, timeout=10) as resp:
                    if resp.status == 200:
                        yaml_text = await resp.text()
        except Exception:
            pass

        if not yaml_text:
            return None

        import yaml
        try:
            raw = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            return None

        safe_name = repo.replace("/", "_")
        manifest = SkillManifest.from_dict(
            raw,
            source=f"github:{repo}/{path}" if path else f"github:{repo}",
            install_path=str(self._cache_dir / safe_name),
        )

        return self._registry.register(manifest, force=force)

    async def import_release(
        self, repo: str, tag: str = "latest", force: bool = False,
    ) -> Optional[InstallResult]:
        """Import from a tagged GitHub release."""
        if tag == "latest":
            import aiohttp
            url = f"https://api.github.com/repos/{repo}/releases/latest"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            tag = data.get("tag_name", "main")
            except Exception:
                tag = "main"

        return await self.import_from_github(repo, ref=tag, force=force)


# ── Unified Importer ──

class UnifiedImporter:
    """Single entry point for importing skills from any supported source.

    Usage:
        importer = UnifiedImporter(registry)

        # From OpenClaw community
        skill = await importer.import_from("openclaw:pdf-tools")

        # From HuggingFace
        skill = await importer.import_from("hf://username/repo")

        # From arbitrary GitHub
        skill = await importer.import_from("github://user/repo/skills/my-skill")
    """

    _PROTOCOLS = {
        "openclaw": "openclaw",
        "hf": "huggingface",
        "huggingface": "huggingface",
        "github": "github",
        "gh": "github",
    }

    def __init__(self, registry: SkillRegistry, cache_dir: str = ""):
        self._registry = registry
        self._cache_dir = cache_dir
        self._openclaw = OpenClawImporter(registry, cache_dir)
        self._huggingface = HuggingFaceImporter(registry, cache_dir)
        self._github = GitHubImporter(registry, cache_dir)

    async def import_from(self, uri: str, force: bool = False) -> Optional[InstallResult]:
        """Import a skill from a URI.

        URI formats:
          - 'openclaw:skill-name'       OpenClaw community skill
          - 'hf://user/repo'            HuggingFace repo
          - 'github://user/repo[/path]' GitHub repo
          - 'skill-name'                Default: try OpenClaw first
        """
        # Parse protocol
        if "://" in uri:
            protocol, rest = uri.split("://", 1)
        elif ":" in uri and uri.split(":")[0] in self._PROTOCOLS:
            protocol, rest = uri.split(":", 1)
        else:
            # Default: try OpenClaw
            return await self._openclaw.import_skill(uri, force=force)

        protocol = self._PROTOCOLS.get(protocol, protocol)

        if protocol == "openclaw":
            return await self._openclaw.import_skill(rest, force=force)

        elif protocol == "huggingface":
            return await self._huggingface.import_from_hf(rest, force=force)

        elif protocol == "github":
            parts = rest.split("/")
            if len(parts) >= 2:
                repo = f"{parts[0]}/{parts[1]}"
                subpath = "/".join(parts[2:]) if len(parts) > 2 else ""
                return await self._github.import_from_github(repo, subpath, force=force)

        return None

    async def list_openclaw(self, refresh: bool = False) -> list[RemoteSkill]:
        """List all available OpenClaw community skills."""
        return await self._openclaw.list_available(refresh=refresh)
