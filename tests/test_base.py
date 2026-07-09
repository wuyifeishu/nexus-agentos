"""Tests for agentos.tools.base — Tool base classes."""

import pytest

from agentos.tools.base import BaseTool, PermissionLevel, ToolCall, ToolResult


class TestPermissionLevel:
    """PermissionLevel enum tests."""

    def test_values(self):
        assert PermissionLevel.SAFE.value == "safe"
        assert PermissionLevel.MODERATE.value == "moderate"
        assert PermissionLevel.SENSITIVE.value == "sensitive"

    def test_unique(self):
        vals = [e.value for e in PermissionLevel]
        assert len(vals) == len(set(vals))

    def test_from_string(self):
        assert PermissionLevel("safe") == PermissionLevel.SAFE
        assert PermissionLevel("moderate") == PermissionLevel.MODERATE
        assert PermissionLevel("sensitive") == PermissionLevel.SENSITIVE

    def test_invalid_level(self):
        with pytest.raises(ValueError):
            PermissionLevel("admin")


class TestToolCall:
    """ToolCall dataclass tests."""

    def test_construction(self):
        tc = ToolCall(id="call_1", name="my_tool", arguments={"x": 1})
        assert tc.id == "call_1"
        assert tc.name == "my_tool"
        assert tc.arguments == {"x": 1}

    def test_arguments_empty(self):
        tc = ToolCall(id="c", name="t", arguments={})
        assert tc.arguments == {}

    def test_default_factories(self):
        tc = ToolCall(id="c", name="t", arguments={})
        assert isinstance(tc.id, str)
        assert isinstance(tc.name, str)
        assert isinstance(tc.arguments, dict)


class TestToolResult:
    """ToolResult dataclass tests."""

    def test_construction_all_fields(self):
        tr = ToolResult(
            call_id="call_1", output="done", error=None, exit_code=0
        )
        assert tr.call_id == "call_1"
        assert tr.output == "done"
        assert tr.error is None
        assert tr.exit_code == 0

    def test_construction_minimal(self):
        tr = ToolResult(call_id="call_1")
        assert tr.call_id == "call_1"
        assert tr.output is None
        assert tr.error is None
        assert tr.exit_code is None

    def test_ok_factory(self):
        tr = ToolResult.ok(call_id="call_2", output="success")
        assert tr.call_id == "call_2"
        assert tr.output == "success"
        assert tr.error is None

    def test_fail_factory(self):
        tr = ToolResult.fail(call_id="call_3", error="timeout")
        assert tr.call_id == "call_3"
        assert tr.error == "timeout"
        assert tr.output is None


class _ConcreteTool(BaseTool):
    """Minimal concrete tool for testing BaseTool."""

    name = "concrete_tool"
    description = "A test tool"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "param x"},
            },
            "required": ["x"],
        }

    async def execute(self, arguments, sandbox=None):
        return ToolResult.ok(call_id=self.name, output=str(arguments.get("x", 0) * 2))


class _ReadOnlyTool(BaseTool):
    """A read-only tool for testing is_write/is_read defaults."""

    name = "reader"
    description = "Reads"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, arguments, sandbox=None):
        return ToolResult.ok(call_id=self.name, output="read")


class _WriteTool(BaseTool):
    """A write tool — overrides is_write_operation."""

    name = "writer"
    description = "Writes"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, arguments, sandbox=None):
        return ToolResult.ok(call_id=self.name, output="written")

    def is_write_operation(self, arguments):
        return True

    def is_read_operation(self, arguments):
        return False


class _PathTool(BaseTool):
    """A tool that overrides extract_target_path."""

    name = "path_tool"
    description = "Path tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, arguments, sandbox=None):
        return ToolResult.ok(call_id=self.name, output="ok")


class TestBaseTool:
    """BaseTool abstract class tests."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseTool()

    def test_name_property(self):
        tool = _ConcreteTool()
        assert tool.name == "concrete_tool"

    def test_description_property(self):
        tool = _ConcreteTool()
        assert tool.description == "A test tool"

    def test_permission_level_default(self):
        tool = _ConcreteTool()
        assert tool.permission_level == PermissionLevel.MODERATE

    def test_concurrent_safe_default(self):
        tool = _ConcreteTool()
        assert tool.concurrent_safe is True

    def test_to_openai_schema(self):
        tool = _ConcreteTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "concrete_tool"
        assert schema["function"]["description"] == "A test tool"
        assert schema["function"]["parameters"]["required"] == ["x"]

    def test_to_anthropic_schema(self):
        tool = _ConcreteTool()
        schema = tool.to_anthropic_schema()
        assert schema["name"] == "concrete_tool"
        assert schema["description"] == "A test tool"
        assert schema["input_schema"]["required"] == ["x"]

    def test_is_write_operation_default_false(self):
        tool = _ReadOnlyTool()
        assert tool.is_write_operation({"file_path": "/tmp/x"}) is False

    def test_is_write_operation_true(self):
        tool = _WriteTool()
        assert tool.is_write_operation({"file_path": "/tmp/x"}) is True

    def test_is_read_operation_default_true(self):
        tool = _ReadOnlyTool()
        assert tool.is_read_operation({}) is True

    def test_is_read_operation_false(self):
        tool = _WriteTool()
        assert tool.is_read_operation({}) is False

    def test_extract_target_path_file_path(self):
        tool = _PathTool()
        path = tool.extract_target_path({"file_path": "/tmp/x.txt"})
        assert path == "/tmp/x.txt"

    def test_extract_target_path_short_path(self):
        tool = _PathTool()
        path = tool.extract_target_path({"path": "/etc/hosts"})
        assert path == "/etc/hosts"

    def test_extract_target_path_none(self):
        tool = _PathTool()
        path = tool.extract_target_path({"other": "val"})
        assert path is None

    def test_extract_target_path_empty(self):
        tool = _PathTool()
        path = tool.extract_target_path({})
        assert path is None

    @pytest.mark.asyncio
    async def test_execute(self):
        tool = _ConcreteTool()
        result = await tool.execute({"x": 5})
        assert result.output == "10"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_with_sandbox(self):
        tool = _ConcreteTool()
        sandbox_mock = object()
        result = await tool.execute({"x": 3}, sandbox=sandbox_mock)
        assert result.output == "6"
