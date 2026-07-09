"""Tests for agentos.core.di — Dependency Injection system."""

import pytest

from agentos.core.di import (
    Agent,
    Depends,
    RunContext,
    inject_tool,
    requires_context,
)

# ============================================================================
# RunContext
# ============================================================================

class TestRunContext:
    def test_defaults_str_deps(self):
        ctx = RunContext[str](deps="hello", agent_name="test")
        assert ctx.deps == "hello"
        assert ctx.agent_name == "test"
        assert len(ctx.run_id) == 12
        assert ctx.metadata == {}

    def test_custom_metadata(self):
        ctx = RunContext[int](deps=42, metadata={"key": "val"})
        assert ctx.get("key") == "val"
        assert ctx.get("missing", "default") == "default"

    def test_set_metadata(self):
        ctx = RunContext[int](deps=10)
        ctx.set("user_id", "u123")
        assert ctx.metadata["user_id"] == "u123"


# ============================================================================
# Depends
# ============================================================================

class TestDepends:
    def test_resolve_calls_callable(self):
        d = Depends(lambda: "resolved")
        assert d.resolve() == "resolved"

    def test_resolve_with_state(self):
        counter = []
        d = Depends(lambda: counter.append(1) or counter)
        result = d.resolve()
        assert len(result) == 1


# ============================================================================
# inject_tool
# ============================================================================

class TestInjectTool:
    def test_injects_tool(self):
        def tool_a():
            return "a"

        @inject_tool(tool_a)
        class MyAgent(Agent[None, str]):
            async def run(self, ctx):
                return "done"

        agent = MyAgent()
        tools = agent.get_tools()
        assert tool_a in tools

    def test_inject_multiple(self):
        def t1(): pass
        def t2(): pass

        @inject_tool(t1)
        @inject_tool(t2)
        class MultiToolAgent(Agent[None, str]):
            async def run(self, ctx):
                return "ok"

        agent = MultiToolAgent()
        assert len(agent.get_tools()) == 2


# ============================================================================
# requires_context
# ============================================================================

class TestRequiresContext:
    def test_single_required_field_ok(self):
        @requires_context("user_id")
        class CtxAgent(Agent[str, str]):
            async def run(self, ctx):
                return ctx.deps

        agent = CtxAgent()
        import asyncio
        result = asyncio.run(agent.invoke("hello", user_id="u1"))
        assert result == "hello"

    def test_missing_required_field_raises(self):
        @requires_context("session_id")
        class CtxAgent(Agent[str, str]):
            async def run(self, ctx):
                return ctx.deps

        agent = CtxAgent()
        import asyncio
        with pytest.raises(ValueError, match="session_id"):
            asyncio.run(agent.invoke("data"))

    def test_multiple_required_fields(self):
        @requires_context("a", "b", "c")
        class CtxAgent(Agent[str, str]):
            async def run(self, ctx):
                return ctx.deps

        agent = CtxAgent()
        import asyncio
        result = asyncio.run(agent.invoke("x", a=1, b=2, c=3))
        assert result == "x"


# ============================================================================
# Agent base class
# ============================================================================

class _SimpleAgent(Agent[str, str]):
    async def run(self, ctx: RunContext[str]) -> str:
        return f"Hello, {ctx.deps}"


class TestAgent:
    def test_invoke_str(self):
        agent = _SimpleAgent()
        import asyncio
        result = asyncio.run(agent.invoke("World"))
        assert result == "Hello, World"

    def test_invoke_with_depends(self):
        agent = _SimpleAgent()
        import asyncio
        d = Depends(lambda: "Bob")
        result = asyncio.run(agent.invoke(d))
        assert result == "Hello, Bob"

    def test_default_name(self):
        agent = _SimpleAgent()
        assert agent.name == "_SimpleAgent"

    def test_custom_name(self):
        agent = _SimpleAgent(name="custom")
        assert agent.name == "custom"

    def test_repr(self):
        agent = _SimpleAgent(name="greeter")
        assert repr(agent) == "_SimpleAgent(name='greeter')"

    def test_get_tools_empty_by_default(self):
        agent = _SimpleAgent()
        assert agent.get_tools() == []

    def test_run_not_implemented_by_default(self):
        """Agent.run() raises NotImplementedError if not overridden."""
        agent = Agent[str, str]()
        import asyncio
        ctx = RunContext[str](deps="test")
        with pytest.raises(NotImplementedError):
            asyncio.run(agent.run(ctx))


# ============================================================================
# Agent with complex Deps types
# ============================================================================

class ComplexDeps:
    def __init__(self, db="mock_db", cache="mock_cache"):
        self.db = db
        self.cache = cache


class ComplexAgent(Agent[ComplexDeps, str]):
    async def run(self, ctx: RunContext[ComplexDeps]) -> str:
        return f"{ctx.deps.db}/{ctx.deps.cache}"


class TestComplexAgent:
    def test_invoke_with_dataclass_deps(self):
        agent = ComplexAgent()
        import asyncio
        deps = ComplexDeps(db="pg", cache="redis")
        result = asyncio.run(agent.invoke(deps))
        assert result == "pg/redis"


# ============================================================================
# Agent with int Deps/Out
# ============================================================================

class IntAgent(Agent[int, int]):
    async def run(self, ctx: RunContext[int]) -> int:
        return ctx.deps * 2


class TestIntAgent:
    def test_int_types(self):
        agent = IntAgent()
        import asyncio
        result = asyncio.run(agent.invoke(5))
        assert result == 10
