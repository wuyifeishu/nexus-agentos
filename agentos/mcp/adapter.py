"""MCP Tool Adapter for AgentOS.

Wraps MCP tools as AgentOS BaseTool instances, enabling seamless
integration with the AgentOS tool system and permission model.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agentos.mcp import MCPClient, MCPToolInfo
from agentos.tools.base import BaseTool, PermissionLevel, ToolResult


class MCPToolAdapter(BaseTool):
    """Adapts an MCP tool to the AgentOS BaseTool interface.

    Wraps a remote MCP tool call in the standard BaseTool protocol,
    handling execution, schema export, and permission routing.

    Usage:
        adapter = MCPToolAdapter(
            client=mcp_client,
            tool_info=tool_info,
            permission_level=PermissionLevel.MODERATE,
        )
        result = await adapter.execute({"path": "/tmp/test.txt"})
    """

    def __init__(
        self,
        client: MCPClient,
        tool_info: MCPToolInfo,
        permission_level: PermissionLevel = PermissionLevel.MODERATE,
        tool_id: Optional[str] = None,
    ):
        """Initialize the adapter.

        Args:
            client: Connected MCPClient instance.
            tool_info: Tool metadata from MCP discovery.
            permission_level: AgentOS permission level for this tool.
            tool_id: Optional unique tool identifier.
        """
        self._client = client
        self._tool_info = tool_info
        self._server_name = tool_info.server_name
        self._tool_name = tool_info.name
        self._id = tool_id or f"mcp__{self._server_name}__{self._tool_name}"
        self.permission_level = permission_level

    @property
    def name(self) -> str:
        return self._id

    @property
    def description(self) -> str:
        return self._tool_info.description or f"MCP tool: {self._tool_name}"

    def parameters(self) -> dict:
        """Return the JSON Schema for tool parameters."""
        return self._tool_info.input_schema

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        """Execute the MCP tool and wrap result in ToolResult."""
        try:
            result = await self._client.call_tool(
                self._server_name,
                self._tool_name,
                arguments,
            )
            return ToolResult.ok(call_id=str(id(arguments)), output=str(result))
        except Exception as e:
            return ToolResult.fail(
                call_id=str(id(arguments)),
                error=f"MCP tool '{self._tool_name}' error: {e}",
            )

    def to_openai_schema(self) -> dict:
        params = self._tool_info.input_schema
        return {
            "type": "function",
            "function": {
                "name": self._id,
                "description": self._tool_info.description or "",
                "parameters": {
                    **params,
                    "title": params.get("title", self._id),
                } if params else {"type": "object", "properties": {}},
            },
        }

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self._id,
            "description": self._tool_info.description or "",
            "input_schema": self._tool_info.input_schema or {
                "type": "object",
                "properties": {},
            },
        }

    def is_write_operation(self, arguments: dict) -> bool:
        """Heuristic: MCP tools with names containing write/update/create/delete
        or having 'mode' parameter are treated as write operations."""
        write_keywords = ("write", "update", "create", "delete", "remove", "put", "patch", "post")
        name_lower = self._tool_name.lower()
        for kw in write_keywords:
            if kw in name_lower:
                return True
        return arguments.get("mode") == "write"

    def is_read_operation(self, arguments: dict) -> bool:
        return not self.is_write_operation(arguments)

    def extract_target_path(self, arguments: dict) -> Optional[str]:
        """Extract file path from common MCP tool arguments."""
        for key in ("path", "uri", "file_path", "filepath"):
            if key in arguments:
                return arguments[key]
        return None


class MCPToolRegistry:
    """Registry that adapts all tools from an MCPClient into BaseTool instances.

    Creates MCPToolAdapter wrappers for each discovered tool, with
    appropriate permission level assignment.

    Usage:
        registry = MCPToolRegistry(client)
        tools = registry.get_all_tools()
        # tools can now be used with any AgentOS agent
    """

    def __init__(
        self,
        client: MCPClient,
        default_permission: PermissionLevel = PermissionLevel.MODERATE,
    ):
        """Initialize the registry.

        Args:
            client: Connected MCPClient with discovered tools.
            default_permission: Default permission level for adapted tools.
        """
        self._client = client
        self._default_permission = default_permission
        self._adapters: Dict[str, MCPToolAdapter] = {}
        self._build_adapters()

    def _build_adapters(self) -> None:
        """Rebuild tool adapters from the current client state."""
        self._adapters.clear()
        for tool_info in self._client.list_tools():
            adapter = MCPToolAdapter(
                client=self._client,
                tool_info=tool_info,
                permission_level=self._default_permission,
            )
            self._adapters[adapter.name] = adapter

    def get_all_tools(self) -> Dict[str, BaseTool]:
        """Return all adapted tools as name -> BaseTool mapping."""
        return dict(self._adapters)

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a single adapted tool by name."""
        return self._adapters.get(name)

    def get_tool_schemas(self, format: str = "openai") -> list:
        """Export schemas for all adapted tools."""
        return [t.to_openai_schema() for t in self._adapters.values()]

    def refresh(self) -> None:
        """Refresh the registry to pick up new tools."""
        self._build_adapters()
