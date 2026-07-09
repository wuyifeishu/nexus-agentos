"""Tests for agentos.tools.bridge — BaseTool to LLMTool bridging."""

from unittest.mock import MagicMock

from agentos.llm.base import Tool as LLMTool
from agentos.tools.base import BaseTool, ToolResult
from agentos.tools.bridge import (
    base_tool_to_llm_tool,
    bridge_registry_to_executor,
    make_handler,
)


class FakeTool(BaseTool):
    """Simple tool for testing bridge."""
    name = "fake_tool"
    description = "A test tool"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "A name"},
            "count": {"type": "integer", "description": "A count"},
        },
        "required": ["name"],
    }

    async def execute(self, inputs: dict) -> ToolResult:
        return ToolResult(
            call_id=inputs.get("call_id", "fake-001"),
            output=f"Hello {inputs.get('name', 'World')}",
        )


class FakeMinimalTool(BaseTool):
    """Tool with minimal parameters."""
    name = "minimal"
    description = "Minimal test tool"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, inputs: dict) -> ToolResult:
        return ToolResult(call_id="min-001", output="minimal output")


class FakeErrorTool(BaseTool):
    """Tool that always returns an error."""
    name = "error_tool"
    description = "Always errors"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, inputs: dict) -> ToolResult:
        return ToolResult(call_id="err-001", error="Something went wrong")


class TestBaseToolToLLMTool:
    def test_converts_params(self):
        tool = FakeTool()
        llm_tool = base_tool_to_llm_tool(tool)
        assert isinstance(llm_tool, LLMTool)
        assert llm_tool.function.name == "fake_tool"
        assert llm_tool.function.description == "A test tool"
        assert "name" in llm_tool.function.parameters
        assert llm_tool.function.required == ["name"]

    def test_param_type_and_required(self):
        tool = FakeTool()
        llm_tool = base_tool_to_llm_tool(tool)
        name_param = llm_tool.function.parameters["name"]
        assert name_param.type == "string"
        assert name_param.required is True

        count_param = llm_tool.function.parameters["count"]
        assert count_param.type == "integer"
        assert count_param.required is False

    def test_minimal_params(self):
        tool = FakeMinimalTool()
        llm_tool = base_tool_to_llm_tool(tool)
        assert isinstance(llm_tool, LLMTool)
        assert llm_tool.function.parameters == {}


class TestMakeHandler:
    def test_handler_returns_output(self):
        tool = FakeTool()
        handler = make_handler(tool)
        result = handler(name="Alice", count=5)
        assert "Hello Alice" in result

    def test_handler_returns_error_json(self):
        tool = FakeErrorTool()
        handler = make_handler(tool)
        result = handler()
        assert "error" in result
        assert "Something went wrong" in result


class TestBridgeRegistryToExecutor:
    def test_registers_all_tools(self):
        from agentos.tools.registry import ToolRegistry

        registry = ToolRegistry()
        tool = FakeTool()
        registry.register(tool)
        registry.register(FakeMinimalTool())

        executor = MagicMock()
        bridge_registry_to_executor(registry, executor)

        assert executor.register.call_count == 2
