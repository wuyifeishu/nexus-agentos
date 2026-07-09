"""Tests for agentos.tools.skill_tool — marketplace skill wrapping."""

import pytest

from agentos.tools.skill_tool import (
    SkillTool,
    _infer_parameters,
)

# ============================================================================
# _infer_parameters
# ============================================================================

class TestInferParameters:
    def test_no_params(self):
        def fn():
            return "ok"

        schema = _infer_parameters(fn)
        assert schema["type"] == "object"
        assert schema["properties"] == {}

    def test_typed_params(self):
        def fn(query: str, limit: int = 10, active: bool = True):
            pass

        schema = _infer_parameters(fn)
        props = schema["properties"]
        assert props["query"]["type"] == "string"
        assert props["limit"]["type"] == "integer"
        assert props["active"]["type"] == "boolean"
        assert "query" in schema["required"]
        assert "limit" not in schema["required"]

    def test_skip_self(self):
        class Foo:
            def method(self, x: str):
                pass

        schema = _infer_parameters(Foo().method)
        assert "self" not in schema["properties"]

    def test_float_param(self):
        def fn(ratio: float):
            pass

        schema = _infer_parameters(fn)
        assert schema["properties"]["ratio"]["type"] == "number"


# ============================================================================
# SkillTool
# ============================================================================

class TestSkillTool:
    def test_name_and_description(self):
        def my_run():
            return "done"

        tool = SkillTool("my_skill", my_run, description="My skill desc")
        assert tool.name == "my_skill"
        assert tool.description == "My skill desc"

    def test_default_description(self):
        def my_run():
            return "ok"

        tool = SkillTool("foo", my_run)
        assert "foo" in tool.description

    def test_default_parameters(self):
        def my_run():
            return "ok"

        tool = SkillTool("bar", my_run)
        assert "kwargs" in tool.parameters["properties"]

    def test_custom_parameters(self):
        def my_run():
            return "ok"

        custom_params = {"type": "object", "properties": {}}
        tool = SkillTool("baz", my_run, parameters=custom_params)
        assert tool.parameters == custom_params

    @pytest.mark.asyncio
    async def test_execute_no_args(self):
        def my_run():
            return "hello"

        tool = SkillTool("echo", my_run)
        result = await tool.execute({})
        assert result.output == "hello"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_execute_with_kwargs(self):
        def my_run(greeting: str, name: str = "World"):
            return f"{greeting}, {name}"

        tool = SkillTool("greet", my_run)
        import json
        result = await tool.execute({"kwargs": json.dumps({"greeting": "Hi", "name": "Bob"})})
        assert result.output == "Hi, Bob"

    @pytest.mark.asyncio
    async def test_execute_error(self):
        def my_run():
            raise ValueError("boom")

        tool = SkillTool("bad", my_run)
        result = await tool.execute({})
        assert result.error is not None
        assert "boom" in result.error
