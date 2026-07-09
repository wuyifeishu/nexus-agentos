"""Tests for agentos.concurrent.parallel — ParallelExecutor & friends."""

import asyncio

import pytest

from agentos.concurrent.parallel import (
    FanOutConfig,
    FanOutExecutor,
    GatherResult,
    ParallelExecutor,
    TaskResult,
    TaskStatus,
    TaskThrottler,
    create_parallel_agent_gather,
    parallel_gather,
    parallel_map,
)

# ─── TaskStatus ────────────────────────────────────────────────

class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.TIMEOUT == "timeout"
        assert TaskStatus.CANCELLED == "cancelled"

    def test_enum_membership(self):
        assert isinstance(TaskStatus.PENDING, str)
        assert TaskStatus.PENDING in TaskStatus.__members__.values()


# ─── TaskResult ─────────────────────────────────────────────────

class TestTaskResult:
    def test_defaults(self):
        r = TaskResult(task_id="t1")
        assert r.task_id == "t1"
        assert r.status == TaskStatus.PENDING
        assert r.result is None
        assert r.error is None
        assert r.started_at == 0.0
        assert r.finished_at == 0.0
        assert r.duration_ms == 0.0
        assert r.retries == 0

    def test_full(self):
        err = ValueError("boom")
        r = TaskResult(
            task_id="t2", status=TaskStatus.FAILED, result=None,
            error=err, started_at=1.0, finished_at=2.0,
            duration_ms=1000.0, retries=3,
        )
        assert r.error is err
        assert r.retries == 3
        assert r.duration_ms == 1000.0


# ─── GatherResult ───────────────────────────────────────────────

class TestGatherResult:
    def test_defaults(self):
        g = GatherResult()
        assert g.results == []
        assert g.total == 0
        assert g.completed == 0
        assert g.failed == 0
        assert g.timed_out == 0
        assert g.cancelled == 0
        assert g.all_succeeded is False

    def test_success_rate(self):
        g = GatherResult(total=10, completed=7)
        assert g.success_rate == 0.7

    def test_success_rate_zero_total(self):
        g = GatherResult(total=0)
        assert g.success_rate == 0.0

    def test_get_results(self):
        r1 = TaskResult(task_id="a", status=TaskStatus.COMPLETED, result=1)
        r2 = TaskResult(task_id="b", status=TaskStatus.FAILED, result=2)
        r3 = TaskResult(task_id="c", status=TaskStatus.COMPLETED, result=3)
        g = GatherResult(results=[r1, r2, r3])
        assert g.get_results() == [1, 3]

    def test_get_results_empty(self):
        g = GatherResult()
        assert g.get_results() == []

    def test_get_errors(self):
        err1 = ValueError("a")
        r1 = TaskResult(task_id="x", error=err1)
        r2 = TaskResult(task_id="y", error=None)
        g = GatherResult(results=[r1, r2])
        errors = g.get_errors()
        assert len(errors) == 1
        assert errors[0][0] == "x"
        assert errors[0][1] is err1


# ─── TaskThrottler ──────────────────────────────────────────────

class TestTaskThrottler:
    def test_init_default(self):
        t = TaskThrottler()
        assert t.max_concurrent == 10
        assert t.active == 0
        assert t.peak == 0

    def test_init_custom(self):
        t = TaskThrottler(max_concurrent=5)
        assert t.max_concurrent == 5

    def test_init_zero_raises(self):
        with pytest.raises(ValueError, match="max_concurrent"):
            TaskThrottler(max_concurrent=0)

    def test_init_negative_raises(self):
        with pytest.raises(ValueError, match="max_concurrent"):
            TaskThrottler(max_concurrent=-1)

    @pytest.mark.asyncio
    async def test_context_manager(self):
        t = TaskThrottler(max_concurrent=3)
        assert t.active == 0
        async with t:
            assert t.active == 1
            assert t.peak == 1
        assert t.active == 0

    @pytest.mark.asyncio
    async def test_concurrent_throttling(self):
        t = TaskThrottler(max_concurrent=2)
        active_values = []

        async def worker(n):
            async with t:
                active_values.append(t.active)
                assert t.active <= 2
                await asyncio.sleep(0.02)

        await asyncio.gather(*(worker(i) for i in range(5)))
        assert t.peak <= 2
        assert t.active == 0

    @pytest.mark.asyncio
    async def test_peak_tracking(self):
        t = TaskThrottler(max_concurrent=3)

        async def worker():
            async with t:
                await asyncio.sleep(0.02)

        await asyncio.gather(*(worker() for _ in range(3)))
        assert t.peak == 3

    @pytest.mark.asyncio
    async def test_exception_releases(self):
        t = TaskThrottler(max_concurrent=1)

        async def bad():
            async with t:
                raise ValueError("oops")

        with pytest.raises(ValueError, match="oops"):
            await bad()
        assert t.active == 0
        # Semaphore should be released — another task can acquire
        async with t:
            pass
        assert t.active == 0


# ─── ParallelExecutor.gather ───────────────────────────────────

class TestParallelExecutorGather:
    @pytest.mark.asyncio
    async def test_empty(self):
        exe = ParallelExecutor()
        result = await exe.gather([])
        assert result.total == 0
        assert result.completed == 0

    @pytest.mark.asyncio
    async def test_single_success(self):
        async def ok():
            return 42

        exe = ParallelExecutor()
        result = await exe.gather([ok()])
        assert result.completed == 1
        assert result.all_succeeded is True
        assert result.get_results() == [42]

    @pytest.mark.asyncio
    async def test_single_failure(self):
        async def bad():
            raise ValueError("fail")

        exe = ParallelExecutor()
        result = await exe.gather([bad()])
        assert result.failed == 1
        assert result.completed == 0
        assert result.all_succeeded is False

    @pytest.mark.asyncio
    async def test_multiple_parallel(self):
        async def work(n):
            await asyncio.sleep(0.01)
            return n * 10

        exe = ParallelExecutor(max_concurrent=5)
        coros = [work(i) for i in range(4)]
        result = await exe.gather(coros)
        assert result.completed == 4
        assert sorted(result.get_results()) == [0, 10, 20, 30]

    @pytest.mark.asyncio
    async def test_mixed_results(self):
        async def ok():
            return "ok"

        async def fail():
            raise RuntimeError("fail")

        exe = ParallelExecutor(max_concurrent=3)
        result = await exe.gather([ok(), ok(), fail()])
        assert result.completed == 2
        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_timeout_partial(self):
        async def slow():
            await asyncio.sleep(10)

        async def fast():
            return "fast"

        exe = ParallelExecutor(max_concurrent=3)
        result = await exe.gather([slow(), fast()], timeout=0.05, return_partial=True)
        assert result.completed >= 1
        assert result.timed_out >= 1

    @pytest.mark.asyncio
    async def test_timeout_no_partial_raises(self):
        async def slow():
            await asyncio.sleep(10)

        exe = ParallelExecutor(max_concurrent=3)
        with pytest.raises(TimeoutError, match="timed out"):
            await exe.gather([slow()], timeout=0.05, return_partial=False)

    @pytest.mark.asyncio
    async def test_fail_fast(self):
        order = []

        async def work(n):
            order.append(n)
            if n == 1:
                raise ValueError("fail fast")
            await asyncio.sleep(0.5)
            return n

        exe = ParallelExecutor(max_concurrent=3, fail_fast=True)
        result = await exe.gather([work(0), work(1), work(2)])
        # At least the failing task is captured
        assert result.failed >= 1

    @pytest.mark.asyncio
    async def test_duration_tracking(self):
        async def work():
            await asyncio.sleep(0.02)

        exe = ParallelExecutor()
        result = await exe.gather([work(), work()])
        assert result.total_duration_ms > 0

    @pytest.mark.asyncio
    async def test_task_result_timestamps(self):
        async def work():
            await asyncio.sleep(0.01)
            return 1

        exe = ParallelExecutor()
        result = await exe.gather([work()])
        r = result.results[0]
        assert r.started_at > 0
        assert r.finished_at > 0
        assert r.duration_ms > 0

    @pytest.mark.asyncio
    async def test_concurrency_limit(self):
        concurrent = 0
        peak = 0

        async def work():
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.03)
            concurrent -= 1
            return "done"

        exe = ParallelExecutor(max_concurrent=2, timeout=10.0)
        result = await exe.gather([work() for _ in range(6)])
        assert result.completed == 6
        assert peak <= 2


# ─── ParallelExecutor.map ──────────────────────────────────────

class TestParallelExecutorMap:
    @pytest.mark.asyncio
    async def test_map_basic(self):
        async def double(x):
            return x * 2

        exe = ParallelExecutor(max_concurrent=3)
        result = await exe.map(double, [1, 2, 3])
        assert result.completed == 3
        assert sorted(result.get_results()) == [2, 4, 6]

    @pytest.mark.asyncio
    async def test_map_empty(self):
        async def f(x):
            return x

        exe = ParallelExecutor()
        result = await exe.map(f, [])
        assert result.total == 0


# ─── parallel_gather convenience ───────────────────────────────

class TestParallelGather:
    @pytest.mark.asyncio
    async def test_basic(self):
        async def a():
            return "a"

        async def b():
            return "b"

        result = await parallel_gather(a(), b(), max_concurrent=2)
        assert result.completed == 2
        assert set(result.get_results()) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_timeout_partial(self):
        async def slow():
            await asyncio.sleep(10)

        async def fast():
            return "fast"

        result = await parallel_gather(slow(), fast(), max_concurrent=2, timeout=0.05, return_partial=True)
        assert result.completed >= 1


# ─── parallel_map convenience ──────────────────────────────────

class TestParallelMap:
    @pytest.mark.asyncio
    async def test_basic(self):
        async def sq(x):
            return x * x

        result = await parallel_map(sq, [1, 2, 3, 4], max_concurrent=3)
        assert result.completed == 4
        assert sorted(result.get_results()) == [1, 4, 9, 16]


# ─── FanOutConfig ──────────────────────────────────────────────

class TestFanOutConfig:
    def test_defaults(self):
        c = FanOutConfig()
        assert c.max_concurrent == 8
        assert c.timeout == 60.0
        assert c.aggregation == "all"
        assert c.retry_failed is False
        assert c.max_retries == 2

    def test_custom(self):
        c = FanOutConfig(aggregation="first", max_concurrent=4)
        assert c.aggregation == "first"
        assert c.max_concurrent == 4


# ─── FanOutExecutor ────────────────────────────────────────────

class TestFanOutExecutor:
    @pytest.mark.asyncio
    async def test_all_mode(self):
        async def w(n):
            return n

        fe = FanOutExecutor()
        result = await fe.fan_out([w(1), w(2), w(3)])
        # "all" mode returns GatherResult
        assert isinstance(result, GatherResult)
        assert result.completed == 3

    @pytest.mark.asyncio
    async def test_first_mode(self):
        async def fast():
            await asyncio.sleep(0.01)
            return "fast"

        async def slow():
            await asyncio.sleep(0.1)
            return "slow"

        fe = FanOutExecutor(FanOutConfig(aggregation="first"))
        r = await fe.fan_out([fast(), slow()])
        assert r == "fast"

    @pytest.mark.asyncio
    async def test_first_all_fail(self):
        async def fail():
            raise ValueError("all dead")

        fe = FanOutExecutor(FanOutConfig(aggregation="first"))
        with pytest.raises(ValueError, match="all dead"):
            await fe.fan_out([fail()])

    @pytest.mark.asyncio
    async def test_merge_mode(self):
        async def w(n):
            return n

        def merge(results):
            return sum(results)

        fe = FanOutExecutor(FanOutConfig(aggregation="merge"))
        r = await fe.fan_out([w(1), w(2), w(3)], merge_fn=merge)
        assert r == 6

    @pytest.mark.asyncio
    async def test_merge_no_fn_raises(self):
        async def w(n):
            return n

        fe = FanOutExecutor(FanOutConfig(aggregation="merge"))
        with pytest.raises(ValueError, match="merge_fn"):
            await fe.fan_out([w(1)])

    def test_init_default(self):
        fe = FanOutExecutor()
        assert fe.config.max_concurrent == 8

    def test_init_with_config(self):
        fe = FanOutExecutor(FanOutConfig(max_concurrent=2, timeout=30.0))
        assert fe.config.max_concurrent == 2
        assert fe.config.timeout == 30.0

    def test_init_with_max_concurrent_int(self):
        fe = FanOutExecutor(max_concurrent=4)
        assert fe.config.max_concurrent == 4


# ─── create_parallel_agent_gather ──────────────────────────────

class TestCreateParallelAgentGather:
    @pytest.mark.asyncio
    async def test_creates_callable(self):
        fn = create_parallel_agent_gather(max_concurrent=4, timeout=5.0)
        assert callable(fn)

    @pytest.mark.asyncio
    async def test_gather_works(self):
        async def w():
            return "ok"

        fn = create_parallel_agent_gather(max_concurrent=2, timeout=5.0)
        result = await fn(w(), w())
        assert result.completed == 2
