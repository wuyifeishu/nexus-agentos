"""Tests for agentos.core.background — Background Task Execution."""

import asyncio

import pytest

from agentos.core.background import (
    BackgroundExecutor,
    IntervalSchedule,
    RetryPolicy,
    TaskDef,
    TaskResult,
    TaskState,
)

# ═════════════════════════════════════════════════════════════════════════
# TaskDef
# ═════════════════════════════════════════════════════════════════════════

class TestTaskDef:
    def test_auto_generates_id(self):
        td = TaskDef(func=lambda: None)
        assert td.task_id
        assert len(td.task_id) == 12

    def test_custom_id(self):
        td = TaskDef(func=lambda: None, task_id="my-id")
        assert td.task_id == "my-id"

    def test_auto_name_from_func(self):
        async def my_workflow(): ...
        td = TaskDef(func=my_workflow)
        assert td.name == "my_workflow"


# ═════════════════════════════════════════════════════════════════════════
# RetryPolicy
# ═════════════════════════════════════════════════════════════════════════

class TestRetryPolicy:
    def test_delay_grows(self):
        rp = RetryPolicy(base_delay=1.0, backoff_factor=2.0, jitter=False)
        d0 = rp.delay(0)
        d1 = rp.delay(1)
        d2 = rp.delay(2)
        assert d0 == 1.0
        assert d1 == 2.0
        assert d2 == 4.0

    def test_max_delay_cap(self):
        rp = RetryPolicy(base_delay=1.0, backoff_factor=10.0, max_delay=3.0, jitter=False)
        assert rp.delay(5) == 3.0

    def test_retry_on_specific(self):
        rp = RetryPolicy(retry_on=(ValueError,))
        assert isinstance(ValueError("bad"), rp.retry_on)
        assert not isinstance(RuntimeError("fail"), rp.retry_on)


# ═════════════════════════════════════════════════════════════════════════
# BackgroundExecutor — basic execution
# ═════════════════════════════════════════════════════════════════════════

class TestBackgroundExecutorBasic:
    @pytest.fixture
    async def executor(self):
        ex = BackgroundExecutor(max_concurrency=4)
        await ex.start(num_workers=2)
        yield ex
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_submit_success(self, executor):
        async def work():
            await asyncio.sleep(0.01)
            return 42
        result = await executor.submit(work)
        assert result.state == TaskState.DONE
        assert result.result == 42
        assert result.duration > 0

    @pytest.mark.asyncio
    async def test_submit_with_args(self, executor):
        async def add(a, b): return a + b
        result = await executor.submit(add, 10, 20)
        assert result.result == 30

    @pytest.mark.asyncio
    async def test_submit_kwargs(self, executor):
        async def greet(name, greeting="Hello"):
            return f"{greeting}, {name}"
        result = await executor.submit(greet, "World", greeting="Hi")
        assert result.result == "Hi, World"

    @pytest.mark.asyncio
    async def test_submit_raises(self, executor):
        async def fail(): raise RuntimeError("boom")
        result = await executor.submit(fail)
        assert result.state == TaskState.FAILED
        assert isinstance(result.error, RuntimeError)
        assert str(result.error) == "boom"

    @pytest.mark.asyncio
    async def test_submit_async_return_id(self, executor):
        flags = []

        async def work():
            await asyncio.sleep(0.02)
            flags.append(1)

        tid = await executor.submit_async(work)
        assert len(tid) == 12
        result = await executor.wait_for(tid, timeout=5.0)
        assert result.state == TaskState.DONE
        assert flags == [1]

    @pytest.mark.asyncio
    async def test_get_result(self, executor):
        async def work(): return "done"
        result = await executor.submit(work)
        stored = executor.get_result(result.task_id)
        assert stored is result
        assert stored.state == TaskState.DONE

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self, executor):
        async def slow():
            await asyncio.sleep(10)

        tid = await executor.submit_async(slow)
        with pytest.raises(asyncio.TimeoutError):
            await executor.wait_for(tid, timeout=0.05)


# ═════════════════════════════════════════════════════════════════════════
# Retry
# ═════════════════════════════════════════════════════════════════════════

class TestBackgroundExecutorRetry:
    @pytest.fixture
    async def executor(self):
        ex = BackgroundExecutor(max_concurrency=2)
        await ex.start(num_workers=2)
        yield ex
        await ex.shutdown()

    @pytest.mark.asyncio
    async def test_retry_success(self, executor):
        attempt = [0]

        async def flaky():
            attempt[0] += 1
            if attempt[0] < 3:
                raise ValueError("try again")
            return "ok"

        result = await executor.submit(
            flaky,
            retry_policy=RetryPolicy(max_retries=3, base_delay=0.01, jitter=False),
        )
        assert result.state == TaskState.DONE
        assert result.result == "ok"
        assert result.retries == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted(self, executor):
        async def always_fail():
            raise ValueError("always")

        result = await executor.submit(
            always_fail,
            retry_policy=RetryPolicy(max_retries=2, base_delay=0.01),
        )
        assert result.state == TaskState.FAILED
        assert isinstance(result.error, ValueError)
        assert result.retries == 2

    @pytest.mark.asyncio
    async def test_no_retry_without_policy(self, executor):
        async def fail():
            raise RuntimeError("no retry")

        result = await executor.submit(fail)
        assert result.state == TaskState.FAILED
        assert result.retries == 0


# ═════════════════════════════════════════════════════════════════════════
# Concurrency & Semaphore
# ═════════════════════════════════════════════════════════════════════════

class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrency_limit(self):
        ex = BackgroundExecutor(max_concurrency=2)
        await ex.start(num_workers=4)

        running = 0
        max_running = 0
        lock = asyncio.Lock()

        async def work():
            nonlocal running, max_running
            async with lock:
                running += 1
                max_running = max(max_running, running)
            await asyncio.sleep(0.05)
            async with lock:
                running -= 1
            return True

        tasks = [ex.submit(work) for _ in range(6)]
        results = await asyncio.gather(*tasks)
        assert all(r.state == TaskState.DONE for r in results)
        assert max_running <= 2
        await ex.shutdown()


# ═════════════════════════════════════════════════════════════════════════
# Schedule
# ═════════════════════════════════════════════════════════════════════════

class TestScheduled:
    @pytest.mark.asyncio
    async def test_interval_schedule(self):
        ex = BackgroundExecutor(max_concurrency=2)
        runs = []

        async def tick():
            runs.append(1)

        ex.scheduled(every=IntervalSchedule(seconds=0.05))(tick)
        await ex.start(num_workers=2)
        await asyncio.sleep(0.25)
        await ex.shutdown()

        assert len(runs) >= 2

    @pytest.mark.asyncio
    async def test_float_interval(self):
        ex = BackgroundExecutor()
        runs = []

        @ex.scheduled(every=IntervalSchedule(seconds=0.03))
        async def tick():
            runs.append(1)

        await ex.start(num_workers=2)
        await asyncio.sleep(0.25)
        await ex.shutdown()

        assert len(runs) >= 2


# ═════════════════════════════════════════════════════════════════════════
# Shutdown
# ═════════════════════════════════════════════════════════════════════════

class TestShutdown:
    @pytest.mark.asyncio
    async def test_graceful_shutdown_drains_queue(self):
        ex = BackgroundExecutor(max_concurrency=2)
        await ex.start(num_workers=2)

        results = []

        async def make_worker(i):
            async def work():
                await asyncio.sleep(0.02)
                results.append(i)
            return work

        for i in range(5):
            await ex.submit_async(await make_worker(i))
        await asyncio.sleep(0.01)
        await ex.shutdown(timeout=5.0)
        assert len(results) == 5  # all drained


# ═════════════════════════════════════════════════════════════════════════
# TaskResult
# ═════════════════════════════════════════════════════════════════════════

class TestTaskResult:
    def test_duration_none_when_not_finished(self):
        r = TaskResult(task_id="1", state=TaskState.PENDING)
        assert r.duration is None

    def test_duration_computed(self):
        r = TaskResult(
            task_id="1", state=TaskState.DONE,
            started_at=100.0, finished_at=105.0,
        )
        assert r.duration == 5.0
