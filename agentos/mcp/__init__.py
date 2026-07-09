"""MCP (Model Context Protocol) client implementation for AgentOS.

Full MCP client with JSON-RPC 2.0, initialize handshake, tool/resource/prompt
discovery, dual transport (stdio + SSE), Sampling, Logging, Roots.
Designed to be used as async context manager.

v1.14.0: Added Sampling, Resource Templates, Logging, Roots support.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Data Models ────────────────────────────


@dataclass
class MCPServerConfig:
    """Configuration for connecting to an MCP server."""

    name: str
    transport: str = "stdio"  # stdio | sse
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    capabilities: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolInfo:
    """Metadata for a discovered MCP tool."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


@dataclass
class MCPResourceInfo:
    """Metadata for a discovered MCP resource."""

    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    server_name: str = ""


@dataclass
class MCPPromptInfo:
    """Metadata for a discovered MCP prompt."""

    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)
    server_name: str = ""


# ── JSON-RPC 2.0 Transport ──────────────────


class MCPTransport(ABC):
    """Abstract transport layer for MCP JSON-RPC 2.0 communication."""

    @abstractmethod
    async def connect(self, config: MCPServerConfig) -> None: ...

    @abstractmethod
    async def send_request(self, method: str, params: dict | None = None) -> dict[str, Any]: ...

    @abstractmethod
    async def send_notification(self, method: str, params: dict | None = None) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


class StdioTransport(MCPTransport):
    """MCP transport over subprocess stdio.

    Communicates with an MCP server launched as a child process
    using newline-delimited JSON-RPC 2.0 messages.
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = asyncio.Lock()
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def connect(self, config: MCPServerConfig) -> None:
        cmd = config.command or "npx"
        full_args = [cmd] + list(config.args)
        env = {**__import__("os").environ, **config.env}

        self._proc = subprocess.Popen(
            full_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=False,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Continuously read JSON-RPC responses from stdout."""
        loop = asyncio.get_event_loop()
        while self._proc and self._proc.poll() is None:
            try:
                line = await loop.run_in_executor(None, self._proc.stdout.readline)
                if not line:
                    break
                data = json.loads(line.decode("utf-8"))
                req_id = data.get("id")
                if req_id is not None and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if "error" in data:
                        future.set_exception(
                            MCPError(
                                data["error"].get("code", -1),
                                data["error"].get("message", "Unknown error"),
                            )
                        )
                    else:
                        future.set_result(data.get("result", {}))
            except Exception:
                continue

    async def send_request(self, method: str, params: dict | None = None) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request and await the response."""
        if not self._proc or self._proc.poll() is not None:
            raise MCPError(-32000, "MCP server process is not running")

        async with self._lock:
            self._request_id += 1
            req_id = self._request_id
            request = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params or {},
            }

            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending[req_id] = future

            payload = json.dumps(request).encode("utf-8") + b"\n"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._proc.stdin.write, payload)
            await loop.run_in_executor(None, self._proc.stdin.flush)

            try:
                return await asyncio.wait_for(future, timeout=30)
            except TimeoutError:
                self._pending.pop(req_id, None)
                raise MCPError(-32001, "Request timed out")

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        """Send a JSON-RPC 2.0 notification (no response expected)."""
        if not self._proc or self._proc.poll() is not None:
            return

        async with self._lock:
            notification = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }
            payload = json.dumps(notification).encode("utf-8") + b"\n"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._proc.stdin.write, payload)
            await loop.run_in_executor(None, self._proc.stdin.flush)

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


class SSETransport(MCPTransport):
    """MCP transport over HTTP SSE (Server-Sent Events).

    Connects to a remote MCP server via HTTP POST for requests
    and SSE stream for responses.
    """

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._sse_task: asyncio.Task | None = None
        self._response_queue: asyncio.Queue = asyncio.Queue()
        self._message_endpoint: str = ""
        self._sse_endpoint: str = ""

    async def connect(self, config: MCPServerConfig) -> None:
        if not config.url:
            raise MCPError(-32602, "URL required for SSE transport")

        self._message_endpoint = config.url.rstrip("/") + "/message"
        self._sse_endpoint = config.url.rstrip("/") + "/sse"
        self._client = httpx.AsyncClient(timeout=config.timeout)
        self._sse_task = asyncio.create_task(self._sse_loop())

    async def _sse_loop(self) -> None:
        """Read SSE events and route to pending futures."""
        while self._client:
            try:
                async with self._client.stream("GET", self._sse_endpoint) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            try:
                                data = json.loads(data_str)
                                req_id = data.get("id")
                                if req_id is not None and req_id in self._pending:
                                    future = self._pending.pop(req_id)
                                    if "error" in data:
                                        future.set_exception(
                                            MCPError(
                                                data["error"].get("code", -1),
                                                data["error"].get("message", ""),
                                            )
                                        )
                                    else:
                                        future.set_result(data.get("result", {}))
                            except json.JSONDecodeError:
                                continue
            except Exception:
                await asyncio.sleep(1)

    async def send_request(self, method: str, params: dict | None = None) -> dict[str, Any]:
        if not self._client:
            raise MCPError(-32000, "SSE transport not connected")

        self._request_id += 1
        req_id = self._request_id
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        resp = await self._client.post(self._message_endpoint, json=request)
        resp.raise_for_status()

        try:
            return await asyncio.wait_for(future, timeout=30)
        except TimeoutError:
            self._pending.pop(req_id, None)
            raise MCPError(-32001, "SSE request timed out")

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        if not self._client:
            return
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        await self._client.post(self._message_endpoint, json=notification)

    async def close(self) -> None:
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None


# ── Error ────────────────────────────────────


class MCPError(Exception):
    """MCP protocol error."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"MCP Error [{code}]: {message}")


# ── Full Client ─────────────────────────────


class MCPClient:
    """Full MCP client for connecting to and using MCP servers.

    Supports stdio (local process) and SSE (remote HTTP) transports.

    Usage:
        async with MCPClient() as client:
            await client.connect_server(MCPServerConfig(
                name="filesystem",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            ))
            tools = client.list_tools()
            result = await client.call_tool("filesystem", "read_file", {"path": "/tmp/test.txt"})
    """

    TRANSPORTS = {
        "stdio": StdioTransport,
        "sse": SSETransport,
    }

    def __init__(self):
        self._servers: dict[str, MCPTransport] = {}
        self._server_configs: dict[str, MCPServerConfig] = {}
        self._tools: dict[str, MCPToolInfo] = {}
        self._resources: dict[str, MCPResourceInfo] = {}
        self._prompts: dict[str, MCPPromptInfo] = {}
        self._server_capabilities: dict[str, dict[str, Any]] = {}

    async def __aenter__(self) -> MCPClient:
        return self

    async def __aexit__(self, *args) -> None:
        await self.close_all()

    async def connect_server(self, config: MCPServerConfig) -> dict[str, Any]:
        """Connect to an MCP server and perform initialization handshake.

        Returns the server's capabilities dict.
        """
        transport_cls = self.TRANSPORTS.get(config.transport)
        if not transport_cls:
            raise MCPError(-32601, f"Unknown transport: {config.transport}")

        transport = transport_cls()
        await transport.connect(config)

        # MCP Initialize handshake
        init_result = await transport.send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": config.capabilities or {},
                "clientInfo": {
                    "name": "agentos-mcp-client",
                    "version": "1.0.0",
                },
            },
        )

        # Send initialized notification
        await transport.send_notification("notifications/initialized")

        self._servers[config.name] = transport
        self._server_configs[config.name] = config
        self._server_capabilities[config.name] = init_result.get("capabilities", {})

        # Discover tools, resources, prompts
        await self._discover_server(config.name)

        return init_result

    async def _discover_server(self, server_name: str) -> None:
        """Discover all capabilities of a connected server."""
        transport = self._servers[server_name]
        caps = self._server_capabilities.get(server_name, {})

        # Discover tools
        if caps.get("tools"):
            try:
                result = await transport.send_request("tools/list")
                for tool in result.get("tools", []):
                    full_name = f"mcp__{server_name}__{tool['name']}"
                    self._tools[full_name] = MCPToolInfo(
                        name=tool["name"],
                        description=tool.get("description", ""),
                        input_schema=tool.get("inputSchema", {}),
                        server_name=server_name,
                    )
            except MCPError:
                logger.debug(f"Server '{server_name}' tools/list not supported")

        # Discover resources
        if caps.get("resources"):
            try:
                result = await transport.send_request("resources/list")
                for res in result.get("resources", []):
                    self._resources[res["uri"]] = MCPResourceInfo(
                        uri=res["uri"],
                        name=res.get("name", ""),
                        description=res.get("description", ""),
                        mime_type=res.get("mimeType", ""),
                        server_name=server_name,
                    )
            except MCPError:
                logger.debug(f"Server '{server_name}' resources/list not supported")

        # Discover prompts
        if caps.get("prompts"):
            try:
                result = await transport.send_request("prompts/list")
                for prompt in result.get("prompts", []):
                    key = f"{server_name}__{prompt['name']}"
                    self._prompts[key] = MCPPromptInfo(
                        name=prompt["name"],
                        description=prompt.get("description", ""),
                        arguments=prompt.get("arguments", []),
                        server_name=server_name,
                    )
            except MCPError:
                logger.debug(f"Server '{server_name}' prompts/list not supported")

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call a tool on a connected MCP server.

        Args:
            server_name: Name of the MCP server.
            tool_name: Name of the tool to call.
            arguments: Tool arguments dict.

        Returns:
            Tool result content (text or structured data).
        """
        if server_name not in self._servers:
            raise MCPError(-32602, f"Server '{server_name}' not connected")

        transport = self._servers[server_name]
        result = await transport.send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments or {},
            },
        )

        content = result.get("content", [])
        if not content:
            return ""

        # Extract text from content blocks
        texts = []
        for block in content:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif block.get("type") == "resource":
                texts.append(f"[Resource: {block.get('resource', {}).get('uri', '')}]")
            elif block.get("type") == "image":
                texts.append(f"[Image: {block.get('data', '')[:50]}...]")

        return "\n".join(texts) if texts else content

    async def read_resource(self, server_name: str, uri: str) -> dict[str, Any]:
        """Read a resource from a connected MCP server."""
        if server_name not in self._servers:
            raise MCPError(-32602, f"Server '{server_name}' not connected")

        transport = self._servers[server_name]
        result = await transport.send_request("resources/read", {"uri": uri})
        return result.get("contents", [{}])[0] if result.get("contents") else {}

    async def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Get a prompt template from a connected MCP server."""
        if server_name not in self._servers:
            raise MCPError(-32602, f"Server '{server_name}' not connected")

        transport = self._servers[server_name]
        result = await transport.send_request(
            "prompts/get",
            {
                "name": prompt_name,
                "arguments": arguments or {},
            },
        )
        return result

    def list_tools(self, server_name: str | None = None) -> list[MCPToolInfo]:
        """List discovered tools, optionally filtered by server."""
        tools = list(self._tools.values())
        if server_name:
            tools = [t for t in tools if t.server_name == server_name]
        return tools

    def list_resources(self, server_name: str | None = None) -> list[MCPResourceInfo]:
        """List discovered resources, optionally filtered by server."""
        resources = list(self._resources.values())
        if server_name:
            resources = [r for r in resources if r.server_name == server_name]
        return resources

    def list_prompts(self, server_name: str | None = None) -> list[MCPPromptInfo]:
        """List discovered prompts, optionally filtered by server."""
        prompts = list(self._prompts.values())
        if server_name:
            prompts = [p for p in prompts if p.server_name == server_name]
        return prompts

    def get_server_capabilities(self, server_name: str) -> dict[str, Any]:
        """Get the capabilities reported by a server."""
        return self._server_capabilities.get(server_name, {})

    def get_tool_schemas(
        self,
        server_name: str | None = None,
        format: str = "openai",
    ) -> list[dict[str, Any]]:
        """Export tool schemas in OpenAI or Anthropic function format.

        Args:
            server_name: Optional filter by server.
            format: 'openai' or 'anthropic'.

        Returns:
            List of function/tool schema dicts.
        """
        tools = self.list_tools(server_name)
        schemas = []

        for tool in tools:
            params = tool.input_schema
            if format == "openai":
                schemas.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"mcp__{tool.server_name}__{tool.name}",
                            "description": tool.description,
                            "parameters": params,
                        },
                    }
                )
            elif format == "anthropic":
                schemas.append(
                    {
                        "name": f"mcp__{tool.server_name}__{tool.name}",
                        "description": tool.description,
                        "input_schema": params,
                    }
                )

        return schemas

    @property
    def connected_servers(self) -> list[str]:
        """List names of connected servers."""
        return list(self._servers.keys())

    async def disconnect_server(self, server_name: str) -> None:
        """Disconnect from a specific MCP server."""
        if server_name in self._servers:
            await self._servers[server_name].close()
            del self._servers[server_name]
            self._server_configs.pop(server_name, None)
            self._server_capabilities.pop(server_name, None)
            # Remove associated tools/resources/prompts
            self._tools = {k: v for k, v in self._tools.items() if v.server_name != server_name}
            self._resources = {
                k: v for k, v in self._resources.items() if v.server_name != server_name
            }
            self._prompts = {k: v for k, v in self._prompts.items() if v.server_name != server_name}

    async def close_all(self) -> None:
        """Disconnect from all MCP servers."""
        for name in list(self._servers.keys()):
            await self.disconnect_server(name)


# ── Convenience Functions ────────────────────


async def connect_mcp_servers(
    configs: list[MCPServerConfig],
) -> MCPClient:
    """Connect to multiple MCP servers at once.

    Usage:
        client = await connect_mcp_servers([
            MCPServerConfig(name="filesystem", command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]),
            MCPServerConfig(name="github", command="npx",
                args=["-y", "@modelcontextprotocol/server-github"],
                env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ["GITHUB_TOKEN"]}),
        ])
    """
    client = MCPClient()
    for config in configs:
        await client.connect_server(config)
    return client


# ── MCP Server (v1.5.2) ─────────────────────

from agentos.mcp.server import (  # noqa: E402
    MCPPromptDef,
    MCPResource,
    MCPServer,
    MCPToolDef,
    create_default_server,
    start_mcp_server,
)

__all__ = [
    "MCPServerConfig",
    "MCPToolInfo",
    "MCPResourceInfo",
    "MCPPromptInfo",
    "MCPError",
    "MCPTransport",
    "StdioTransport",
    "SSETransport",
    "MCPClient",
    "connect_mcp_servers",
    # MCP Server (v1.5.2)
    "MCPServer",
    "MCPToolDef",
    "MCPResource",
    "MCPPromptDef",
    "create_default_server",
    "start_mcp_server",
    # MCP Sampling, Resource Templates, Logging, Roots (v1.14.0)
    "MCPClientSampling",
    "SamplingRequest",
    "SamplingResponse",
    "SamplingMessage",
    "SamplingContentBlock",
    "SamplingRole",
    "SamplingError",
    "mock_llm_call",
    "MCPResourceTemplate",
    "MCPLogLevel",
    "MCPLoggingHandler",
    "MCPRoot",
    # MCP Tool Adapter (v1.16.10)
    "MCPToolAdapter",
    "MCPAdapter",
    # Built-in MCP Servers (v1.16.11)
    "FilesystemServer",
    "WebFetchServer",
    "MemoryServer",
    "SearchServer",
    "GitServer",
    "ShellServer",
    "CodeServer",
    "TextServer",
    "BuiltinMCPRegistry",
]

# ── Convenience alias ──
from agentos.mcp.adapter import MCPToolAdapter  # noqa: E402, F811

MCPAdapter = MCPToolAdapter

# ── Built-in MCP Servers ──
from agentos.mcp.builtin_servers import (  # noqa: E402
    BuiltinMCPRegistry,
    CodeServer,
    FilesystemServer,
    GitServer,
    MemoryServer,
    SearchServer,
    ShellServer,
    TextServer,
    WebFetchServer,
)
