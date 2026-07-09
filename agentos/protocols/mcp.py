"""
AgentOS v0.20 MCP (Model Context Protocol) 客户端。
支持 stdio / SSE / WebSocket 三种传输方式。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPServerConfig:
    """MCP 服务端配置。"""

    name: str
    transport: str = "stdio"  # stdio | sse | ws
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPToolSchema:
    """MCP 工具 Schema。"""

    name: str
    description: str
    input_schema: dict


# ── 传输层 ──────────────────────────────────────


class MCPTransport(ABC):
    """MCP 传输协议。"""

    @abstractmethod
    async def connect(self, config: MCPServerConfig): ...

    @abstractmethod
    async def send(self, method: str, params: dict | None = None) -> dict: ...

    @abstractmethod
    async def close(self): ...


class StdioTransport(MCPTransport):
    """通过 subprocess 与 MCP Server 通信。"""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = asyncio.Lock()

    async def connect(self, config: MCPServerConfig):
        self._proc = subprocess.Popen(
            [config.command or "npx"] + config.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**__import__("os").environ, **config.env},
        )

    async def send(self, method: str, params: dict | None = None) -> dict:
        async with self._lock:
            msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1})
            self._proc.stdin.write((msg + "\n").encode())
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
            return json.loads(line)

    async def close(self):
        if self._proc:
            self._proc.terminate()


class SSETransport(MCPTransport):
    """通过 HTTP SSE 与远程 MCP Server 通信。"""

    async def connect(self, config: MCPServerConfig):
        import httpx

        self._client = httpx.AsyncClient(base_url=config.url, timeout=30)

    async def send(self, method: str, params: dict | None = None) -> dict:
        resp = await self._client.post(
            "/message", json={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
        )
        return resp.json()

    async def close(self):
        if hasattr(self, "_client"):
            await self._client.aclose()


# ── MCP 客户端 ──────────────────────────────────


class MCPClient:
    """MCP 协议客户端，管理多个 MCP Server 连接。"""

    TRANSPORTS = {"stdio": StdioTransport, "sse": SSETransport}

    def __init__(self):
        self._servers: dict[str, MCPTransport] = {}
        self._tools: dict[str, MCPToolSchema] = {}

    async def connect_server(self, config: MCPServerConfig):
        transport_cls = self.TRANSPORTS.get(config.transport, StdioTransport)
        transport = transport_cls()
        await transport.connect(config)
        self._servers[config.name] = transport
        # 拉取工具列表
        result = await self._list_tools(config.name)
        for tool in result.get("tools", []):
            schema = MCPToolSchema(
                name=f"mcp_{config.name}_{tool['name']}",
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", {}),
            )
            self._tools[schema.name] = schema

    async def _list_tools(self, server_name: str) -> dict:
        transport = self._servers[server_name]
        return await transport.send("tools/list")

    async def call_tool(self, full_name: str, arguments: dict) -> Any:
        full_name.replace("mcp_", "", 1)
        # 找到所属server
        for name in self._servers:
            if full_name.startswith(f"mcp_{name}_"):
                tool_name = full_name[len(f"mcp_{name}_") + 1 :]
                transport = self._servers[name]
                result = await transport.send(
                    "tools/call", {"name": tool_name, "arguments": arguments}
                )
                return result.get("content", [{}])[0].get("text", "")
        raise ValueError(f"Unknown MCP tool: {full_name}")

    def get_mcp_tool_schemas(self) -> list[dict]:
        """转为 OpenAI function 格式。"""
        schemas = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )
        return schemas

    async def close_all(self):
        for transport in self._servers.values():
            await transport.close()
