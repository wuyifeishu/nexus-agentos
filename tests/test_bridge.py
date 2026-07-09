"""Tests for agentos.tools.bridge — Bridge between BaseTool and LLM Tool."""

from unittest.mock import MagicMock, patch

import pytest

from agentos.llm.base import Tool as LLMTool
from agentos.tools.base import BaseTool, ToolResult
from agentos.tools.bridge import (
    base_tool_to_llm_tool,
    bridge_registry_to_executor,
    make_handler,
)
from agentos.tools.registry import ToolRegistry


class _SimpleTool(BaseTool):
    name = "simple"
    description = "A simple tool"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "input text", "enum": ["a", "b"]},
                "count": {"type": "integer", "description": "count"},
            },
            "required": ["text"],
        }

    async def execute(self, arguments, sandbox=None):
        return ToolResult.ok(call_id=self.name, output=arguments["text"] * arguments.get("count", 1))


class _NoParamTool(BaseTool):
    name = "noparam"
    description = "No params"

    @property
    def parameters(self) -> dict:
        return {}

    async def execute(self, arguments, sandbox=None):
        return ToolResult.ok(call_id=self.name, output="done")


class _ErrorTool(BaseTool):
    name = "err_tool"
    description = "Always errors"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, arguments, sandbox=None):
        return ToolResult.fail(call_id=self.name, error="boom")


class _NoneOutputTool(BaseTool):
    name = "noneout"
    description = "Output is None"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, arguments, sandbox=None):
        return ToolResult(call_id=self.name, output=None, error=None)


class TestBaseToolToLLMTool:
    """Converter: BaseTool -> LLMTool."""

    def test_simple_conversion(self):
        tool = _SimpleTool()
        llm_tool = base_tool_to_llm_tool(tool)

        assert isinstance(llm_tool, LLMTool)
        assert llm_tool.function.name == "simple"
        assert llm_tool.function.description == "A simple tool"
        assert "text" in llm_tool.function.parameters
        assert "count" in llm_tool.function.parameters

    def test_enum_preserved(self):
        tool = _SimpleTool()
        llm_tool = base_tool_to_llm_tool(tool)

        text_param = llm_tool.function.parameters["text"]
        assert text_param.enum == ["a", "b"]

    def test_required_param(self):
        tool = _SimpleTool()
        llm_tool = base_tool_to_llm_tool(tool)

        text_param = llm_tool.function.parameters["text"]
        assert text_param.required is True

    def test_non_required_param(self):
        tool = _SimpleTool()
        llm_tool = base_tool_to_llm_tool(tool)

        count_param = llm_tool.function.parameters["count"]
        assert count_param.required is False

    def test_empty_params(self):
        tool = _NoParamTool()
        llm_tool = base_tool_to_llm_tool(tool)

        assert llm_tool.function.name == "noparam"
        assert llm_tool.function.parameters == {}
        assert llm_tool.function.required == []

    def test_none_params_default_schema(self):
        class _NoneParamsTool(BaseTool):
            name = "np"
            description = "desc"

            @property
            def parameters(self) -> dict:
                return None

            async def execute(self, arguments, sandbox=None):
                return ToolResult.ok(call_id=self.name, output="ok")

        tool = _NoneParamsTool()
        llm_tool = base_tool_to_llm_tool(tool)
        assert llm_tool.function.name == "np"


class TestMakeHandler:
    """Handler creation for async tool execution."""

    def test_sync_handler_success(self):
        tool = _SimpleTool()
        handler = make_handler(tool)
        result = handler(text="hello", count=2)
        assert result == "hellohello"

    def test_sync_handler_default_count(self):
        tool = _SimpleTool()
        handler = make_handler(tool)
        result = handler(text="x")
        assert result == "x"

    def test_sync_handler_error(self):
        tool = _ErrorTool()
        handler = make_handler(tool)
        result = handler()
        assert "boom" in result
        assert "error" in result

    def test_sync_handler_none_output(self):
        tool = _NoneOutputTool()
        handler = make_handler(tool)
        result = handler()
        assert result == ""

    def test_sync_handler_no_params(self):
        tool = _NoParamTool()
        handler = make_handler(tool)
        result = handler()
        assert result == "done"

    def test_sync_handler_with_extra_kwargs(self):
        tool = _NoParamTool()
        handler = make_handler(tool)
        result = handler(extra="ignored")
        assert result == "done"

    @pytest.mark.asyncio
    async def test_handler_async_context(self):
        """Handler called within an already-running event loop."""
        tool = _SimpleTool()
        handler = make_handler(tool)
        result = handler(text="a", count=3)
        assert result == "aaa"


class TestBridgeRegistryToExecutor:
    """Bridge a full ToolRegistry to an executor."""

    def test_bridge_empty_registry(self):
        reg = ToolRegistry()
        executor = MagicMock()
        bridge_registry_to_executor(reg, executor)
        executor.register.assert_not_called()

    def test_bridge_single_tool(self):
        tool = _SimpleTool()
        reg = ToolRegistry()
        reg.register(tool)
        executor = MagicMock()
        bridge_registry_to_executor(reg, executor)

        assert executor.register.call_count == 1
        args, _ = executor.register.call_args
        llm_tool, handler = args
        assert isinstance(llm_tool, LLMTool)
        assert llm_tool.function.name == "simple"
        assert callable(handler)

    def test_bridge_multiple_tools(self):
        reg = ToolRegistry()
        reg.register(_SimpleTool())
        reg.register(_NoParamTool())
        reg.register(_ErrorTool())

        executor = MagicMock()
        bridge_registry_to_executor(reg, executor)

        assert executor.register.call_count == 3

    def test_bridge_skips_none_tool(self):
        """When registry.get returns None, skip gracefully."""
        reg = ToolRegistry()
        # Use a mock that returns None for get
        with patch.object(reg, "list_names", return_value=["ghost"]):
            with patch.object(reg, "get", return_value=None):
                executor = MagicMock()
                bridge_registry_to_executor(reg, executor)
                executor.register.assert_not_called()

    def test_bridge_tool_registered_with_correct_handler(self):
        tool = _SimpleTool()
        reg = ToolRegistry()
        reg.register(tool)
        executor = MagicMock()
        bridge_registry_to_executor(reg, executor)

        _, handler = executor.register.call_args[0]
        result = handler(text="z", count=2)
        assert result == "zz"

    def test_bridge_tool_handler_errors(self):
        tool = _ErrorTool()
        reg = ToolRegistry()
        reg.register(tool)
        executor = MagicMock()
        bridge_registry_to_executor(reg, executor)

        _, handler = executor.register.call_args[0]
        result = handler()
        assert "boom" in result
