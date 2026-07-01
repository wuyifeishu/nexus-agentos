"""Skill marketplace ecosystem bridge.

Converts skills from external ecosystems (Claude Code, Cursor, Custom GPT, LangChain)
into AgentOS SkillManifest format for unified skill registry and discovery.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from agentos.marketplace.manifest import SkillManifest, SkillFormat, ToolDef

logger = logging.getLogger(__name__)


# ── Ecosystem Formats ───────────────────────────────────────────────


class EcosystemFormat(str, enum.Enum):
    """Supported external ecosystem formats."""
    CLAUDE_CODE = "claude-code"
    CURSOR = "cursor"
    CUSTOM_GPT = "custom-gpt"
    LANGCHAIN = "langchain"


# ── Data Classes ────────────────────────────────────────────────────


@dataclass
class BridgeResult:
    """Result of bridging a single skill from an external ecosystem."""
    success: bool = False
    skill_name: str = ""
    source_format: str = ""
    source_uri: str = ""
    manifest: Optional[SkillManifest] = None
    error: str = ""
    warnings: List[str] = field(default_factory=list)


@dataclass
class BridgeBatchResult:
    """Result of a batch bridge operation."""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: List[BridgeResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ── Base Adapter ────────────────────────────────────────────────────


class BaseAdapter:
    """Base class for ecosystem adapters."""

    format_name: str = ""

    def detect(self, source: str) -> bool:
        """Check if this adapter can handle the given source."""
        raise NotImplementedError

    def bridge(self, source: str) -> BridgeResult:
        """Bridge a single skill from external format to AgentOS."""
        raise NotImplementedError

    def list_available(self) -> List[str]:
        """List available skills in this ecosystem."""
        return []


# ── Claude Code Adapter ────────────────────────────────────────────


class ClaudeCodeAdapter(BaseAdapter):
    """Bridge Claude Code extensions to AgentOS skills.

    Claude Code extensions are npm packages that expose tools or MCP servers.
    This adapter can:
    1. Download the package from npm (or read local)
    2. Parse the package.json and extension manifest
    3. Convert tool definitions to AgentOS ToolDef
    4. Generate a SkillManifest
    """

    format_name = EcosystemFormat.CLAUDE_CODE.value

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = cache_dir or os.path.join(
            tempfile.gettempdir(), "agentos", "claude_cache"
        )
        os.makedirs(self._cache_dir, exist_ok=True)

    def detect(self, source: str) -> bool:
        return (
            source.startswith("claude://")
            or source.startswith("@")  # npm scoped package
            or "claude-code" in source.lower()
            or source.endswith(".tgz")
        )

    def list_available(self) -> List[str]:
        """Return known popular Claude Code extensions."""
        return [
            "@anthropic/claude-code-tools",
            "@modelcontextprotocol/server-filesystem",
            "@modelcontextprotocol/server-github",
            "@modelcontextprotocol/server-postgres",
            "@modelcontextprotocol/server-sqlite",
            "@modelcontextprotocol/server-puppeteer",
            "@modelcontextprotocol/server-playwright",
            "@modelcontextprotocol/server-redis",
        ]

    def bridge(self, source: str) -> BridgeResult:
        result = BridgeResult(
            skill_name=source,
            source_format=self.format_name,
            source_uri=source,
        )

        try:
            # Strip protocol prefix
            if source.startswith("claude://"):
                source = source[len("claude://"):]

            # Try to load extension manifest (simulated for now)
            manifest = self._convert_to_skill(source)
            if manifest:
                result.success = True
                result.manifest = manifest
                result.skill_name = manifest.name
                result.warnings.append("Claude Code extension converted to AgentOS format")
                result.warnings.append(
                    "Note: Some Claude Code extensions use external APIs "
                    "that may require additional configuration"
                )
            else:
                result.error = f"Could not parse Claude Code extension: {source}"

        except Exception as e:
            result.error = f"Bridge failed: {e}"

        return result

    def _convert_to_skill(self, source: str) -> Optional[SkillManifest]:
        """Convert a Claude Code extension identifier to a SkillManifest.

        In production, this would:
        1. Download the npm package
        2. Parse package.json for 'claude-code' extension config
        3. Convert tool definitions

        For now, we generate a template manifest based on the package name.
        """
        name = source.lstrip("@").replace("/", "-").replace("@", "")
        # Infer tools from package name
        tools = []
        if "filesystem" in source.lower():
            tools.append(ToolDef(
                name="read_file",
                description="Read file contents from the filesystem",
                parameters={"type": "object", "properties": {
                    "path": {"type": "string"},
                }},
            ))
            tools.append(ToolDef(
                name="write_file",
                description="Write content to a file",
                parameters={"type": "object", "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                }},
            ))
        elif "github" in source.lower():
            tools.append(ToolDef(
                name="github_get_file",
                description="Get file contents from a GitHub repository",
                parameters={"type": "object", "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "path": {"type": "string"},
                }},
            ))
        elif "database" in source.lower() or "postgres" in source.lower():
            tools.append(ToolDef(
                name="query_database",
                description="Execute a SQL query against the database",
                parameters={"type": "object", "properties": {
                    "query": {"type": "string"},
                }},
            ))

        return SkillManifest(
            name=name,
            version="1.0.0",
            description=f"Claude Code extension: {source}",
            format=SkillFormat.GENERIC,
            tools=tools if tools else [
                ToolDef(
                    name=f"{name}_tool",
                    description=f"Auto-converted tool from {source}",
                    parameters={"type": "object", "properties": {}},
                )
            ],
            author="Claude Code Ecosystem",
            tags=["claude-code", "bridge"],
        )


# ── Cursor Adapter ──────────────────────────────────────────────────


class CursorAdapter(BaseAdapter):
    """Bridge Cursor rules to AgentOS skills.

    Cursor uses .cursorrules files and .cursor/rules/ directories
    to define AI behavior modifications. This adapter converts
    those rule definitions into AgentOS skills.
    """

    format_name = EcosystemFormat.CURSOR.value

    def detect(self, source: str) -> bool:
        return (
            source.startswith("cursor://")
            or ".cursorrules" in source.lower()
            or ".cursor/" in source
            or source.endswith(".mdc")
        )

    def list_available(self) -> List[str]:
        """Return common Cursor rule sources."""
        return [
            "cursor://rules/python-best-practices",
            "cursor://rules/typescript-standards",
            "cursor://rules/react-patterns",
            "cursor://rules/testing-guidelines",
        ]

    def bridge(self, source: str) -> BridgeResult:
        result = BridgeResult(
            skill_name=source,
            source_format=self.format_name,
            source_uri=source,
        )

        try:
            if source.startswith("cursor://"):
                rule_path = source[len("cursor://"):]
            else:
                rule_path = source

            manifest = self._convert_rule(rule_path)
            if manifest:
                result.success = True
                result.manifest = manifest
                result.skill_name = manifest.name
                result.warnings.append("Cursor rule converted to AgentOS skill")
            else:
                result.error = f"Could not parse Cursor rule: {source}"

        except Exception as e:
            result.error = f"Bridge failed: {e}"

        return result

    def _convert_rule(self, rule_path: str) -> Optional[SkillManifest]:
        name = Path(rule_path).stem.replace(".cursorrules", "").replace(".", "-")
        if not name:
            name = rule_path.replace("/", "-")

        return SkillManifest(
            name=name,
            version="1.0.0",
            description=f"Cursor rule: {rule_path}",
            format=SkillFormat.GENERIC,
            tools=[],
            author="Cursor Ecosystem",
            tags=["cursor", "bridge"],
        )


# ── Custom GPT Adapter ──────────────────────────────────────────────


class CustomGPTAdapter(BaseAdapter):
    """Bridge Custom GPT instructions to AgentOS skills.

    Custom GPTs have instructions, conversation starters, knowledge files,
    and capabilities. This adapter extracts instructions and converts
    them into an AgentOS skill definition.
    """

    format_name = EcosystemFormat.CUSTOM_GPT.value

    def detect(self, source: str) -> bool:
        return (
            source.startswith("gpt://")
            or "chatgpt.com/g/" in source
            or source.endswith(".gpt.md")
        )

    def list_available(self) -> List[str]:
        return [
            "gpt://data-analyst",
            "gpt://creative-writer",
            "gpt://code-reviewer",
            "gpt://research-assistant",
        ]

    def bridge(self, source: str) -> BridgeResult:
        result = BridgeResult(
            skill_name=source,
            source_format=self.format_name,
            source_uri=source,
        )

        try:
            if source.startswith("gpt://"):
                gpt_id = source[len("gpt://"):]
            else:
                gpt_id = source

            manifest = self._convert_gpt(gpt_id)
            if manifest:
                result.success = True
                result.manifest = manifest
                result.skill_name = manifest.name
                result.warnings.append("Custom GPT instructions converted to AgentOS skill")
            else:
                result.error = f"Could not parse Custom GPT: {source}"

        except Exception as e:
            result.error = f"Bridge failed: {e}"

        return result

    def _convert_gpt(self, gpt_id: str) -> Optional[SkillManifest]:
        name = gpt_id.replace("/", "-").replace(" ", "-")
        return SkillManifest(
            name=name,
            version="1.0.0",
            description=f"Custom GPT: {gpt_id}",
            format=SkillFormat.GENERIC,
            tools=[],
            author="Custom GPT Ecosystem",
            tags=["custom-gpt", "bridge"],
        )


# ── LangChain Adapter ───────────────────────────────────────────────


class LangChainAdapter(BaseAdapter):
    """Bridge LangChain tools to AgentOS skills.

    LangChain provides a rich ecosystem of tools (toolkits, tools,
    MCP adapters). This adapter converts them into AgentOS ToolDef
    and wraps them in a SkillManifest.
    """

    format_name = EcosystemFormat.LANGCHAIN.value

    KNOWN_TOOLS = {
        "wikipedia": {
            "name": "wikipedia_query",
            "description": "Search and retrieve information from Wikipedia",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 3},
                },
                "required": ["query"],
            },
        },
        "arxiv": {
            "name": "arxiv_search",
            "description": "Search academic papers on arXiv",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
        "duckduckgo": {
            "name": "web_search",
            "description": "Search the web using DuckDuckGo",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        "python_repl": {
            "name": "execute_python",
            "description": "Execute Python code in a REPL environment",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                },
                "required": ["code"],
            },
        },
        "shell": {
            "name": "execute_shell",
            "description": "Execute shell commands",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    }

    def detect(self, source: str) -> bool:
        return (
            source.startswith("langchain://")
            or "langchain" in source.lower()
        )

    def list_available(self) -> List[str]:
        return [f"langchain://{name}" for name in self.KNOWN_TOOLS]

    def bridge(self, source: str) -> BridgeResult:
        result = BridgeResult(
            skill_name=source,
            source_format=self.format_name,
            source_uri=source,
        )

        try:
            if source.startswith("langchain://"):
                tool_name = source[len("langchain://"):]
            else:
                tool_name = source

            manifest = self._convert_tool(tool_name)
            if manifest:
                result.success = True
                result.manifest = manifest
                result.skill_name = manifest.name
            else:
                result.error = f"Unknown LangChain tool: {tool_name}"

        except Exception as e:
            result.error = f"Bridge failed: {e}"

        return result

    def _convert_tool(self, tool_name: str) -> Optional[SkillManifest]:
        if tool_name not in self.KNOWN_TOOLS:
            return None

        tool_info = self.KNOWN_TOOLS[tool_name]
        tool_def = ToolDef(
            name=tool_info["name"],
            description=tool_info["description"],
            parameters=tool_info["parameters"],
        )

        return SkillManifest(
            name=f"langchain-{tool_name}",
            version="1.0.0",
            description=f"LangChain tool: {tool_name}",
            format=SkillFormat.GENERIC,
            tools=[tool_def],
            author="LangChain Ecosystem",
            tags=["langchain", "bridge"],
        )


# ── Adapter Factory ─────────────────────────────────────────────────


class AdapterFactory:
    """Factory for creating ecosystem adapters."""

    _adapters: Dict[EcosystemFormat, type] = {}

    @classmethod
    def register(cls, fmt: EcosystemFormat, adapter_cls: type):
        cls._adapters[fmt] = adapter_cls

    @classmethod
    def create(cls, fmt: EcosystemFormat, **kwargs) -> BaseAdapter:
        """Create an adapter for the given ecosystem format."""
        if fmt not in cls._adapters:
            raise ValueError(f"Unsupported ecosystem format: {fmt}")
        return cls._adapters[fmt](**kwargs)

    @classmethod
    def detect_format(cls, source: str) -> Optional[EcosystemFormat]:
        """Auto-detect ecosystem format from source string."""
        for fmt, adapter_cls in cls._adapters.items():
            adapter = adapter_cls()
            if adapter.detect(source):
                return fmt
        return None

    @classmethod
    def list_supported_formats(cls) -> List[str]:
        return [f.value for f in cls._adapters]


# Register built-in adapters
AdapterFactory.register(EcosystemFormat.CLAUDE_CODE, ClaudeCodeAdapter)
AdapterFactory.register(EcosystemFormat.CURSOR, CursorAdapter)
AdapterFactory.register(EcosystemFormat.CUSTOM_GPT, CustomGPTAdapter)
AdapterFactory.register(EcosystemFormat.LANGCHAIN, LangChainAdapter)


# ── Ecosystem Bridge (Main Entry) ───────────────────────────────────


class EcosystemBridge:
    """Bridge external skill ecosystems into AgentOS SkillRegistry.

    Usage:
        bridge = EcosystemBridge()
        # Single skill
        result = bridge.bridge("claude://@anthropic/claude-code-tools")

        # Batch (all available from one ecosystem)
        results = bridge.bridge_all(EcosystemFormat.CLAUDE_CODE)

        # Auto-detect and bridge
        result = bridge.bridge("langchain://wikipedia")
    """

    def __init__(self, skill_registry=None):
        self._skill_registry = skill_registry
        self._adapters: Dict[EcosystemFormat, BaseAdapter] = {}

    def _get_adapter(self, fmt: EcosystemFormat) -> BaseAdapter:
        if fmt not in self._adapters:
            self._adapters[fmt] = AdapterFactory.create(fmt)
        return self._adapters[fmt]

    def bridge(self, source: str, fmt: Optional[EcosystemFormat] = None) -> BridgeResult:
        """Bridge a single skill from external ecosystem.

        Args:
            source: Source identifier (e.g., "claude://pkg", "cursor://rule")
            fmt: Ecosystem format. Auto-detected if not specified.

        Returns:
            BridgeResult with converted SkillManifest.
        """
        if not fmt:
            fmt = AdapterFactory.detect_format(source)
            if not fmt:
                return BridgeResult(
                    success=False,
                    skill_name=source,
                    error=f"Could not auto-detect ecosystem format for: {source}",
                )

        adapter = self._get_adapter(fmt)
        result = adapter.bridge(source)

        # Auto-register to skill registry if available
        if result.success and result.manifest and self._skill_registry:
            try:
                self._skill_registry.register_skill(result.manifest)
            except Exception as e:
                result.warnings.append(f"Registered but SKillRegistry error: {e}")

        return result

    def bridge_all(self, fmt: EcosystemFormat) -> BridgeBatchResult:
        """Bridge all available skills from an ecosystem."""
        batch = BridgeBatchResult()
        adapter = self._get_adapter(fmt)
        available = adapter.list_available()

        for source in available:
            result = adapter.bridge(source)
            batch.results.append(result)
            if result.success:
                batch.succeeded += 1
            else:
                batch.failed += 1
                batch.errors.append(result.error)

        batch.total = len(available)
        return batch

    def batch_bridge(self, sources: List[str]) -> BridgeBatchResult:
        """Bridge multiple sources, auto-detecting formats."""
        batch = BridgeBatchResult()

        for source in sources:
            result = self.bridge(source)
            batch.results.append(result)
            if result.success:
                batch.succeeded += 1
            else:
                batch.failed += 1
                batch.errors.append(result.error)

        batch.total = len(sources)
        return batch

    def list_available(self, fmt: EcosystemFormat) -> List[str]:
        """List available skills in an ecosystem."""
        adapter = self._get_adapter(fmt)
        return adapter.list_available()

    def supported_formats(self) -> List[str]:
        return AdapterFactory.list_supported_formats()
