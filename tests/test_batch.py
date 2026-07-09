"""Tests for agentos.concurrency.batch — AsyncBatchExecutor."""

import asyncio

import pytest

from agentos.concurrency.batch import (
    AsyncBatchExecutor,
    BatchConfig,
    BatchResult,
    BatchStrategy,
    TaskResult,
    TaskSpec,
    TaskStatus,
)

# ─── TaskStatus ────────────────────────────────────────────────

class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.SUCCESS.value == "success"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.TIMEOUT.value == "timeout"
        assert TaskStatus.RETRYING.value == "retrying"
        assert TaskStatus.CANCELLED.value == "cancelled"

    def test_unique(self):
        vals = [e.value for e in TaskStatus]
        assert len(vals) == len(set(vals))


# ─── BatchStrategy ─────────────────────────────────────────────

class TestBatchStrategy:
    def test_values(self):
        assert BatchStrategy.PARALLEL.value == "parallel"
        assert BatchStrategy.SEQUENTIAL.value == "sequential"
        assert BatchStrategy.SMART.value == "smart"


# ─── TaskSpec ──────────────────────────────────────────────────

class TestTaskSpec:
    def test_minimal(self):
        async def f():
            pass
        ts = TaskSpec(task_id="t1", coro_or_func=f)
        assert ts.task_id == "t1"
        assert ts.args == ()
        assert ts.kwargs == {}
        assert ts.timeout == 60.0
        assert ts.max_retries == 0
        assert ts.metadata == {}

    def test_full(self):
        async def f(x):
            return x
        ts = TaskSpec(
            task_id="t2", coro_or_func=f, args=(1,), kwargs={"y": 2},
            timeout=30.0, max_retries=3, metadata={"priority": 1},
        )
        assert ts.args == (1,)
        assert ts.kwargs == {"y": 2}
        assert ts.timeout == 30.0
        assert ts.max_retries == 3


# ─── TaskResult ────────────────────────────────────────────────

class TestTaskResult:
    def test_defaults(self):
        r = TaskResult(task_id="t1", status=TaskStatus.PENDING)
        assert r.task_id == "t1"
        assert r.status == TaskStatus.PENDING
        assert r.result is None
        assert r.error is None
        assert r.duration_ms == 0.0
        assert r.retries == 0

    def test_success_property(self):
        assert TaskResult(task_id="t", status=TaskStatus.SUCCESS).success is True
        assert TaskResult(task_id="t", status=TaskStatus.FAILED).success is False
        assert TaskResult(task_id="t", status=TaskStatus.TIMEOUT).success is False
        assert TaskResult(task_id="t", status=TaskStatus.PENDING).success is False

    def test_full_fields(self):
        r = TaskResult(
            task_id="t1", status=TaskStatus.SUCCESS, result=42,
            error=None, duration_ms=100.0, retries=1,
            started_at=1.0, finished_at=2.0,
        )
        assert r.result == 42
        assert r.duration_ms == 100.0
        assert r.retries == 1


# ─── BatchConfig ───────────────────────────────────────────────

class TestBatchConfig:
    def test_defaults(self):
        c = BatchConfig()
        assert c.max_concurrency == 5
        assert c.default_timeout == 60.0
        assert c.max_retries == 1
        assert c.retry_delay == 1.0
        assert c.strategy == BatchStrategy.PARALLEL
        assert c.fail_fast is False
        assert c.collect_errors is True

    def test_custom(self):
        c = BatchConfig(max_concurrency=3, fail_fast=True, strategy=BatchStrategy.SEQUENTIAL)
        assert c.max_concurrency == 3
        assert c.fail_fast is True
        assert c.strategy == BatchStrategy.SEQUENTIAL


# ─── BatchResult ───────────────────────────────────────────────

class TestBatchResult:
    def test_defaults(self):
        br = BatchResult()
        assert br.results == []
        assert br.total == 0
        assert br.succeeded == 0
        assert br.failed == 0
        assert br.timed_out == 0

    def test_success_rate_zero(self):
        br = BatchResult()
        assert br.success_rate == 0.0

    def test_success_rate(self):
        br = BatchResult(
            results=[],
            total=10, succeeded=8, failed=2,
        )
        assert br.success_rate == 0.8

    def test_all_success(self):
        br = BatchResult(total=5, succeeded=5)
        assert br.all_success is True

    def test_not_all_success(self):
        br = BatchResult(total=5, succeeded=3, failed=2)
        assert br.all_success is False

    def test_get_failed_ids(self):
        r1 = TaskResult(task_id="a", status=TaskStatus.FAILED)
        r2 = TaskResult(task_id="b", status=TaskStatus.TIMEOUT)
        r3 = TaskResult(task_id="c", status=TaskStatus.SUCCESS)
        br = BatchResult(results=[r1, r2, r3])
        assert set(br.get_failed_ids()) == {"a", "b"}


# ─── AsyncBatchExecutor ────────────────────────────────────────

class TestAsyncBatchExecutor:
    @pytest.mark.asyncio
    async def test_empty_tasks(self):
        exe = AsyncBatchExecutor()
        result = await exe.execute([])
        assert result.total == 0
        assert result.succeeded == 0

    @pytest.mark.asyncio
    async def test_single_success(self):
        async def ok():
            return 42

        exe = AsyncBatchExecutor()
        result = await exe.execute([TaskSpec(task_id="t1", coro_or_func=ok)])
        assert result.total == 1
        assert result.succeeded == 1
        assert result.results[0].result == 42

    @pytest.mark.asyncio
    async def test_single_failure(self):
        async def bad():
            raise ValueError("boom")

        exe = AsyncBatchExecutor()
        result = await exe.execute([TaskSpec(task_id="t1", coro_or_func=bad)])
        assert result.total == 1
        assert result.failed == 1
        assert "boom" in result.results[0].error

    @pytest.mark.asyncio
    async def test_single_timeout(self):
        async def slow():
            await asyncio.sleep(10)

        exe = AsyncBatchExecutor(BatchConfig(default_timeout=0.01, max_retries=0))
        result = await exe.execute([TaskSpec(task_id="t1", coro_or_func=slow, timeout=0.01)])
        assert result.timed_out == 1

    @pytest.mark.asyncio
    async def test_single_timeout_with_retry(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                await asyncio.sleep(10)
            return "ok"

        exe = AsyncBatchExecutor(BatchConfig(default_timeout=0.05, max_retries=2, retry_delay=0.01))
        result = await exe.execute([TaskSpec(task_id="t1", coro_or_func=flaky, timeout=0.05, max_retries=2)])
        assert result.succeeded == 1
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_single_exhausted_retries(self):
        async def bad():
            raise ValueError("persistent")

        exe = AsyncBatchExecutor(BatchConfig(default_timeout=5.0, max_retries=2, retry_delay=0.01))
        result = await exe.execute([TaskSpec(task_id="t1", coro_or_func=bad, max_retries=2)])
        assert result.failed == 1
        assert result.results[0].retries == 2

    @pytest.mark.asyncio
    async def test_parallel_multiple(self):
        async def work(n):
            await asyncio.sleep(0.01)
            return n * 2

        tasks = [TaskSpec(task_id=f"t{i}", coro_or_func=work, args=(i,)) for i in range(3)]
        exe = AsyncBatchExecutor(BatchConfig(max_concurrency=3, strategy=BatchStrategy.PARALLEL))
        result = await exe.execute(tasks)
        assert result.total == 3
        assert result.succeeded == 3
        outputs = sorted(r.result for r in result.results)
        assert outputs == [0, 2, 4]

    @pytest.mark.asyncio
    async def test_sequential(self):
        order = []

        async def work(n):
            order.append(n)
            return n

        tasks = [TaskSpec(task_id=f"t{i}", coro_or_func=work, args=(i,)) for i in range(3)]
        exe = AsyncBatchExecutor(BatchConfig(strategy=BatchStrategy.SEQUENTIAL))
        result = await exe.execute(tasks)
        assert result.succeeded == 3
        # Sequential ensures ordered execution
        assert order == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_fail_fast_parallel(self):
        order = []

        async def work(n):
            order.append(n)
            if n == 1:
                raise ValueError("fail")
            await asyncio.sleep(0.05)
            return n

        tasks = [TaskSpec(task_id=f"t{i}", coro_or_func=work, args=(i,)) for i in range(3)]
        exe = AsyncBatchExecutor(BatchConfig(fail_fast=False, strategy=BatchStrategy.PARALLEL))
        result = await exe.execute(tasks)
        # fail_fast only affects sequential mode
        assert result.failed >= 1

    @pytest.mark.asyncio
    async def test_fail_fast_sequential(self):
        order = []

        async def work(n):
            order.append(n)
            if n == 1:
                raise ValueError("fail")
            return n

        tasks = [TaskSpec(task_id=f"t{i}", coro_or_func=work, args=(i,)) for i in range(3)]
        exe = AsyncBatchExecutor(BatchConfig(fail_fast=True, strategy=BatchStrategy.SEQUENTIAL, max_retries=0))
        result = await exe.execute(tasks)
        # Should stop after failure before running task 2
        assert len(order) <= 2

    @pytest.mark.asyncio
    async def test_cancel_all(self):
        exe = AsyncBatchExecutor()
        exe.cancel_all()  # Should not crash even if no tasks running

    @pytest.mark.asyncio
    async def test_default_config_used(self):
        async def ok():
            return "val"

        exe = AsyncBatchExecutor()
        result = await exe.execute([TaskSpec(task_id="t1", coro_or_func=ok)])
        assert result.succeeded == 1

    @pytest.mark.asyncio
    async def test_duration_tracked(self):
        async def ok():
            return 1

        exe = AsyncBatchExecutor()
        result = await exe.execute([TaskSpec(task_id="t1", coro_or_func=ok)])
        assert result.total_duration_ms >= 0
        assert result.started_at > 0
        assert result.finished_at > 0

    @pytest.mark.asyncio
    async def test_task_result_timestamps(self):
        async def ok():
            return 1

        exe = AsyncBatchExecutor()
        result = await exe.execute([TaskSpec(task_id="t1", coro_or_func=ok)])
        r = result.results[0]
        assert r.started_at > 0
        assert r.finished_at > 0
        assert r.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_mixed_results(self):
        async def ok():
            return "ok"

        async def fail():
            raise RuntimeError("fail")

        async def slow():
            await asyncio.sleep(10)

        exe = AsyncBatchExecutor(BatchConfig(max_concurrency=3, default_timeout=0.05, max_retries=0))
        tasks = [
            TaskSpec(task_id="t1", coro_or_func=ok),
            TaskSpec(task_id="t2", coro_or_func=fail),
            TaskSpec(task_id="t3", coro_or_func=slow, timeout=0.05),
        ]
        result = await exe.execute(tasks)
        assert result.succeeded == 1
        assert result.failed == 1
        assert result.timed_out == 1

    @pytest.mark.asyncio
    async def test_with_args_kwargs(self):
        async def add(a, b=0):
            return a + b

        exe = AsyncBatchExecutor()
        result = await exe.execute([
            TaskSpec(task_id="t1", coro_or_func=add, args=(3,), kwargs={"b": 5}),
            TaskSpec(task_id="t2", coro_or_func=add, args=(10,)),
        ])
        assert result.succeeded == 2
        vals = [r.result for r in result.results]
        assert sorted(vals) == [8, 10]
