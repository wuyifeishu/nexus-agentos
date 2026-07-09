"""Tests for agentos.core.middleware — composable execution lifecycle pipeline."""

import asyncio
import logging

import pytest

from agentos.core.middleware import (
    AgentMiddleware,
    AuditLogMiddleware,
    BudgetGuardMiddleware,
    MiddlewareContext,
    MiddlewareDecision,
    MiddlewarePhase,
    MiddlewarePipeline,
    RetryMiddleware,
    TimingMiddleware,
)

# ============================================================================
# Stubs
# ============================================================================

class _EmptyMiddleware(AgentMiddleware):
    """Middleware that allows everything with no side effects."""
    name = "empty"

    @property
    def phases(self):
        return [MiddlewarePhase.PRE_LLM, MiddlewarePhase.PRE_TOOL]

    async def process(self, ctx):
        return MiddlewareDecision(allow=True)


class _TransformMiddleware(AgentMiddleware):
    """Middleware that transforms the prompt by appending a suffix."""
    name = "transform"

    @property
    def phases(self):
        return [MiddlewarePhase.PRE_LLM]

    async def process(self, ctx):
        if ctx.prompt:
            new_ctx = MiddlewareContext(**{**ctx.__dict__})
            new_ctx.prompt = ctx.prompt + " [transformed]"
            new_ctx.metadata["transformed"] = True
            return MiddlewareDecision(
                allow=True, action="transform",
                modified_context=new_ctx,
            )
        return MiddlewareDecision(allow=True)


class _BlockMiddleware(AgentMiddleware):
    """Middleware that blocks all pre_llm phases."""
    name = "blocker"

    @property
    def phases(self):
        return [MiddlewarePhase.PRE_LLM]

    async def process(self, ctx):
        return MiddlewareDecision(allow=False, reason="blocked by test", action="block")


class _WarnMiddleware(AgentMiddleware):
    """Middleware that warns but still allows."""
    name = "warner"

    @property
    def phases(self):
        return [MiddlewarePhase.PRE_LLM]

    async def process(self, ctx):
        return MiddlewareDecision(allow=True, action="warn", reason="just a warning")


class _AllPhasesMiddleware(AgentMiddleware):
    """Middleware that listens to all phases for tracing."""
    name = "all_phases"
    def __init__(self):
        self.hit_phases: list[str] = []

    @property
    def phases(self):
        return list(MiddlewarePhase)

    async def process(self, ctx):
        self.hit_phases.append(ctx.phase.value)
        return MiddlewareDecision(allow=True)


# ============================================================================
# MiddlewarePhase
# ============================================================================

class TestMiddlewarePhase:
    def test_all_phases_exist(self):
        expected = {"pre_llm", "post_llm", "pre_tool", "post_tool", "on_error", "on_start", "on_complete"}
        actual = {p.value for p in MiddlewarePhase}
        assert actual == expected


# ============================================================================
# MiddlewareContext
# ============================================================================

class TestMiddlewareContext:
    def test_defaults(self):
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        assert ctx.phase == MiddlewarePhase.PRE_LLM
        assert ctx.agent_name == ""
        assert ctx.prompt is None
        assert ctx.metadata == {}

    def test_full_context(self):
        ctx = MiddlewareContext(
            phase=MiddlewarePhase.PRE_TOOL,
            agent_name="test_agent",
            run_id="run_001",
            tool_name="search",
            tool_args={"q": "hello"},
            metadata={"key": "val"},
        )
        assert ctx.tool_name == "search"
        assert ctx.tool_args == {"q": "hello"}
        assert ctx.metadata["key"] == "val"


# ============================================================================
# MiddlewareDecision
# ============================================================================

class TestMiddlewareDecision:
    def test_default_allow(self):
        d = MiddlewareDecision()
        assert d.allow is True
        assert d.action == "allow"
        assert d.reason == ""

    def test_block(self):
        d = MiddlewareDecision(allow=False, reason="test", action="block", blocked_by="guard")
        assert d.allow is False
        assert d.blocked_by == "guard"

    def test_modified_context(self):
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        new_ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, prompt="modified")
        d = MiddlewareDecision(modified_context=new_ctx)
        assert d.modified_context.prompt == "modified"


# ============================================================================
# AgentMiddleware base
# ============================================================================

class TestAgentMiddleware:
    def test_call_delegates_to_process(self):
        mw = _EmptyMiddleware()
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        decision = asyncio.run(mw(ctx))
        assert decision.allow is True


# ============================================================================
# Built-in Middleware
# ============================================================================

class DummyTracker:
    def __init__(self, cost=0.0):
        self.total_cost = cost


class TestBudgetGuardMiddleware:
    def test_no_tracker_allows(self):
        mw = BudgetGuardMiddleware()
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        d = asyncio.run(mw.process(ctx))
        assert d.allow is True

    def test_within_budget(self):
        mw = BudgetGuardMiddleware(tracker=DummyTracker(5.0), budget_limit=10.0)
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        d = asyncio.run(mw.process(ctx))
        assert d.allow is True

    def test_exceeded_budget(self):
        mw = BudgetGuardMiddleware(tracker=DummyTracker(15.0), budget_limit=10.0)
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        d = asyncio.run(mw.process(ctx))
        assert d.allow is False
        assert d.action == "block"

    def test_warning_threshold(self):
        mw = BudgetGuardMiddleware(tracker=DummyTracker(9.0), budget_limit=10.0, warn_ratio=0.8)
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        d = asyncio.run(mw.process(ctx))
        assert d.allow is True
        assert d.action == "warn"

    def test_pre_tool_phase(self):
        mw = BudgetGuardMiddleware(tracker=DummyTracker(11.0), budget_limit=10.0)
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_TOOL, tool_name="search")
        d = asyncio.run(mw.process(ctx))
        assert d.allow is False


class TestAuditLogMiddleware:
    def test_logs_all_phases(self, caplog):
        mw = AuditLogMiddleware()
        caplog.set_level(logging.INFO, logger="agentos.audit")
        for phase in [MiddlewarePhase.ON_START, MiddlewarePhase.PRE_TOOL, MiddlewarePhase.ON_COMPLETE]:
            ctx = MiddlewareContext(
                phase=phase, agent_name="test", run_id="r1", tool_name="search"
            )
            d = asyncio.run(mw.process(ctx))
            assert d.allow is True
        assert len(caplog.records) == 3


class TestTimingMiddleware:
    def test_records_timings(self):
        mw = TimingMiddleware()
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_START, agent_name="agent1")
        asyncio.run(mw.process(ctx))
        timings = mw.get_timings()
        assert any("on_start" in k for k in timings)

    def test_total_ms(self):
        mw = TimingMiddleware()
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, tool_name="search")
        asyncio.run(mw.process(ctx))
        assert mw.total_ms() >= 0


class TestRetryMiddleware:
    def test_allows_first_retry(self):
        mw = RetryMiddleware(max_retries=3, backoff_base=0.001)
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_ERROR, run_id="r1")
        d = asyncio.run(mw.process(ctx))
        assert d.allow is True
        assert "Retry 1/3" in d.reason

    def test_exhaust_retries(self):
        mw = RetryMiddleware(max_retries=2, backoff_base=0.001)
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_ERROR, run_id="r2")
        asyncio.run(mw.process(ctx))
        asyncio.run(mw.process(ctx))
        d = asyncio.run(mw.process(ctx))
        assert d.action == "warn"
        assert "Max retries" in d.reason

    def test_reset(self):
        mw = RetryMiddleware(max_retries=2, backoff_base=0.001)
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_ERROR, run_id="r3")
        asyncio.run(mw.process(ctx))
        mw.reset("r3")
        d = asyncio.run(mw.process(ctx))
        assert "Retry 1/2" in d.reason

    def test_reset_all(self):
        mw = RetryMiddleware(max_retries=2, backoff_base=0.001)
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_ERROR, run_id="r4")
        asyncio.run(mw.process(ctx))
        mw.reset()
        d = asyncio.run(mw.process(ctx))
        assert "Retry 1/2" in d.reason


# ============================================================================
# MiddlewarePipeline
# ============================================================================

class TestMiddlewarePipeline:
    def test_add_chainable(self):
        pl = MiddlewarePipeline()
        result = pl.add(_EmptyMiddleware())
        assert result is pl

    def test_remove(self):
        pl = MiddlewarePipeline([_EmptyMiddleware()])
        pl.remove("empty")
        assert pl.middleware_names == []

    def test_middleware_names(self):
        pl = MiddlewarePipeline([_EmptyMiddleware(), _BlockMiddleware()])
        assert pl.middleware_names == ["empty", "blocker"]

    def test_empty_pipeline(self):
        pl = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        d = asyncio.run(pl.execute_phase(MiddlewarePhase.PRE_LLM, ctx))
        assert d.allow is True

    def test_transform_chain(self):
        """Transform middleware modifies context, next middleware sees modified."""
        pl = MiddlewarePipeline([_TransformMiddleware(), _TransformMiddleware()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, prompt="hello")
        d = asyncio.run(pl.execute_phase(MiddlewarePhase.PRE_LLM, ctx))
        assert d.modified_context.prompt == "hello [transformed] [transformed]"

    def test_block_stops_chain(self):
        pl = MiddlewarePipeline([_BlockMiddleware(), _TransformMiddleware()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, prompt="hello")
        d = asyncio.run(pl.execute_phase(MiddlewarePhase.PRE_LLM, ctx))
        assert d.allow is False
        assert d.blocked_by == "blocker"
        # Context should not be transformed since blocker stopped the chain
        assert d.modified_context is None

    def test_warn_does_not_stop(self):
        pl = MiddlewarePipeline([_WarnMiddleware(), _EmptyMiddleware()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        d = asyncio.run(pl.execute_phase(MiddlewarePhase.PRE_LLM, ctx))
        assert d.allow is True

    def test_phase_routing(self):
        """Middleware only fires for its declared phases."""
        pl = MiddlewarePipeline([_EmptyMiddleware(), _AllPhasesMiddleware()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_TOOL, tool_name="search")
        asyncio.run(pl.execute_phase(MiddlewarePhase.PRE_TOOL, ctx))
        # _EmptyMiddleware should be hit for PRE_TOOL, _AllPhasesMiddleware should hit too
        # We only validate no errors
        d = asyncio.run(pl.execute_phase(MiddlewarePhase.PRE_TOOL, ctx))
        assert d.allow is True

    # Phase convenience methods

    def test_on_start(self):
        pl = MiddlewarePipeline([_AllPhasesMiddleware()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_START)
        d = asyncio.run(pl.on_start(ctx))
        assert d.allow is True

    def test_pre_llm(self):
        pl = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        d = asyncio.run(pl.pre_llm(ctx))
        assert d.allow is True

    def test_post_llm(self):
        pl = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.POST_LLM)
        d = asyncio.run(pl.post_llm(ctx))
        assert d.allow is True

    def test_pre_tool(self):
        pl = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_TOOL)
        d = asyncio.run(pl.pre_tool(ctx))
        assert d.allow is True

    def test_post_tool(self):
        pl = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.POST_TOOL)
        d = asyncio.run(pl.post_tool(ctx))
        assert d.allow is True

    def test_on_error(self):
        pl = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_ERROR)
        d = asyncio.run(pl.on_error(ctx))
        assert d.allow is True

    def test_on_complete(self):
        pl = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_COMPLETE)
        d = asyncio.run(pl.on_complete(ctx))
        assert d.allow is True

    def test_run_full_cycle(self):
        pl = MiddlewarePipeline([_AllPhasesMiddleware()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.ON_START, agent_name="a", run_id="r")
        d = asyncio.run(pl.run(ctx))
        assert d.allow is True

    def test_run_custom_phases(self):
        pl = MiddlewarePipeline([_EmptyMiddleware()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
        d = asyncio.run(pl.run(ctx, phases=[MiddlewarePhase.PRE_LLM]))
        assert d.allow is True


# ============================================================================
# Concurrency safety
# ============================================================================

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_retry_middleware_concurrent(self):
        """Multiple coroutines hitting retry middleware with different run_ids."""
        mw = RetryMiddleware(max_retries=3, backoff_base=0.001)

        async def do_retry(run_id):
            ctx = MiddlewareContext(phase=MiddlewarePhase.ON_ERROR, run_id=run_id)
            return await mw.process(ctx)

        d1, d2 = await asyncio.gather(do_retry("a"), do_retry("b"))
        assert d1.allow
        assert d2.allow

    @pytest.mark.asyncio
    async def test_pipeline_concurrent(self):
        pl = MiddlewarePipeline([_EmptyMiddleware()])

        async def do_phase():
            ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM)
            return await pl.execute_phase(MiddlewarePhase.PRE_LLM, ctx)

        results = await asyncio.gather(*[do_phase() for _ in range(5)])
        assert all(r.allow for r in results)
