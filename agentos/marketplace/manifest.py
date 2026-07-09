"""
AgentOS Skill Marketplace — Skill Manifest v1.0。

兼容格式：
  - agentos:    原生 AgentOS Skill 格式
  - openclaw:   OpenClaw 社区 Skill 格式（自动适配）
  - mcp:        MCP 协议 Skill（JSON-RPC stdio/sse 代理）
  - generic:    通用 Python 包 Skill（无约束格式）

参考:
  OpenClaw Marketplace: https://github.com/openclaw/skills
  MCP Specification:    https://modelcontextprotocol.io
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SkillFormat(StrEnum):
    AGENTOS = "agentos"
    OPENCLAW = "openclaw"
    MCP = "mcp"
    GENERIC = "generic"

    @classmethod
    def detect(cls, raw: dict) -> SkillFormat:
        """从原始 manifest dict 自动检测格式。"""
        if (
            raw.get("mcpServers")
            or raw.get("tools")
            and isinstance(raw.get("tools"), list)
            and raw["tools"]
            and "server" in raw["tools"][0]
        ):
            return cls.MCP
        if raw.get("format") == "openclaw" or raw.get("openclaw_version"):
            return cls.OPENCLAW
        if (
            raw.get("format") == "agentos"
            or raw.get("entrypoint")
            or raw.get("tools")
            and isinstance(raw.get("tools"), list)
        ):
            return cls.AGENTOS
        return cls.GENERIC


@dataclass
class ToolDef:
    """Skill 暴露的工具定义。"""

    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    returns: str = ""


@dataclass
class SkillManifest:
    """统一的 Skill 清单 — 跨格式兼容。

    支持从 agentos / openclaw / mcp / generic 四种格式的 manifest
    自动解析为统一模型。安装和解依赖均基于本模型。
    """

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = "unknown"
    license_: str = "MIT"
    format: SkillFormat = SkillFormat.GENERIC

    # AgentOS 原生字段
    entrypoint: str = ""  # "module:func" 格式的入口点
    tools: list[ToolDef] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    # MCP 兼容字段
    mcp_command: str = ""  # MCP server 启动命令，如 "npx -y @anthropic/mcp-server"
    mcp_args: list[str] = field(default_factory=list)
    mcp_env: dict = field(default_factory=dict)
    mcp_type: str = "stdio"  # stdio | sse

    # OpenClaw 兼容字段
    openclaw_version: str = ""

    # 通用字段
    tags: list[str] = field(default_factory=list)
    homepage: str = ""
    repository: str = ""
    icon: str = ""
    min_agentos_version: str = "1.7.0"

    # 元数据
    install_path: str = ""
    source: str = ""  # pypi | github | local | url
    manifest_hash: str = ""

    @classmethod
    def from_dict(cls, raw: dict, source: str = "", install_path: str = "") -> SkillManifest:
        """从原始 dict 自动检测格式并解析。"""
        fmt = SkillFormat.detect(raw)
        m = cls(name="", description="")

        m.name = raw.get("name", "")
        m.version = str(raw.get("version", "0.1.0"))
        m.description = raw.get("description", "")
        m.author = raw.get("author", raw.get("maintainer", "unknown"))
        m.license_ = raw.get("license", raw.get("license_", "MIT"))
        m.format = fmt
        m.source = source
        m.install_path = install_path
        m.tags = raw.get("tags", raw.get("keywords", []))
        m.homepage = raw.get("homepage", raw.get("url", ""))
        m.repository = raw.get("repository", raw.get("repo", ""))
        m.icon = raw.get("icon", "")
        m.min_agentos_version = raw.get("min_agentos_version", raw.get("requires_agentos", "1.7.0"))

        if fmt == SkillFormat.AGENTOS:
            m.entrypoint = raw.get("entrypoint", "")
            m.dependencies = raw.get("dependencies", raw.get("requires", []))
            tools_raw = raw.get("tools", [])
            for t in tools_raw:
                m.tools.append(
                    ToolDef(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        parameters=t.get("parameters", {}),
                        returns=t.get("returns", ""),
                    )
                )

        elif fmt == SkillFormat.OPENCLAW:
            # OpenClaw 格式：skill.yaml → agentos 适配
            m.entrypoint = raw.get("entrypoint", raw.get("main", ""))
            m.dependencies = raw.get("dependencies", raw.get("pip", []))
            m.openclaw_version = raw.get("openclaw_version", raw.get("format_version", ""))
            tools_raw = raw.get("tools", raw.get("functions", []))
            for t in tools_raw:
                m.tools.append(
                    ToolDef(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        parameters=t.get("parameters", t.get("input_schema", {})),
                    )
                )

        elif fmt == SkillFormat.MCP:
            # MCP 格式：mcpServers.{name} → agentos 适配
            servers = raw.get("mcpServers", {})
            if servers:
                first = list(servers.values())[0] if servers else {}
                m.mcp_command = first.get("command", "")
                m.mcp_args = first.get("args", [])
                m.mcp_env = first.get("env", {})
                m.mcp_type = first.get("type", "stdio")
            if not m.name and "server_name" in raw:
                m.name = raw["server_name"]
            if not m.description:
                m.description = f"MCP Server: {m.mcp_command} {' '.join(m.mcp_args)}"
            tools_raw = raw.get("tools", [])
            for t in tools_raw:
                m.tools.append(
                    ToolDef(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        parameters=t.get("inputSchema", {}),
                    )
                )

        elif fmt == SkillFormat.GENERIC:
            m.entrypoint = raw.get("entrypoint", raw.get("main", ""))
            m.dependencies = raw.get(
                "dependencies", raw.get("requires", raw.get("install_requires", []))
            )
            m.description = raw.get("description", raw.get("summary", ""))

        # 计算 manifest 哈希
        m.manifest_hash = m._compute_hash()
        return m

    def to_dict(self) -> dict:
        """导出为标准 agentos manifest dict。"""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license_,
            "format": self.format.value,
            "entrypoint": self.entrypoint,
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                    "returns": t.returns,
                }
                for t in self.tools
            ],
            "dependencies": self.dependencies,
            "tags": self.tags,
            "homepage": self.homepage,
            "repository": self.repository,
            "icon": self.icon,
            "min_agentos_version": self.min_agentos_version,
            "mcp": (
                {
                    "command": self.mcp_command,
                    "args": self.mcp_args,
                    "env": self.mcp_env,
                    "type": self.mcp_type,
                }
                if self.mcp_command
                else None
            ),
            "manifest_hash": self.manifest_hash,
            "source": self.source,
        }

    def _compute_hash(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def load_from_path(manifest_path: str | Path, source: str = "local") -> SkillManifest | None:
        """从本地 manifest 文件加载。支持 yaml/json。"""
        p = Path(manifest_path)
        if not p.exists():
            return None
        text = p.read_text(encoding="utf-8")
        if p.suffix in (".yaml", ".yml"):
            import yaml

            raw = yaml.safe_load(text)
        else:
            raw = json.loads(text)
        return SkillManifest.from_dict(raw, source=source, install_path=str(p.parent))
