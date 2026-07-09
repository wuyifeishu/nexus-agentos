"""Test AsyncLoop — concurrent agent execution, timeouts, retry, streaming, metrics."""

from __future__ import annotations

import asyncio

import pytest

from agentos.core.async_loop import (
    AsyncAgentLoop,
    AsyncContextManager,
    AsyncInvocationResult,
    AsyncLoopConfig,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def loop_cfg():
    return AsyncLoopConfig(max_concurrency=5, timeout_seconds=1.0, max_retries=1)


@pytest.fixture
def loop(loop_cfg):
    return AsyncAgentLoop(config=loop_cfg)


@pytest.fixture
def strict_loop():
    return AsyncAgentLoop(AsyncLoopConfig(max_concurrency=1, timeout_seconds=0.05, max_retries=0, retry_on_timeout=False))


# ============================================================================
# AsyncLoopConfig
# ============================================================================

class TestAsyncLoopConfig:
    def test_defaults(self):
        cfg = AsyncLoopConfig()
        assert cfg.max_concurrency == 10
        assert cfg.timeout_seconds == 300.0
        assert cfg.retry_on_timeout is True
        assert cfg.max_retries == 3
        assert cfg.collect_metrics is True

    def test_custom(self):
        cfg = AsyncLoopConfig(max_concurrency=2, timeout_seconds=60.0, collect_metrics=False)
        assert cfg.max_concurrency == 2
        assert cfg.collect_metrics is False


# ============================================================================
# AsyncInvocationResult
# ============================================================================

class TestAsyncInvocationResult:
    def test_success_defaults(self):
        r = AsyncInvocationResult(agent_id="a1", success=True, output="done")
        assert r.agent_id == "a1"
        assert r.success is True
        assert r.output == "done"
        assert r.error is None
        assert r.retries == 0

    def test_failure(self):
        r = AsyncInvocationResult(agent_id="a1", success=False, error="boom", retries=3)
        assert r.success is False
        assert r.error == "boom"
        assert r.retries == 3


# ============================================================================
# run_single — success
# ============================================================================

class TestRunSingleSuccess:
    @pytest.mark.asyncio
    async def test_returns_result(self, loop):
        async def ok():
            return "hello"

        result = await loop.run_single("agent-1", ok)
        assert result.success
        assert result.output == "hello"
        assert result.agent_id == "agent-1"
        assert result.error is None
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_passes_args_kwargs(self, loop):
        async def add(a, b, *, mul=1):
            return (a + b) * mul

        result = await loop.run_single("math", add, 10, 20, mul=2)
        assert result.output == 60

    @pytest.mark.asyncio
    async def test_collects_metrics(self, loop):
        async def work():
            await asyncio.sleep(0.01)
            return "ok"

        await loop.run_single("a", work)
        stats = loop.get_latency_stats()
        assert stats["count"] == 1
        assert stats["p50_ms"] > 0


# ============================================================================
# run_single — timeout / error
# ============================================================================

class TestRunSingleErrors:
    @pytest.mark.asyncio
    async def test_timeout_fails(self, strict_loop):
        async def slow():
            await asyncio.sleep(10)
            return "never"

        result = await strict_loop.run_single("slow", slow)
        assert not result.success
        assert "Timeout" in result.error

    @pytest.mark.asyncio
    async def test_exception_fails_with_retries(self, loop):
        calls = []

        async def flaky():
            calls.append(1)
            raise ValueError("boom")

        result = await loop.run_single("flaky", flaky)
        assert not result.success
        assert "ValueError" in result.error
        assert result.retries == 1  # max_retries=1 → 1 retry after initial failure
        assert len(calls) == 2  # 2 total attempts: initial + 1 retry

    @pytest.mark.asyncio
    async def test_no_retries_on_exception_with_max_retries_zero(self):
        lo = AsyncAgentLoop(AsyncLoopConfig(max_concurrency=1, timeout_seconds=5.0, max_retries=0))
        calls = []

        async def boom():
            calls.append(1)
            raise RuntimeError("fail")

        result = await lo.run_single("b", boom)
        assert not result.success
        assert result.retries == 0


# ============================================================================
# run_all — concurrent execution
# ============================================================================

class TestRunAll:
    @pytest.mark.asyncio
    async def test_runs_all_tasks(self, loop):
        async def echo(x):
            return x

        tasks = [
            ("a1", echo, (1,), {}),
            ("a2", echo, (2,), {}),
            ("a3", echo, (3,), {}),
        ]
        results = await loop.run_all(tasks)
        assert len(results) == 3
        outputs = {r.agent_id: r.output for r in results}
        assert outputs == {"a1": 1, "a2": 2, "a3": 3}

    @pytest.mark.asyncio
    async def test_respects_order(self, loop):
        async def echo(x):
            return x

        tasks = [("a1", echo, (10,), {}), ("a2", echo, (20,), {})]
        results = await loop.run_all(tasks)
        assert results[0].output == 10
        assert results[1].output == 20

    @pytest.mark.asyncio
    async def test_partial_failure_does_not_block(self, loop):
        async def ok():
            return "ok"

        async def bad():
            raise RuntimeError("fail")

        tasks = [("ok", ok, (), {}), ("bad", bad, (), {})]
        results = await loop.run_all(tasks)
        assert results[0].success
        assert not results[1].success
        assert results[1].error is not None


# ============================================================================
# Concurrency (semaphore)
# ============================================================================

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        cfg = AsyncLoopConfig(max_concurrency=2, timeout_seconds=5.0, max_retries=1)
        lo = AsyncAgentLoop(cfg)

        concurrent = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        async def limited():
            nonlocal concurrent, max_concurrent
            concurrent += 1
            async with lock:
                if concurrent > max_concurrent:
                    max_concurrent = concurrent
            await asyncio.sleep(0.02)
            concurrent -= 1
            return "ok"

        tasks = [(f"a{i}", limited, (), {}) for i in range(6)]
        await lo.run_all(tasks)
        assert max_concurrent <= 2


# ============================================================================
# Streaming
# ============================================================================

class TestStreaming:
    @pytest.mark.asyncio
    async def test_yields_chunks(self, loop):
        chunks = []

        async def stream():
            for i in range(3):
                yield f"chunk_{i}"

        results = []
        async for chunk in loop.run_streaming("s1", stream):
            results.append(chunk)

        assert results == ["chunk_0", "chunk_1", "chunk_2"]

    @pytest.mark.asyncio
    async def test_streaming_collects_metrics(self, loop):
        async def stream():
            yield "x"

        async for _ in loop.run_streaming("s", stream):
            pass

        stats = loop.get_latency_stats()
        assert stats["count"] == 1


# ============================================================================
# Latency stats
# ============================================================================

class TestLatencyStats:
    @pytest.mark.asyncio
    async def test_empty_returns_zeros(self, loop):
        stats = loop.get_latency_stats()
        assert stats == {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "mean_ms": 0, "count": 0}

    @pytest.mark.asyncio
    async def test_percentile_ordering(self, loop):
        async def work(s):
            await asyncio.sleep(s)
            return "ok"

        await loop.run_single("a", work, 0.01)
        await loop.run_single("b", work, 0.02)
        await loop.run_single("c", work, 0.03)

        stats = loop.get_latency_stats()
        assert stats["count"] == 3
        assert stats["p50_ms"] <= stats["p95_ms"] <= stats["p99_ms"]
        assert stats["mean_ms"] > 0

    def test_reset_metrics(self, loop):
        stats = loop.get_latency_stats()
        assert stats["count"] == 0
        loop._metrics.append(100.0)
        loop._metrics.append(200.0)
        loop.reset_metrics()
        stats = loop.get_latency_stats()
        assert stats["count"] == 0

    @pytest.mark.asyncio
    async def test_metrics_disabled(self):
        lo = AsyncAgentLoop(AsyncLoopConfig(collect_metrics=False))

        async def ok():
            return "x"

        await lo.run_single("a", ok)
        assert lo.get_latency_stats()["count"] == 0


# ============================================================================
# AsyncContextManager
# ============================================================================

class TestAsyncContextManager:
    @pytest.mark.asyncio
    async def test_get_set(self):
        from agentos.core.context import AgentContext
        ctx = AgentContext(messages=[])
        mgr = AsyncContextManager(ctx)

        await mgr.set("key", "val")
        assert await mgr.get("key") == "val"

    @pytest.mark.asyncio
    async def test_get_default(self):
        from agentos.core.context import AgentContext
        ctx = AgentContext(messages=[])
        mgr = AsyncContextManager(ctx)

        assert await mgr.get("missing", 42) == 42

    @pytest.mark.asyncio
    async def test_update(self):
        from agentos.core.context import AgentContext
        ctx = AgentContext(messages=[])
        mgr = AsyncContextManager(ctx)

        await mgr.update({"a": 1, "b": 2})
        assert await mgr.get("a") == 1
        assert await mgr.get("b") == 2

    @pytest.mark.asyncio
    async def test_snapshot(self):
        from agentos.core.context import AgentContext
        ctx = AgentContext(messages=[])
        mgr = AsyncContextManager(ctx)

        await mgr.set("x", 10)
        snap = await mgr.snapshot()
        assert snap["x"] == 10
        assert isinstance(snap, dict)

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        from agentos.core.context import AgentContext
        ctx = AgentContext(messages=[])
        mgr = AsyncContextManager(ctx)

        async def writer(start, n):
            for i in range(n):
                await mgr.set(f"k_{start}_{i}", start + i)

        await asyncio.gather(writer(0, 10), writer(100, 10))
        snap = await mgr.snapshot()
        assert len(snap) == 20


# ============================================================================
# AsyncLoopConfig — retry_on_timeout behavior
# ============================================================================

class TestRetryOnTimeout:
    @pytest.mark.asyncio
    async def test_no_retry_when_disabled(self):
        lo = AsyncAgentLoop(AsyncLoopConfig(max_concurrency=1, timeout_seconds=0.01, max_retries=2, retry_on_timeout=False))

        async def slow():
            await asyncio.sleep(10)

        result = await lo.run_single("t", slow)
        assert not result.success
        assert result.retries == 0  # no retries because retry_on_timeout is False

    @pytest.mark.asyncio
    async def test_retries_when_enabled(self):
        lo = AsyncAgentLoop(AsyncLoopConfig(max_concurrency=1, timeout_seconds=0.01, max_retries=2, retry_on_timeout=True))

        async def slow():
            await asyncio.sleep(10)

        result = await lo.run_single("t", slow)
        assert not result.success
        assert result.retries == 2  # 0, 1, 2 = 3 attempts


# ============================================================================
# Default config (no args)
# ============================================================================

class TestDefaultConstruction:
    @pytest.mark.asyncio
    async def test_works_with_no_config(self):
        lo = AsyncAgentLoop()
        async def ok():
            return "works"

        result = await lo.run_single("a", ok)
        assert result.success
        assert result.output == "works"
