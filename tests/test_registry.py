"""Tests for agentos.tools.registry — ToolRegistry."""

from agentos.tools.base import BaseTool, ToolCall, ToolResult
from agentos.tools.registry import ToolRegistry


class DummyTool(BaseTool):
    name = "dummy"
    description = "A dummy tool"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        return ToolResult.ok("dummy_call", output=f"done: {arguments.get('x')}")


class FailingTool(BaseTool):
    name = "failer"
    description = "Always fails"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        raise RuntimeError("boom")


class TestToolRegistry:
    def test_init_empty(self):
        r = ToolRegistry()
        assert r.list_names() == []

    def test_register_single(self):
        r = ToolRegistry()
        r.register(DummyTool())
        assert r.list_names() == ["dummy"]

    def test_register_many(self):
        r = ToolRegistry()
        r.register_many([DummyTool(), FailingTool()])
        names = r.list_names()
        assert "dummy" in names
        assert "failer" in names
        assert len(names) == 2

    def test_register_overwrites(self):
        r = ToolRegistry()
        r.register(DummyTool())

        class Dummy2(DummyTool):
            pass

        r.register(Dummy2())
        assert isinstance(r.get("dummy"), Dummy2)

    def test_get_existing(self):
        r = ToolRegistry()
        d = DummyTool()
        r.register(d)
        assert r.get("dummy") is d

    def test_get_missing(self):
        r = ToolRegistry()
        assert r.get("ghost") is None

    def test_get_schemas_openai(self):
        r = ToolRegistry()
        r.register(DummyTool())
        schemas = r.get_schemas_for_model("openai")
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"

    def test_get_schemas_anthropic(self):
        r = ToolRegistry()
        r.register(DummyTool())
        schemas = r.get_schemas_for_model("anthropic")
        assert len(schemas) == 1
        assert "name" in schemas[0]
        assert "input_schema" in schemas[0]

    def test_get_schemas_fallback(self):
        r = ToolRegistry()
        r.register(DummyTool())
        schemas = r.get_schemas_for_model("unknown_model")
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"

    def test_get_schemas_deepseek(self):
        r = ToolRegistry()
        r.register(DummyTool())
        schemas = r.get_schemas_for_model("deepseek")
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"

    def test_make_call_id(self):
        cid = ToolRegistry.make_call_id()
        assert cid.startswith("call_")
        assert len(cid) > 5

    async def test_execute_batch_success(self):
        r = ToolRegistry()
        r.register(DummyTool())
        calls = [
            ToolCall(id="c1", name="dummy", arguments={"x": "a"}),
            ToolCall(id="c2", name="dummy", arguments={"x": "b"}),
        ]
        results = await r.execute_batch(calls)
        assert len(results) == 2
        assert "done: a" == results[0].output
        assert "done: b" == results[1].output

    async def test_execute_batch_unknown_tool(self):
        r = ToolRegistry()
        calls = [ToolCall(id="c1", name="ghost", arguments={})]
        results = await r.execute_batch(calls)
        assert len(results) == 1
        assert results[0].error is not None
        assert "Unknown tool" in results[0].error

    async def test_execute_batch_mixed(self):
        r = ToolRegistry()
        r.register(DummyTool())
        calls = [
            ToolCall(id="c1", name="dummy", arguments={"x": "ok"}),
            ToolCall(id="c2", name="ghost", arguments={}),
        ]
        results = await r.execute_batch(calls)
        assert results[0].output == "done: ok"
        assert "Unknown tool" in results[1].error

    async def test_execute_one_tool_error(self):
        r = ToolRegistry()
        r.register(FailingTool())
        calls = [ToolCall(id="c1", name="failer", arguments={})]
        results = await r.execute_batch(calls)
        assert results[0].error is not None
