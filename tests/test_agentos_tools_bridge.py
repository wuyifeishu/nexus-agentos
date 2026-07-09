"""Tests for agentos.tools.bridge — Tool Bridge between BaseTool and ToolExecutor."""

from unittest.mock import MagicMock

from agentos.tools.base import BaseTool, ToolResult
from agentos.tools.bridge import (
    base_tool_to_llm_tool,
    bridge_registry_to_executor,
    make_handler,
)


class DummyTool(BaseTool):
    """A dummy tool for testing."""

    permission_level = "safe"

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "Does dummy things"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search query"},
                "limit": {"type": "integer", "description": "max results", "enum": [5, 10, 20]},
            },
            "required": ["query"],
        }

    async def execute(self, input_data: dict) -> ToolResult:
        return ToolResult(call_id="d1", output=f"found: {input_data.get('query', '')}")


class ErrorTool(BaseTool):
    permission_level = "safe"

    @property
    def name(self) -> str:
        return "err_tool"

    @property
    def description(self) -> str:
        return "fails"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, input_data: dict) -> ToolResult:
        return ToolResult(call_id="e1", error="something broke")


class TestBaseToolToLLMTool:
    def test_empty_params(self):
        class MinimalTool(BaseTool):
            permission_level = "safe"

            @property
            def name(self) -> str:
                return "min"

            @property
            def description(self) -> str:
                return "minimal"

            @property
            def parameters(self) -> dict:
                return {"type": "object", "properties": {}, "required": []}

            async def execute(self, input_data: dict) -> ToolResult:
                return ToolResult(call_id="m1", output="ok")

        tool = MinimalTool()
        llm_tool = base_tool_to_llm_tool(tool)
        assert llm_tool.function.name == "min"
        assert llm_tool.function.description == "minimal"

    def test_full_params(self):
        tool = DummyTool()
        llm_tool = base_tool_to_llm_tool(tool)
        assert llm_tool.function.name == "dummy"
        assert "query" in llm_tool.function.parameters
        assert "limit" in llm_tool.function.parameters
        assert llm_tool.function.parameters["limit"].enum == [5, 10, 20]
        assert llm_tool.function.required == ["query"]


class TestMakeHandler:
    def test_sync_handler_success(self):
        tool = DummyTool()
        handler = make_handler(tool)
        result = handler(query="test")
        assert result == "found: test"

    def test_sync_handler_error(self):
        tool = ErrorTool()
        handler = make_handler(tool)
        result = handler()
        assert "error" in result
        assert "something broke" in result

    def test_handler_no_output(self):
        class EmptyTool(BaseTool):
            permission_level = "safe"

            @property
            def name(self) -> str:
                return "empty"

            @property
            def description(self) -> str:
                return ""

            @property
            def parameters(self) -> dict:
                return {"type": "object", "properties": {}, "required": []}

            async def execute(self, input_data: dict) -> ToolResult:
                return ToolResult(call_id="e1")

        tool = EmptyTool()
        handler = make_handler(tool)
        result = handler()
        assert result == ""


class TestBridgeRegistryToExecutor:
    def test_bridge_single_tool(self):
        registry = MagicMock()
        tool = DummyTool()
        registry.list_names.return_value = ["dummy"]
        registry.get.return_value = tool

        executor = MagicMock()
        bridge_registry_to_executor(registry, executor)

        executor.register.assert_called_once()

    def test_bridge_skip_none(self):
        registry = MagicMock()
        registry.list_names.return_value = ["missing"]
        registry.get.return_value = None

        executor = MagicMock()
        bridge_registry_to_executor(registry, executor)

        executor.register.assert_not_called()

    def test_bridge_multiple_tools(self):
        registry = MagicMock()
        d1 = DummyTool()
        registry.list_names.return_value = ["dummy", "err"]
        registry.get.side_effect = [d1, None]

        executor = MagicMock()
        bridge_registry_to_executor(registry, executor)
        assert executor.register.call_count == 1
