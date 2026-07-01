"""
Terminal User Interface (TUI) — Textual-based native terminal agent cockpit.

OpenCode/Cursor-style terminal experience:
  - Four-panel layout: file tree | chat/result | terminal/editor | market
  - Full keyboard navigation (vim-style + standard shortcuts)
  - Real-time streaming output
  - Session persistence
  - Dark/light themes
  - Skill marketplace browser (ctrl+m)

Requirements: pip install textual

Usage:
    agentos tui                      # Launch TUI
    agentos tui --safe               # Safe mode (read-only)
    agentos tui --theme dark         # Dark theme (default)
    agentos tui --market             # Open market panel on start
    agentos tui --store-url :18900   # Custom skill store server URL
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    from textual.app import App, ComposeResult
    from textual.widgets import (
        Header, Footer, Tree, TextArea, Input, Static, RichLog,
        ListView, ListItem, Label, Button, TabbedContent, TabPane,
    )
    from textual.containers import Horizontal, Vertical, Container, ScrollableContainer
    from textual.binding import Binding
    from textual.reactive import reactive
    from textual.screen import ModalScreen
    from textual.message import Message
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False


# ── Models ──

@dataclass
class TUIConfig:
    """TUI persistent configuration."""
    theme: str = "dark"
    work_dir: str = field(default_factory=lambda: str(Path.home()))
    font_size: int = 14
    max_history: int = 500
    auto_scroll: bool = True
    store_url: str = "http://127.0.0.1:18900"

    def save(self, path: str = "~/.agentos/tui.json"):
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "theme": self.theme, "work_dir": self.work_dir,
            "font_size": self.font_size, "max_history": self.max_history,
            "auto_scroll": self.auto_scroll, "store_url": self.store_url,
        }, indent=2))

    @classmethod
    def load(cls, path: str = "~/.agentos/tui.json") -> "TUIConfig":
        p = Path(path).expanduser()
        if p.exists():
            data = json.loads(p.read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        return cls()


# ── Stubs (when textual not installed) ──

if not TEXTUAL_AVAILABLE:
    class FileTree: pass
    class ChatArea: pass
    class TerminalPanel: pass
    class StatusBar: pass
    class MarketPanel: pass
    class _StubApp:
        def run(self): raise RuntimeError("textual not installed: pip install textual")


if TEXTUAL_AVAILABLE:

    class FileTree(Vertical):
        """Left panel: clickable file tree."""
        def compose(self) -> ComposeResult:
            yield Static(" File Tree ", id="panel-title")
            yield Tree("~/", id="file-tree")

        def on_mount(self) -> None:
            self._populate_tree()

        def _populate_tree(self) -> None:
            tree = self.query_one("#file-tree", Tree)
            tree.clear()
            root = tree.root
            root.set_label(str(Path.home()))
            try:
                items = sorted(Path.home().iterdir(), key=lambda p: (p.is_file(), p.name))
                for item in items[:50]:
                    icon = "  " if item.is_dir() else "  "
                    node = root.add(f"{icon}{item.name}", data=str(item))
                    if item.is_dir():
                        self._add_dir_children(node, item, depth=0)
            except PermissionError:
                pass

        def _add_dir_children(self, parent, path: Path, depth: int):
            if depth > 1:
                return
            try:
                for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))[:15]:
                    icon = "  " if child.is_dir() else "  "
                    node = parent.add(f"{icon}{child.name}", data=str(child))
                    if child.is_dir():
                        self._add_dir_children(node, child, depth + 1)
            except PermissionError:
                pass


    class ChatArea(Vertical):
        """Center panel: chat interface."""
        def compose(self) -> ComposeResult:
            yield Static(" Chat ", id="panel-title")
            yield RichLog(id="chat-log", highlight=True, markup=True)
            yield Input(placeholder="Ask anything... (Enter to send)", id="chat-input")

        def add_message(self, role: str, text: str):
            log = self.query_one("#chat-log", RichLog)
            if role == "user":
                log.write(f"\n[bold green]>[/bold green] {text}")
            elif role == "error":
                log.write(f"\n[bold red]![/bold red] {text}")
            else:
                log.write(f"\n[bold blue]•[/bold blue] {text}")


    class TerminalPanel(Vertical):
        """Right panel: terminal / shell output."""
        def compose(self) -> ComposeResult:
            yield Static(" Terminal ", id="panel-title")
            yield RichLog(id="terminal-log", highlight=True, markup=True)
            yield Input(placeholder="$ command...", id="terminal-input")

        def on_mount(self) -> None:
            log = self.query_one("#terminal-log", RichLog)
            log.write("[dim]$ agentos tui started[/dim]")
            log.write(f"[dim]  cwd: {os.getcwd()}[/dim]")


    class StatusBar(Horizontal):
        """Bottom status bar with metrics."""
        def compose(self) -> ComposeResult:
            yield Static(" Sessions: 0 ", id="status-sessions")
            yield Static(" Tasks: 0 ", id="status-tasks")
            yield Static(" Mode: READY ", id="status-mode")


    class MarketPanel(ScrollableContainer):
        """Skill marketplace panel with embedded web-like view.

        Shows skill sources from multiple marketplaces (OpenClaw, ClawHub,
        SkillsMP, LobeHub, etc.) and supports one-click install for compatible
        sources. External sources open in the system browser.

        Requires the skill store server: agentos skill-store
        """

        class SkillInstalled(Message):
            """Posted when a skill is installed via the market."""
            def __init__(self, skill_name: str, source: str) -> None:
                self.skill_name = skill_name
                self.source = source
                super().__init__()

        def __init__(self, store_url: str = "http://127.0.0.1:18900", **kwargs):
            super().__init__(**kwargs)
            self._store_url = store_url
            self._sources: list[dict] = []
            self._installed: set[str] = set()
            self._active_source: str = "openclaw"
            self._skills: list[dict] = []

        def compose(self) -> ComposeResult:
            yield Static(" Skill Marketplace ", id="panel-title")
            with Horizontal():
                with Vertical(classes="market-sidebar", id="market-sidebar-container"):
                    yield Static("  Sources", classes="market-section-title")
                    yield ListView(id="market-source-list")
                with Vertical(classes="market-content", id="market-content-container"):
                    yield Static("  Skills", classes="market-section-title")
                    yield Input(placeholder="Search skills...", id="market-search")
                    yield RichLog(id="market-skill-log", highlight=True, markup=True)

        def on_mount(self) -> None:
            self._init_sources()
            self._load_skills()

        def _init_sources(self) -> None:
            try:
                import urllib.request, json as _json
                with urllib.request.urlopen(f"{self._store_url}/api/sources", timeout=5) as resp:
                    self._sources = _json.loads(resp.read())
            except Exception:
                self._sources = [
                    {"id": "openclaw", "name": "OpenClaw Skill Store", "skill_count": "14+",
                     "installable": True, "web_url": "https://github.com/nicepkg/openclaw-skill-store",
                     "description": "OpenClaw 官方社区技能商店"},
                    {"id": "clawhub", "name": "ClawHub", "skill_count": "5,700+",
                     "installable": False, "web_url": "https://github.com/clawhub-community/skills",
                     "description": "ClawHub 社区技能聚合"},
                    {"id": "skillsmp", "name": "SkillsMP", "skill_count": "164万+",
                     "installable": False, "web_url": "https://skills.mp/",
                     "description": "技能界的 Google，最大索引平台"},
                    {"id": "lobehub", "name": "LobeHub Skills", "skill_count": "28万+",
                     "installable": False, "web_url": "https://lobehub.com/skills",
                     "description": "LobeHub 生态精品平台"},
                    {"id": "skillhub", "name": "SkillHub Club", "skill_count": "1.6万+",
                     "installable": False, "web_url": "https://skillhub.club/",
                     "description": "AI 评分品质筛选市集"},
                    {"id": "skills_sh", "name": "skills.sh", "skill_count": "67万+",
                     "installable": False, "web_url": "https://skills.sh/",
                     "description": "Vercel Labs 一键安装平台"},
                    {"id": "awesome", "name": "awesome-agent-skills", "skill_count": "380+",
                     "installable": False, "web_url": "https://github.com/nicepkg/awesome-agent-skills",
                     "description": "人工审核精选技能合集"},
                ]

            lst = self.query_one("#market-source-list", ListView)
            lst.clear()
            for src in self._sources:
                icon = "[bold green]↓[/bold green]" if src.get("installable") else "[bold blue]↗[/bold blue]"
                cnt = src.get("skill_count", "?")
                lst.append(ListItem(
                    Label(f"{icon} {src['name']}  [dim]({cnt})[/dim]"),
                    name=src["id"],
                ))

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            if event.item.name:
                raw = event.item.name
                self._active_source = raw.value if hasattr(raw, 'value') else str(raw)
                self._load_skills()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "market-search":
                self._filter_skills(event.value.strip())

        def _load_skills(self) -> None:
            log = self.query_one("#market-skill-log", RichLog)
            log.clear()
            src = next((s for s in self._sources if s["id"] == self._active_source), None)
            if not src:
                log.write("[bold red]Source not found[/bold red]")
                return

            if not src.get("installable"):
                log.write(f"[bold blue]{src['name']}[/bold blue]")
                log.write(f"[dim]{src.get('description', 'External marketplace')}[/dim]\n")
                log.write(f"[bold]Open in browser:[/bold]")
                log.write(f"  [link={src['web_url']}]{src['web_url']}[/link]")
                log.write(f"  [link={src.get('url', src['web_url'])}]{src.get('url', '')}[/link]\n")
                log.write("[dim]External marketplace — open the URL above in your browser to browse and install.[/dim]")
                return

            try:
                import urllib.request, json as _json
                url = f"{self._store_url}/api/skills?source={self._active_source}"
                with urllib.request.urlopen(url, timeout=5) as resp:
                    data = _json.loads(resp.read())
                    self._skills = data.get("skills", [])
            except Exception:
                self._skills = self._fallback_skills()

            log.write(f"[bold blue]{src['name']}[/bold blue] [dim]({len(self._skills)} skills)[/dim]\n")
            for skill in self._skills:
                name = skill["name"]
                desc = skill.get("description", "")
                tags = " ".join(f"[dim]#{t}[/dim]" for t in skill.get("tags", []))
                installed = "[bold green]✓[/bold green]" if name in self._installed else "[dim]○[/dim]"
                log.write(f"  {installed} [bold]{name}[/bold]  {tags}")
                log.write(f"    [dim]{desc}[/dim]")
            log.write("")
            log.write(f"[dim]Use 'agentos skill-store' to start the web UI for one-click install.[/dim]")

        def _fallback_skills(self) -> list[dict]:
            return [
                {"name": "skill-creator", "description": "Create new skills from templates", "tags": ["meta"]},
                {"name": "pdf-tools", "description": "PDF manipulation, merge, split, extract", "tags": ["document"]},
                {"name": "xlsx-tools", "description": "Excel/Spreadsheet processing", "tags": ["document"]},
                {"name": "docx-tools", "description": "Word document processing", "tags": ["document"]},
                {"name": "pptx-tools", "description": "PowerPoint generation", "tags": ["document"]},
                {"name": "image-tools", "description": "Image processing, resize, convert", "tags": ["media"]},
                {"name": "web-search", "description": "Advanced web search with multiple engines", "tags": ["search"]},
                {"name": "browser-automation", "description": "Browser automation with Playwright", "tags": ["browser"]},
                {"name": "code-review", "description": "Automated code review", "tags": ["code"]},
                {"name": "git-tools", "description": "Git workflow automation", "tags": ["git"]},
                {"name": "file-organizer", "description": "File organization and cleanup", "tags": ["files"]},
                {"name": "data-analysis", "description": "Data analysis and visualization", "tags": ["data"]},
                {"name": "api-tester", "description": "API testing and docs generation", "tags": ["api"]},
                {"name": "markdown-tools", "description": "Markdown editing and conversion", "tags": ["document"]},
            ]

        def _filter_skills(self, query: str) -> None:
            log = self.query_one("#market-skill-log", RichLog)
            if not query:
                self._load_skills()
                return
            log.clear()
            matched = [s for s in self._skills if
                       query.lower() in s["name"].lower() or
                       query.lower() in s.get("description", "").lower()]
            log.write(f"[dim]Search: '{query}' — {len(matched)} results[/dim]\n")
            for skill in matched:
                name = skill["name"]
                desc = skill.get("description", "")
                installed = "[bold green]✓[/bold green]" if name in self._installed else "[dim]○[/dim]"
                log.write(f"  {installed} [bold]{name}[/bold]")
                log.write(f"    [dim]{desc}[/dim]")

        def set_store_url(self, url: str) -> None:
            self._store_url = url

        @property
        def installed_skills(self) -> set[str]:
            return self._installed


    # ── Main Application ──

    class AgentOSTUI(App):
        """Main TUI application — four-panel agent cockpit."""

        CSS = """
        Screen {
            layout: grid;
            grid-size: 3 3;
            grid-gutter: 1 2;
            background: $surface;
        }

        #panel-file {
            row-span: 2;
            border: solid $primary;
            background: $panel;
        }

        #panel-chat {
            row-span: 2;
            border: solid $primary;
            background: $panel;
        }

        #panel-terminal {
            row-span: 2;
            border: solid $primary;
            background: $panel;
        }

        #panel-market {
            row-span: 2;
            border: solid $success;
            background: $panel;
        }

        #panel-status {
            column-span: 3;
            height: 1;
            background: $primary-darken-2;
            color: $text;
        }

        #panel-title {
            background: $primary-darken-1;
            color: $text;
            text-style: bold;
            padding: 0 1;
            height: 1;
        }

        #file-tree {
            height: 1fr;
            overflow-y: auto;
        }

        #chat-log {
            height: 1fr;
            overflow-y: auto;
        }

        #terminal-log {
            height: 1fr;
            overflow-y: auto;
        }

        #chat-input, #terminal-input {
            dock: bottom;
            height: 3;
        }

        .market-sidebar {
            width: 32;
            border: solid $primary-darken-2;
        }

        .market-section-title {
            background: $primary-darken-1;
            color: $text;
            text-style: bold;
            height: 1;
        }

        #market-source-list {
            height: 1fr;
        }

        #market-search {
            dock: top;
            height: 3;
        }

        #market-skill-log {
            height: 1fr;
            overflow-y: auto;
        }
        """

        BINDINGS = [
            Binding("ctrl+q", "quit", "Quit", show=True),
            Binding("ctrl+s", "save", "Save", show=True),
            Binding("ctrl+r", "refresh", "Refresh", show=True),
            Binding("ctrl+t", "focus_terminal", "Terminal", show=True),
            Binding("ctrl+c", "focus_chat", "Chat", show=True),
            Binding("ctrl+f", "focus_files", "Files", show=True),
            Binding("ctrl+m", "toggle_market", "Market", show=True),
            Binding("f5", "refresh", "Refresh", show=False),
        ]

        _config: TUIConfig = TUIConfig()
        _message_handler: Optional[callable] = None
        _market_visible: bool = False

        def __init__(self, config: TUIConfig = None, start_market: bool = False):
            super().__init__()
            if config:
                self._config = config
            self._market_visible = start_market

        def compose(self) -> ComposeResult:
            yield Header("NexusAgentOS", icon="")
            yield FileTree(id="panel-file")
            yield ChatArea(id="panel-chat")
            yield TerminalPanel(id="panel-terminal")
            yield StatusBar(id="panel-status")
            yield Footer()

        def on_mount(self) -> None:
            self.title = "NexusAgentOS TUI"
            self.sub_title = f"v1.7.6 — {self._config.work_dir}"

            # Mount market panel
            market = MarketPanel(store_url=self._config.store_url, id="panel-market")
            market.display = self._market_visible
            self.mount(market, before="#panel-status")

            # Update status
            status_sessions = self.query_one("#status-sessions", Static)
            status_sessions.update(" Sessions: 0 ")

        # ── Actions ──

        def action_quit(self) -> None:
            self.exit()

        def action_save(self) -> None:
            self._config.save()
            chat = self.query_one("#chat-log", RichLog)
            chat.write("[dim]Config saved.[/dim]")

        def action_refresh(self) -> None:
            self.query_one("#file-tree", Tree).root.remove_children()
            self.query_one("#panel-file", FileTree)._populate_tree()

        def action_focus_terminal(self) -> None:
            self.query_one("#terminal-input", Input).focus()

        def action_focus_chat(self) -> None:
            self.query_one("#chat-input", Input).focus()

        def action_focus_files(self) -> None:
            self.query_one("#file-tree", Tree).focus()

        def action_toggle_market(self) -> None:
            market = self.query_one("#panel-market", MarketPanel)
            self._market_visible = not self._market_visible
            market.display = self._market_visible
            if self._market_visible:
                market._init_sources()
                market._load_skills()
                market.query_one("#market-search", Input).focus()
                self.sub_title = f"v1.7.6 — Market | {self._config.work_dir}"
            else:
                self.sub_title = f"v1.7.6 — {self._config.work_dir}"

        # ── Input Handlers ──

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "chat-input" and event.value.strip():
                self._handle_chat(event.value.strip())
                event.input.clear()
            elif event.input.id == "terminal-input" and event.value.strip():
                self._handle_terminal(event.value.strip())
                event.input.clear()

        def _handle_chat(self, message: str) -> None:
            chat = self.query_one("#panel-chat", ChatArea)
            chat.add_message("user", message)
            if self._message_handler:
                asyncio.create_task(self._dispatch_to_handler(message))
            else:
                chat.add_message("agent", f"Echo: {message}")

        async def _dispatch_to_handler(self, message: str) -> None:
            chat = self.query_one("#panel-chat", ChatArea)
            try:
                result = await self._message_handler(message)
                chat.add_message("agent", str(result))
            except Exception as e:
                chat.add_message("error", f"Error: {e}")

        def _handle_terminal(self, command: str) -> None:
            log = self.query_one("#terminal-log", RichLog)
            log.write(f"\n$ {command}")
            try:
                import subprocess
                result = subprocess.run(
                    command, shell=True, capture_output=True,
                    text=True, timeout=30, cwd=self._config.work_dir,
                )
                if result.stdout:
                    log.write(result.stdout.rstrip())
                if result.stderr:
                    log.write(f"[bold red]{result.stderr.rstrip()}[/bold red]")
            except Exception as e:
                log.write(f"[bold red]{e}[/bold red]")

        # ── Public API ──

        def set_message_handler(self, handler: callable):
            self._message_handler = handler

        def add_message(self, role: str, text: str):
            chat = self.query_one("#panel-chat", ChatArea)
            chat.add_message(role, text)


# ── Entry Point ──

def launch_tui(
    message_handler=None,
    work_dir: str = "",
    theme: str = "dark",
    start_market: bool = False,
    store_url: str = "http://127.0.0.1:18900",
) -> None:
    """Launch the TUI application.

    Args:
        message_handler: async callable(msg: str) -> str for chat responses.
        work_dir: Working directory for file tree.
        theme: 'dark' or 'light'.
        start_market: Open market panel on launch.
        store_url: URL of the skill store server.
    """
    if not TEXTUAL_AVAILABLE:
        print("ERROR: textual not installed. Run: pip install textual")
        return

    config = TUIConfig.load()
    if work_dir:
        config.work_dir = work_dir
    if theme:
        config.theme = theme
    if store_url:
        config.store_url = store_url

    app = AgentOSTUI(config=config, start_market=start_market)
    if message_handler:
        app.set_message_handler(message_handler)

    app.run()


if __name__ == "__main__":
    launch_tui()
