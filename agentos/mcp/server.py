"""MCP Server 实现 — 将 AgentOS 暴露为 MCP Server。

支持 stdio JSON-RPC 2.0 传输，暴露 LLM 对话、工具调用、Agent 运行等能力。
其他 MCP 客户端（如 Claude Desktop、Cursor）可直接连接使用。

用法:
    agentos mcp-server          # 以 stdio 模式启动
    agentos mcp-server --port 9000  # 以 HTTP SSE 模式启动（可选）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# ── MCP Server 核心 ─────────────────────────


class MCPServer:
    """MCP Server — stdio JSON-RPC 2.0 传输。

    实现 MCP 协议的 server 端，暴露 AgentOS 能力。
    客户端通过 stdio 发送 JSON-RPC 请求，服务器响应。

    支持的操作:
        - initialize: 协议握手，返回 capabilities
        - tools/list: 列出可用工具
        - tools/call: 调用工具
        - resources/list: 列出可用资源
        - prompts/list: 列出可用提示
    """

    def __init__(
        self,
        server_info=None,
        *,
        name: str = "agentos",
        version: str = "1.5.2",
        tools: list | None = None,
        resources: list | None = None,
        prompts: list | None = None,
    ):
        if server_info is not None:
            if isinstance(server_info, ServerInfo):
                self.name = server_info.name
                self.version = server_info.version
            else:
                # backward compat: first arg is name
                self.name = server_info
                self.version = version
        else:
            self.name = name
            self.version = version
        self._tools: dict[str, Any] = {}
        self._resources: dict[str, MCPResource] = {}
        self._prompts: dict[str, MCPPromptDef] = {}
        self._initialized = False

        for t in tools or []:
            self.register_tool(t)
        for r in resources or []:
            self._resources[r.uri] = r
        for p in prompts or []:
            self._prompts[p.name] = p

        # 内置工具
        self._register_builtin_tools()

    @property
    def info(self) -> ServerInfo:
        return ServerInfo(name=self.name, version=self.version)

    @property
    def tools(self) -> dict[str, Any]:
        return self._tools

    def register_tool(self, tool):
        """注册一个 MCP 工具。兼容 MCPToolDef 和 Tool dataclass。"""
        if hasattr(tool, "name"):
            self._tools[tool.name] = tool
        else:
            # MCPToolDef compat
            self._tools[tool.name] = tool

    async def list_tools(self) -> list:
        """异步列出所有工具。"""
        result = []
        for t in self._tools.values():
            result.append(
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": getattr(t, "input_schema", {}),
                }
            )
        return result

    def run_stdio(self):
        """以 stdio 模式运行 MCP Server（同步阻塞）。"""
        asyncio.run(self._run_stdio_async())

    async def _run_stdio_async(self):
        """异步 stdio 循环。"""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, os.fdopen(sys.stdout.fileno(), "wb")
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, loop)

        logger.info(f"MCP Server '{self.name}' v{self.version} started (stdio)")

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    request = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                response = await self._handle_request(request)
                if response is not None:
                    payload = json.dumps(response, ensure_ascii=False) + "\n"
                    writer.write(payload.encode("utf-8"))
                    await writer.drain()
            except Exception as e:
                logger.error(f"MCP Server error: {e}")
                break

    async def _handle_request(self, request: dict) -> dict | None:
        """处理单个 JSON-RPC 请求。"""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        # 通知类（无 id），不回复
        if req_id is None:
            if method == "notifications/initialized":
                self._initialized = True
            return None

        try:
            result = await self._dispatch(method, params)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        except MCPError as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": e.code, "message": e.message},
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

    async def _dispatch(self, method: str, params: dict) -> Any:
        """路由到对应的处理器。"""
        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
        }
        handler = handlers.get(method)
        if handler is None:
            raise MCPError(-32601, f"Method not found: {method}")
        return await handler(params)

    # ── MCP 协议方法 ──────────────────────

    async def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": self.name,
                "version": self.version,
            },
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
            },
        }

    async def _handle_tools_list(self, params: dict) -> dict:
        tools = []
        for t in self._tools.values():
            tools.append(
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                }
            )
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        tool = self._tools.get(tool_name)
        if tool is None:
            raise MCPError(-32602, f"Unknown tool: {tool_name}")

        try:
            result = (
                tool.handler(arguments)
                if not asyncio.iscoroutinefunction(tool.handler)
                else await tool.handler(arguments)
            )
            return {
                "content": [
                    {"type": "text", "text": str(result) if not isinstance(result, str) else result}
                ]
            }
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }

    async def _handle_resources_list(self, params: dict) -> dict:
        resources = []
        for r in self._resources.values():
            resources.append(
                {
                    "uri": r.uri,
                    "name": r.name,
                    "description": r.description,
                    "mimeType": r.mime_type,
                }
            )
        return {"resources": resources}

    async def _handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        r = self._resources.get(uri)
        if r is None:
            raise MCPError(-32602, f"Unknown resource: {uri}")
        text = r.content() if callable(r.content) else r.content
        return {"contents": [{"uri": uri, "mimeType": r.mime_type, "text": str(text)}]}

    async def _handle_prompts_list(self, params: dict) -> dict:
        prompts = []
        for p in self._prompts.values():
            prompts.append(
                {
                    "name": p.name,
                    "description": p.description,
                    "arguments": p.arguments,
                }
            )
        return {"prompts": prompts}

    async def _handle_prompts_get(self, params: dict) -> dict:
        prompt_name = params.get("name", "")
        prompt_args = params.get("arguments", {})
        p = self._prompts.get(prompt_name)
        if p is None:
            raise MCPError(-32602, f"Unknown prompt: {prompt_name}")
        template = p.template(prompt_args) if callable(p.template) else p.template
        return {
            "description": p.description,
            "messages": [{"role": "user", "content": {"type": "text", "text": template}}],
        }

    # ── 内置工具 ──────────────────────────

    def _register_builtin_tools(self):
        """注册 AgentOS 内置 MCP 工具。"""

        self.register_tool(
            MCPToolDef(
                name="agentos_chat",
                description="使用 AgentOS LLM 进行对话（支持 OpenAI/DeepSeek/Anthropic/Claude/Ollama）",
                input_schema={
                    "type": "object",
                    "properties": {
                        "messages": {
                            "type": "array",
                            "description": "对话消息列表",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "role": {
                                        "type": "string",
                                        "enum": ["system", "user", "assistant"],
                                    },
                                    "content": {"type": "string"},
                                },
                                "required": ["role", "content"],
                            },
                        },
                        "model": {"type": "string", "description": "模型名称，默认从配置读取"},
                        "temperature": {"type": "number", "description": "温度参数（0-2）"},
                        "max_tokens": {"type": "integer", "description": "最大输出 token 数"},
                    },
                    "required": ["messages"],
                },
                handler=self._tool_agentos_chat,
            )
        )

        self.register_tool(
            MCPToolDef(
                name="agentos_list_tools",
                description="列出 AgentOS 中所有可用的工具（含 MCP 工具）",
                input_schema={
                    "type": "object",
                    "properties": {
                        "format": {
                            "type": "string",
                            "enum": ["openai", "anthropic"],
                            "description": "输出格式",
                        },
                    },
                },
                handler=self._tool_list_tools,
            )
        )

        self.register_tool(
            MCPToolDef(
                name="agentos_version",
                description="获取 AgentOS 版本信息",
                input_schema={"type": "object", "properties": {}},
                handler=self._tool_version,
            )
        )

    async def _tool_agentos_chat(self, args: dict) -> str:
        """调用 AgentOS LLM 对话。"""
        try:
            from agentos.llm import LLMClient, LLMMessage
        except ImportError:
            return "Error: AgentOS LLM 模块不可用。请确认已安装 nexus-agentos。"

        messages_raw = args.get("messages", [])
        model = args.get("model")
        temperature = args.get("temperature", 0.7)
        max_tokens = args.get("max_tokens", 4096)

        messages = [LLMMessage(role=m["role"], content=m["content"]) for m in messages_raw]

        client = LLMClient(model=model)
        response = await client.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return response.content

    def _tool_list_tools(self, args: dict) -> str:
        """列出可用工具。"""
        fmt = args.get("format", "openai")
        tools_list = []
        for name, tool in self._tools.items():
            if fmt == "openai":
                tools_list.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": tool.description,
                            "parameters": tool.input_schema,
                        },
                    }
                )
            else:
                tools_list.append(
                    {
                        "name": name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                    }
                )
        return json.dumps(tools_list, ensure_ascii=False, indent=2)

    def _tool_version(self, args: dict) -> str:
        """返回版本信息。"""
        try:
            from agentos import __version__
        except ImportError:
            __version__ = self.version
        return json.dumps(
            {
                "name": self.name,
                "version": self.version,
                "agentos_version": __version__,
                "tools_count": len(self._tools),
            },
            ensure_ascii=False,
        )


# ── 数据结构 ───────────────────────────────


class MCPToolDef:
    """MCP 工具定义。"""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler,
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler


class MCPResource:
    """MCP 资源定义。"""

    def __init__(
        self,
        uri: str,
        name: str = "",
        description: str = "",
        mime_type: str = "text/plain",
        content: Any = "",
    ):
        self.uri = uri
        self.name = name
        self.description = description
        self.mime_type = mime_type
        self.content = content


class MCPPromptDef:
    """MCP 提示模板定义。"""

    def __init__(
        self,
        name: str,
        description: str = "",
        arguments: list = None,
        template: Any = "",
    ):
        self.name = name
        self.description = description
        self.arguments = arguments or []
        self.template = template


class MCPError(Exception):
    """MCP 协议错误（与服务端共用异常类）。"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"MCP Error [{code}]: {message}")


# ── 便捷函数 ───────────────────────────────


def create_default_server() -> MCPServer:
    """创建预配置了 AgentOS 内置工具的 MCP Server。"""
    return MCPServer(
        name="agentos",
        version="1.5.2",
    )


def start_mcp_server(port: int = 0):
    """启动 MCP Server。

    Args:
        port: 0 表示 stdio 模式，>0 表示 HTTP SSE 模式（暂未实现）。
    """
    if port == 0:
        server = create_default_server()
        server.run_stdio()
    else:
        print("MCP HTTP SSE 模式暂未实现。请使用 stdio 模式（port=0）。")
        sys.exit(1)


# ── ServerInfo & Tool (test compatibility) ──
from dataclasses import dataclass, field  # noqa: E402


@dataclass
class ServerInfo:
    name: str
    version: str
    description: str = ""


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    call: callable = field(default=lambda params: None)


@dataclass
class AgentCard:
    agent_id: str
    name: str
    version: str
    capabilities: list = field(default_factory=list)
    endpoint: str = ""
