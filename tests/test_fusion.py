"""Tests for agentos.tools.fusion."""

import pytest

from agentos.tools.fusion import (
    FusionMode,
    FusionResult,
    FusionToolkit,
    ToolResult,
    ToolSpec,
)


def add_func(a, b, **kwargs):
    return a + b


def mul_func(a, b, **kwargs):
    return a * b


def fail_func(**kwargs):
    raise RuntimeError("fail")


class TestFusionMode:
    def test_values(self):
        assert FusionMode.SEQUENTIAL == "sequential"
        assert FusionMode.PARALLEL == "parallel"
        assert FusionMode.CHAIN == "chain"


class TestToolSpec:
    def test_create(self):
        spec = ToolSpec(name="add", func=add_func)
        assert spec.name == "add"
        assert spec.timeout == 30.0
        assert spec.retry_count == 0

    def test_with_description(self):
        spec = ToolSpec(name="add", description="Add numbers", func=add_func, timeout=10.0, retry_count=3)
        assert spec.description == "Add numbers"
        assert spec.timeout == 10.0
        assert spec.retry_count == 3

    def test_to_dict(self):
        spec = ToolSpec(name="add", func=add_func)
        d = spec.to_dict()
        assert d["name"] == "add"
        assert d["timeout"] == 30.0


class TestFusionToolResult:
    def test_success_result(self):
        r = ToolResult(tool_name="add", success=True, output=42, duration=0.5)
        assert r.tool_name == "add"
        assert r.success is True
        assert r.output == 42

    def test_fail_result(self):
        r = ToolResult(tool_name="add", success=False, error="boom", duration=0.1)
        assert r.success is False
        assert r.error == "boom"


class TestFusionResult:
    def test_defaults(self):
        r = FusionResult()
        assert r.mode == FusionMode.SEQUENTIAL
        assert r.results == []
        assert r.success is True

    def test_with_results(self):
        r = FusionResult(
            mode=FusionMode.PARALLEL,
            results=[ToolResult(tool_name="a", success=True, output=1)],
            fused_output=1,
            total_duration=0.5,
            success=True,
        )
        assert r.mode == FusionMode.PARALLEL
        assert len(r.results) == 1
        assert r.fused_output == 1

    def test_to_dict(self):
        r = FusionResult(results=[ToolResult(tool_name="a", success=True, output=1)])
        d = r.to_dict()
        assert d["mode"] == "sequential"
        assert len(d["results"]) == 1


class TestFusionToolkit:
    def test_create_defaults(self):
        ft = FusionToolkit()
        tools = ft.list_tools()
        assert isinstance(tools, list)

    def test_register_and_get(self):
        ft = FusionToolkit()
        spec = ToolSpec(name="add", func=add_func)
        ft.register(spec)
        assert ft.get_tool("add") is spec

    def test_register_duplicate(self):
        ft = FusionToolkit()
        ft.register(ToolSpec(name="add", func=add_func))
        ft.register(ToolSpec(name="add", func=mul_func))
        assert ft.get_tool("add").func is mul_func

    def test_unregister(self):
        ft = FusionToolkit()
        ft.register(ToolSpec(name="add", func=add_func))
        assert ft.unregister("add") is True
        assert ft.unregister("nonexistent") is False

    def test_get_tool_missing(self):
        ft = FusionToolkit()
        assert ft.get_tool("nope") is None

    def test_list_tools(self):
        ft = FusionToolkit()
        ft.register(ToolSpec(name="a", func=add_func))
        ft.register(ToolSpec(name="b", func=mul_func))
        names = [t.name for t in ft.list_tools()]
        assert "a" in names
        assert "b" in names

    @pytest.mark.asyncio
    async def test_execute_sequential_success(self):
        ft = FusionToolkit()
        ft.register(ToolSpec(name="add", func=add_func))
        ft.register(ToolSpec(name="mul", func=mul_func))
        result = await ft.execute(
            tool_names=["add", "mul"],
            inputs={"a": 10, "b": 20},
            mode=FusionMode.SEQUENTIAL,
        )
        assert isinstance(result, FusionResult)
        assert len(result.results) == 2
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_parallel(self):
        ft = FusionToolkit()
        ft.register(ToolSpec(name="add", func=add_func))
        ft.register(ToolSpec(name="mul", func=mul_func))
        result = await ft.execute(
            tool_names=["add", "mul"],
            inputs={"a": 1, "b": 2},
            mode=FusionMode.PARALLEL,
        )
        assert isinstance(result, FusionResult)
        assert len(result.results) == 2

    @pytest.mark.asyncio
    async def test_execute_chain(self):
        ft = FusionToolkit()
        ft.register(ToolSpec(name="add", func=add_func))
        ft.register(ToolSpec(name="mul", func=mul_func))
        result = await ft.execute(
            tool_names=["add", "mul"],
            inputs={"a": 10, "b": 5},
            mode=FusionMode.CHAIN,
        )
        assert isinstance(result, FusionResult)

    @pytest.mark.asyncio
    async def test_execute_missing_tool(self):
        ft = FusionToolkit()
        result = await ft.execute(
            tool_names=["nonexistent"],
            inputs={},
            mode=FusionMode.SEQUENTIAL,
        )
        assert isinstance(result, FusionResult)
        assert len(result.results) == 1
        assert result.results[0].success is False

    @pytest.mark.asyncio
    async def test_execute_default_mode(self):
        ft = FusionToolkit()
        ft.register(ToolSpec(name="add", func=add_func))
        result = await ft.execute(tool_names=["add"], inputs={"a": 1, "b": 2})
        assert isinstance(result, FusionResult)
        assert result.mode == FusionMode.SEQUENTIAL
