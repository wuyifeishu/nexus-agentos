"""Test AsyncAgentLoop — concurrent agent execution with semaphore, timeout, retry, metrics."""

from __future__ import annotations

import asyncio

import pytest

from agentos.core.async_loop import (
    AsyncAgentLoop,
    AsyncInvocationResult,
    AsyncLoopConfig,
)
from agentos.core.context import AgentContext

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def loop_cfg():
    return AsyncLoopConfig(
        max_concurrency=2,
        timeout_seconds=1.0,
        max_retries=1,
        retry_on_timeout=True,
    )


@pytest.fixture
def loop(loop_cfg):
    return AsyncAgentLoop(config=loop_cfg)


# ============================================================================
# AsyncLoopConfig
# ============================================================================

class TestAsyncLoopConfig:
    def test_defaults(self):
        c = AsyncLoopConfig()
        assert c.max_concurrency == 10
        assert c.timeout_seconds == 300.0
        assert c.max_retries == 3
        assert c.retry_on_timeout is True
        assert c.collect_metrics is True

    def test_custom(self):
        c = AsyncLoopConfig(max_concurrency=5, timeout_seconds=60.0, max_retries=2)
        assert c.max_concurrency == 5
        assert c.timeout_seconds == 60.0

    def test_no_retry_no_timeout(self):
        c = AsyncLoopConfig(retry_on_timeout=False, max_retries=0)
        assert c.retry_on_timeout is False
        assert c.max_retries == 0


# ============================================================================
# AsyncInvocationResult
# ============================================================================

class TestAsyncInvocationResult:
    def test_success_result(self):
        r = AsyncInvocationResult(agent_id="a", success=True, output="ok", latency_ms=10.5, retries=0)
        assert r.success is True
        assert r.output == "ok"
        assert r.latency_ms == 10.5

    def test_failure_result(self):
        r = AsyncInvocationResult(agent_id="a", success=False, error="timeout", latency_ms=1000.0, retries=3)
        assert r.success is False
        assert r.error == "timeout"
        assert r.retries == 3


# ============================================================================
# AgentContext
# ============================================================================

class TestAgentContext:
    def test_create_empty(self):
        ctx = AgentContext(messages=[])
        assert ctx.messages == []

    def test_create_with_tools(self):
        ctx = AgentContext(messages=[], tools=[{"name": "search"}])
        assert ctx.tools == [{"name": "search"}]

    def test_model_type_default(self):
        ctx = AgentContext(messages=[])
        assert ctx.model_type == "openai"


# ============================================================================
# AsyncAgentLoop — run_single
# ============================================================================

class TestRunSingle:
    @pytest.mark.asyncio
    async def test_successful_invocation(self, loop):
        async def fast_task(x: int) -> str:
            return f"result-{x}"

        result = await loop.run_single("agent-1", fast_task, 42)
        assert result.success is True
        assert result.output == "result-42"
        assert result.agent_id == "agent-1"
        assert result.retries == 0
        assert result.latency_ms >= 0
        assert result.error is None

    @pytest.mark.asyncio
    async def test_with_kwargs(self, loop):
        async def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}!"

        result = await loop.run_single("a1", greet, "World", greeting="Hi")
        assert result.success is True
        assert "Hi, World" in str(result.output)

    @pytest.mark.asyncio
    async def test_erroneous_task(self, loop):
        async def failing():
            raise ValueError("boom")

        result = await loop.run_single("agent-e", failing)
        assert result.success is False
        assert "ValueError" in (result.error or "")
        assert result.retries == loop.config.max_retries

    @pytest.mark.asyncio
    async def test_no_retry_when_disabled(self):
        cfg = AsyncLoopConfig(max_retries=0, timeout_seconds=1.0)
        loop = AsyncAgentLoop(config=cfg)

        async def always_fail():
            raise RuntimeError("no")

        result = await loop.run_single("a", always_fail)
        assert result.success is False
        assert result.retries == 0

    @pytest.mark.asyncio
    async def test_timeout(self):
        cfg = AsyncLoopConfig(max_retries=0, timeout_seconds=0.01, retry_on_timeout=False)
        loop = AsyncAgentLoop(config=cfg)

        async def slow():
            await asyncio.sleep(10)
            return "done"

        result = await loop.run_single("a", slow)
        assert result.success is False
        assert "Timeout" in (result.error or "")

    @pytest.mark.asyncio
    async def test_retry_fails_and_exhausts(self):
        cfg = AsyncLoopConfig(max_retries=2, timeout_seconds=1.0)
        loop = AsyncAgentLoop(config=cfg)

        async def always_crash():
            raise RuntimeError("persistent")

        result = await loop.run_single("a", always_crash)
        assert result.success is False
        assert result.retries == 2


# ============================================================================
# AsyncAgentLoop — run_all
# ============================================================================

class TestRunAll:
    @pytest.mark.asyncio
    async def test_empty(self, loop):
        results = await loop.run_all([])
        assert results == []

    @pytest.mark.asyncio
    async def test_single(self, loop):
        async def t():
            return "only"

        results = await loop.run_all([("id1", t, (), {})])
        assert len(results) == 1
        assert results[0].output == "only"

    @pytest.mark.asyncio
    async def test_multiple(self, loop):
        async def t(x):
            return x * 2

        tasks = [
            ("a", t, (1,), {}),
            ("b", t, (2,), {}),
            ("c", t, (3,), {}),
        ]
        results = await loop.run_all(tasks)
        assert len(results) == 3
        outputs = [r.output for r in results]
        assert outputs == [2, 4, 6]

    @pytest.mark.asyncio
    async def test_mixed_success_failure(self, loop):
        call_count = 0

        async def maybe_fail(n):
            nonlocal call_count
            call_count += 1
            if n == 2:
                raise RuntimeError("fail")
            return f"ok-{n}"

        tasks = [("a1", maybe_fail, (1,), {}), ("a2", maybe_fail, (2,), {}), ("a3", maybe_fail, (3,), {})]
        results = await loop.run_all(tasks)
        success = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        assert len(success) == 2
        assert len(failures) == 1

    @pytest.mark.asyncio
    async def test_concurrency_throttled(self, loop_cfg):
        """Verify semaphore throttles concurrent invocations."""
        cfg = AsyncLoopConfig(max_concurrency=1, timeout_seconds=10.0)
        loop = AsyncAgentLoop(config=cfg)

        running = 0
        max_running = 0

        async def concurrent_task(n):
            nonlocal running, max_running
            running += 1
            max_running = max(max_running, running)
            await asyncio.sleep(0.01)
            running -= 1
            return n

        tasks = [(f"a{i}", concurrent_task, (i,), {}) for i in range(5)]
        results = await loop.run_all(tasks)
        assert all(r.success for r in results)
        assert max_running == 1  # semaphore ensures single concurrency


# ============================================================================
# AsyncAgentLoop — metrics
# ============================================================================

class TestMetrics:
    @pytest.mark.asyncio
    async def test_metrics_accumulate(self, loop):
        async def work(x):
            return x

        await loop.run_single("a", work, 1)
        await loop.run_single("b", work, 2)

        stats = loop.get_latency_stats()
        assert stats is not None
        assert "p50_ms" in stats

    @pytest.mark.asyncio
    async def test_reset_metrics(self, loop):
        async def work(x):
            return x

        await loop.run_single("a", work, 1)
        loop.reset_metrics()
        stats = loop.get_latency_stats()
        # After reset, metrics list is empty - stats may be empty dict or None
        assert (stats is None or stats == {} or stats.get("count", 0) == 0)

    def test_metrics_disabled(self):
        cfg = AsyncLoopConfig(collect_metrics=False)
        loop = AsyncAgentLoop(config=cfg)
        stats = loop.get_latency_stats()
        # metrics disabled returns all-zero dict
        assert stats is not None
        assert stats.get("count", 0) == 0
