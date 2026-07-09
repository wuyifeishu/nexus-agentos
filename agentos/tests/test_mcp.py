"""Tests for MCP client and tool adapter."""

import pytest

from agentos.mcp import (
    MCPClient,
    MCPError,
    MCPPromptInfo,
    MCPResourceInfo,
    MCPServerConfig,
    MCPToolInfo,
)
from agentos.mcp.adapter import MCPToolAdapter, MCPToolRegistry
from agentos.tools.base import PermissionLevel


class TestMCPServerConfig:
    """Server configuration tests."""

    def test_defaults(self):
        config = MCPServerConfig(name="test")
        assert config.name == "test"
        assert config.transport == "stdio"
        assert config.args == []
        assert config.timeout == 30

    def test_custom(self):
        config = MCPServerConfig(
            name="github",
            transport="sse",
            url="http://localhost:8080",
            timeout=60,
        )
        assert config.transport == "sse"
        assert config.url == "http://localhost:8080"
        assert config.timeout == 60


class TestMCPClientLifecycle:
    """Client init and teardown tests (no real server needed)."""

    @pytest.mark.asyncio
    async def test_init_empty(self):
        client = MCPClient()
        assert client.connected_servers == []
        assert client.list_tools() == []
        assert client.list_resources() == []
        assert client.list_prompts() == []

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with MCPClient() as client:
            assert client.connected_servers == []

    @pytest.mark.asyncio
    async def test_connect_unknown_transport(self):
        client = MCPClient()
        config = MCPServerConfig(name="bad", transport="grpc")
        with pytest.raises(MCPError, match="Unknown transport"):
            await client.connect_server(config)

    @pytest.mark.asyncio
    async def test_sse_requires_url(self):
        client = MCPClient()
        config = MCPServerConfig(name="bad", transport="sse")
        with pytest.raises(MCPError, match="URL required"):
            await client.connect_server(config)


class TestMCPToolAdapter:
    """Tool adapter wrapping tests."""

    def test_adapt_tool_basic(self):
        client = MCPClient()
        tool = MCPToolInfo(
            name="read",
            description="Read a file",
            server_name="fs",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        assert adapter.name == "mcp__fs__read"
        assert adapter.description == "Read a file"
        assert "path" in adapter.parameters()["properties"]

    def test_to_openai_schema(self):
        client = MCPClient()
        tool = MCPToolInfo(
            name="search",
            description="Search docs",
            server_name="docs",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        schema = adapter.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "mcp__docs__search"
        assert "q" in schema["function"]["parameters"]["properties"]

    def test_to_anthropic_schema(self):
        client = MCPClient()
        tool = MCPToolInfo(name="run", description="Run command", server_name="shell")
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        schema = adapter.to_anthropic_schema()
        assert schema["name"] == "mcp__shell__run"

    def test_write_operation_detection(self):
        client = MCPClient()
        tool = MCPToolInfo(name="write_file", server_name="fs")
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        assert adapter.is_write_operation({"path": "/tmp/x"})
        assert not adapter.is_read_operation({"path": "/tmp/x"})

    def test_read_operation_detection(self):
        client = MCPClient()
        tool = MCPToolInfo(name="read_file", server_name="fs")
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        assert not adapter.is_write_operation({"path": "/tmp/x"})
        assert adapter.is_read_operation({"path": "/tmp/x"})

    def test_extract_target_path(self):
        client = MCPClient()
        tool = MCPToolInfo(name="tool", server_name="s")
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        assert adapter.extract_target_path({"path": "/a/b"}) == "/a/b"
        assert adapter.extract_target_path({"uri": "file:///x"}) == "file:///x"

    def test_permission_default(self):
        client = MCPClient()
        tool = MCPToolInfo(name="t", server_name="s")
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        assert adapter.permission_level == PermissionLevel.MODERATE

    def test_permission_custom(self):
        client = MCPClient()
        tool = MCPToolInfo(name="t", server_name="s")
        adapter = MCPToolAdapter(
            client=client,
            tool_info=tool,
            permission_level=PermissionLevel.SAFE,
        )
        assert adapter.permission_level == PermissionLevel.SAFE


class TestMCPToolRegistry:
    """Tool registry tests."""

    def test_empty_registry(self):
        client = MCPClient()
        registry = MCPToolRegistry(client)
        assert registry.get_all_tools() == {}
        assert registry.get_tool("nonexistent") is None

    def test_refresh(self):
        client = MCPClient()
        registry = MCPToolRegistry(client)
        registry.refresh()  # Should not raise


class TestMCPDataModels:
    """Data model tests."""

    def test_tool_info_minimal(self):
        info = MCPToolInfo(name="t", server_name="s")
        assert info.description == ""
        assert info.input_schema == {}

    def test_resource_info(self):
        info = MCPResourceInfo(
            uri="file:///data",
            name="config",
            mime_type="application/json",
            server_name="s",
        )
        assert info.uri == "file:///data"
        assert info.mime_type == "application/json"

    def test_prompt_info(self):
        info = MCPPromptInfo(
            name="greet",
            description="Generate greeting",
            arguments=[{"name": "style", "required": True}],
            server_name="s",
        )
        assert len(info.arguments) == 1
        assert info.arguments[0]["required"]


class TestMCPError:
    """Error handling tests."""

    def test_error_basic(self):
        err = MCPError(-32602, "Invalid params")
        assert err.code == -32602
        assert "Invalid params" in str(err)

    def test_error_with_data(self):
        err = MCPError(-1, "custom", data={"detail": "xyz"})
        assert err.data == {"detail": "xyz"}


class TestMCPToolAdapterEdgeCases:
    """Edge case tests for adapter behavior."""

    def test_adapter_empty_schema(self):
        client = MCPClient()
        tool = MCPToolInfo(name="empty", server_name="s")
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        schema = adapter.to_openai_schema()
        assert "properties" in schema["function"]["parameters"]

    def test_adapter_no_description(self):
        client = MCPClient()
        tool = MCPToolInfo(name="t", server_name="s")
        adapter = MCPToolAdapter(client=client, tool_info=tool)
        assert "mcp" in adapter.description.lower()
