"""
AgentOS v0.40 MCP Server — 将AgentOS暴露为MCP Server。
支持工具列表、资源、提示模板的MCP协议暴露。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, Any


logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """MCP 服务端配置。"""
    name: str = "AgentOS-MCP-Server"
    version: str = "0.40.0"
    transport: str = "stdio"  # stdio | sse | streamable-http
    host: str = "0.0.0.0"
    port: int = 9000


@dataclass
class MCPTool:
    """MCP工具定义。"""
    name: str
    description: str
    input_schema: dict
    handler: Callable
    annotations: dict = field(default_factory=dict)


@dataclass
class MCPResource:
    """MCP资源定义。"""
    uri: str
    name: str
    description: str = ""
    mime_type: str = "text/plain"
    handler: Callable | None = None


@dataclass
class MCPPrompt:
    """MCP提示模板。"""
    name: str
    description: str = ""
    arguments: list[dict] = field(default_factory=list)
    template: str = ""


class MCPServer:
    """MCP Server核心 — 将AgentOS能力以MCP协议暴露。"""

    JSONRPC_VERSION = "2.0"

    def __init__(self, config: MCPServerConfig | None = None):
        self.config = config or MCPServerConfig()
        self._tools: dict[str, MCPTool] = {}
        self._resources: dict[str, MCPResource] = {}
        self._prompts: dict[str, MCPPrompt] = {}
        self._initialized = False
        self._session_id: str | None = None

    # ── 注册 ──────────────────────────────────────

    def register_tool(self, tool: MCPTool):
        self._tools[tool.name] = tool
        logger.info(f"MCP tool registered: {tool.name}")

    def register_resource(self, resource: MCPResource):
        self._resources[resource.uri] = resource

    def register_prompt(self, prompt: MCPPrompt):
        self._prompts[prompt.name] = prompt

    # ── 协议处理 ──────────────────────────────────

    def handle_request(self, raw: dict) -> dict:
        """处理MCP JSON-RPC请求。"""
        method = raw.get("method", "")
        params = raw.get("params", {})
        req_id = raw.get("id")

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "notifications/initialized":
                self._initialized = True
                return {}
            elif method == "tools/list":
                result = self._handle_tools_list()
            elif method == "tools/call":
                result = self._handle_tool_call(params)
            elif method == "resources/list":
                result = self._handle_resources_list()
            elif method == "resources/read":
                result = self._handle_resource_read(params)
            elif method == "prompts/list":
                result = self._handle_prompts_list()
            elif method == "prompts/get":
                result = self._handle_prompt_get(params)
            else:
                return self._error(req_id, -32601, f"Method not found: {method}")

            return self._success(req_id, result)
        except Exception as e:
            logger.exception(f"MCP handler error: {e}")
            return self._error(req_id, -32603, str(e))

    def _success(self, req_id, result) -> dict:
        if req_id is None:
            return {}
        return {"jsonrpc": self.JSONRPC_VERSION, "id": req_id, "result": result}

    def _error(self, req_id, code: int, message: str) -> dict:
        if req_id is None:
            return {}
        return {"jsonrpc": self.JSONRPC_VERSION, "id": req_id, "error": {"code": code, "message": message}}

    # ── 方法实现 ──────────────────────────────────

    def _handle_initialize(self, params: dict) -> dict:
        client_info = params.get("clientInfo", {})
        self._session_id = params.get("sessionId")
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": {"name": self.config.name, "version": self.config.version},
        }

    def _handle_tools_list(self) -> dict:
        tools = []
        for t in self._tools.values():
            tools.append({
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema,
                "annotations": t.annotations,
            })
        return {"tools": tools}

    def _handle_tool_call(self, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")

        result = tool.handler(arguments)
        content = []
        if isinstance(result, dict):
            if "content" in result:
                content = result["content"]
            else:
                content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
        elif isinstance(result, str):
            content = [{"type": "text", "text": result}]
        else:
            content = [{"type": "text", "text": str(result)}]

        return {"content": content}

    def _handle_resources_list(self) -> dict:
        resources = []
        for r in self._resources.values():
            resources.append({"uri": r.uri, "name": r.name, "description": r.description, "mimeType": r.mime_type})
        return {"resources": resources}

    def _handle_resource_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        resource = self._resources.get(uri)
        if not resource:
            raise ValueError(f"Resource not found: {uri}")
        text = resource.handler() if resource.handler else ""
        return {"contents": [{"uri": uri, "mimeType": resource.mime_type, "text": text}]}

    def _handle_prompts_list(self) -> dict:
        prompts = []
        for p in self._prompts.values():
            prompts.append({"name": p.name, "description": p.description, "arguments": p.arguments})
        return {"prompts": prompts}

    def _handle_prompt_get(self, params: dict) -> dict:
        name = params.get("name", "")
        prompt = self._prompts.get(name)
        if not prompt:
            raise ValueError(f"Prompt not found: {name}")
        return {"description": prompt.description, "messages": [{"role": "user", "content": {"type": "text", "text": prompt.template}}]}

    # ── 统计 ──────────────────────────────────────

    def stats(self) -> dict:
        return {"tools": len(self._tools), "resources": len(self._resources), "prompts": len(self._prompts), "transport": self.config.transport}


class MCPClient:
    """MCP客户端 — AgentOS中Agent连接到外部MCP Server。"""

    def __init__(self, server_url: str, transport: str = "stdio"):
        self.server_url = server_url
        self.transport = transport
        self._tools: list[dict] = []
        self._connected = False

    async def connect(self):
        # 模拟连接（实际生产环境用mcp SDK）
        self._connected = True
        logger.info(f"MCP client connected to {self.server_url}")

    async def list_tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict = {}) -> dict:
        logger.info(f"MCP client calling tool: {name}")
        return {"result": f"Simulated call to {name}"}

    def disconnect(self):
        self._connected = False
