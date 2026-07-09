"""Tests for agentos.core.background — background task execution framework."""

from __future__ import annotations

import asyncio

import pytest

from agentos.core.background import (
    BackgroundExecutor,
    CronSchedule,
    IntervalSchedule,
    RetryPolicy,
    TaskDef,
    TaskQueue,
    TaskResult,
    TaskState,
    get_background_executor,
    set_background_executor,
)

# ============================================================================
# TaskState
# ============================================================================

class TestTaskState:
    def test_enum_values(self):
        assert TaskState.PENDING is not None
        assert TaskState.RUNNING is not None
        assert TaskState.DONE is not None
        assert TaskState.FAILED is not None
        assert TaskState.CANCELLED is not None
        assert TaskState.RETRYING is not None


# ============================================================================
# TaskResult
# ============================================================================

class TestTaskResult:
    def test_defaults(self):
        result = TaskResult(task_id="abc", state=TaskState.PENDING)
        assert result.task_id == "abc"
        assert result.state == TaskState.PENDING
        assert result.result is None
        assert result.error is None
        assert result.duration is None

    def test_duration(self):
        result = TaskResult(
            task_id="t1", state=TaskState.DONE,
            started_at=100.0, finished_at=101.5,
        )
        assert result.duration == 1.5

    def test_duration_none_without_times(self):
        result = TaskResult(task_id="t1", state=TaskState.DONE)
        assert result.duration is None


# ============================================================================
# RetryPolicy
# ============================================================================

class TestRetryPolicy:
    def test_defaults(self):
        rp = RetryPolicy()
        assert rp.max_retries == 3
        assert rp.base_delay == 1.0
        assert rp.max_delay == 60.0
        assert rp.backoff_factor == 2.0
        assert rp.jitter is True
        assert rp.retry_on == (Exception,)

    def test_delay_grows_exponentially(self):
        rp = RetryPolicy(backoff_factor=2.0, jitter=False)
        d0 = rp.delay(0)
        d1 = rp.delay(1)
        d2 = rp.delay(2)
        assert d1 > d0
        assert d2 > d1

    def test_delay_capped_at_max(self):
        rp = RetryPolicy(max_delay=5.0, jitter=False)
        big_delay = rp.delay(100)
        assert big_delay <= 5.0

    def test_custom_retry_on(self):
        rp = RetryPolicy(retry_on=(ValueError, KeyError))
        assert rp.retry_on == (ValueError, KeyError)


# ============================================================================
# CronSchedule / IntervalSchedule
# ============================================================================

class TestSchedules:
    def test_cron_defaults(self):
        s = CronSchedule()
        assert s.minute == "*"
        assert s.hour == "*"
        assert s.day_of_month == "*"
        assert s.month == "*"
        assert s.day_of_week == "*"

    def test_cron_immutable(self):
        s = CronSchedule(minute="5")
        with pytest.raises(Exception):
            s.minute = "10"  # frozen dataclass

    def test_interval_defaults(self):
        s = IntervalSchedule(seconds=10.0)
        assert s.seconds == 10.0
        assert s.align_to_start is True


# ============================================================================
# TaskDef
# ============================================================================

class TestTaskDef:
    async def dummy(self):
        pass

    def test_auto_generates_id(self):
        td = TaskDef(func=self.dummy)
        assert len(td.task_id) == 12

    def test_auto_generates_name(self):
        td = TaskDef(func=self.dummy)
        assert td.name == "dummy"

    def test_custom_task_id(self):
        td = TaskDef(func=self.dummy, task_id="custom-123")
        assert td.task_id == "custom-123"

    def test_custom_name(self):
        td = TaskDef(func=self.dummy, name="my-task")
        assert td.name == "my-task"


# ============================================================================
# TaskQueue
# ============================================================================

class TestTaskQueue:
    async def dummy(self):
        pass

    @pytest.mark.asyncio
    async def test_put_and_get(self):
        q = TaskQueue()
        td = TaskDef(func=self.dummy, name="test1")
        await q.put(td)
        retrieved = await q.get()
        assert retrieved.name == "test1"
        q.task_done()

    @pytest.mark.asyncio
    async def test_qsize(self):
        q = TaskQueue()
        assert q.qsize == 0
        await q.put(TaskDef(func=self.dummy))
        assert q.qsize == 1
        await q.get()
        assert q.qsize == 0

    @pytest.mark.asyncio
    async def test_empty(self):
        q = TaskQueue()
        assert q.empty is True
        await q.put(TaskDef(func=self.dummy))
        assert q.empty is False

    @pytest.mark.asyncio
    async def test_join(self):
        q = TaskQueue()
        await q.put(TaskDef(func=self.dummy, name="j1"))
        td = await q.get()
        q.task_done()
        await q.join()  # should return immediately when queue is empty+done


# ============================================================================
# BackgroundExecutor — Submission
# ============================================================================

class TestBackgroundExecutorSubmit:
    @pytest.mark.asyncio
    async def test_submit_returns_result(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def add(a, b):
            return a + b

        result = await executor.submit(add, 3, 4)
        assert result.state == TaskState.DONE
        assert result.result == 7
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_submit_task_id_in_result(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def noop():
            pass

        result = await executor.submit(noop, task_id="my-task")
        assert result.task_id == "my-task"
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_submit_async_returns_task_id(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def slow():
            await asyncio.sleep(0.05)
            return 42

        task_id = await executor.submit_async(slow)
        assert len(task_id) > 0

        tr = await executor.wait_for(task_id, timeout=5.0)
        assert tr.state == TaskState.DONE
        assert tr.result == 42
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_submit_rejected_during_shutdown(self):
        executor = BackgroundExecutor()
        await executor.start()
        await executor.shutdown()

        async def noop():
            pass

        with pytest.raises(RuntimeError, match="shutting down"):
            await executor.submit(noop)

    @pytest.mark.asyncio
    async def test_get_result_while_running(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def work():
            return 99

        task_id = await executor.submit_async(work)
        result = await executor.wait_for(task_id, timeout=5.0)
        assert result.result == 99
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_get_result_nonexistent(self):
        executor = BackgroundExecutor()
        await executor.start()
        result = executor.get_result("nonexistent")
        assert result is None
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def forever():
            await asyncio.sleep(99)

        task_id = await executor.submit_async(forever)
        with pytest.raises(asyncio.TimeoutError):
            await executor.wait_for(task_id, timeout=0.1)
        await executor.shutdown()


# ============================================================================
# BackgroundExecutor — Retry
# ============================================================================

class TestBackgroundExecutorRetry:
    @pytest.mark.asyncio
    async def test_retry_success(self):
        executor = BackgroundExecutor()
        await executor.start()
        call_count = []

        async def flaky():
            call_count.append(1)
            if len(call_count) < 3:
                raise ValueError("not ready")
            return "ok"

        result = await executor.submit(
            flaky,
            retry_policy=RetryPolicy(max_retries=3, base_delay=0.01, jitter=False),
        )
        assert result.state == TaskState.DONE
        assert result.result == "ok"
        assert len(call_count) == 3
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def always_fails():
            raise RuntimeError("boom")

        result = await executor.submit(
            always_fails,
            retry_policy=RetryPolicy(max_retries=2, base_delay=0.01, jitter=False),
        )
        assert result.state == TaskState.FAILED
        assert isinstance(result.error, RuntimeError)
        assert result.retries == 2
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_retry_skipped_for_wrong_exception_type(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def type_error_func():
            raise TypeError("wrong type")

        result = await executor.submit(
            type_error_func,
            retry_policy=RetryPolicy(
                max_retries=3,
                base_delay=0.01,
                retry_on=(ValueError,),  # Only retry on ValueError
            ),
        )
        assert result.state == TaskState.FAILED
        assert isinstance(result.error, TypeError)
        assert result.retries == 0  # No retry for TypeError
        await executor.shutdown()


# ============================================================================
# BackgroundExecutor — Workers / Concurrency
# ============================================================================

class TestBackgroundExecutorWorkers:
    @pytest.mark.asyncio
    async def test_workers_process_queue(self):
        executor = BackgroundExecutor(max_concurrency=5)
        await executor.start(num_workers=3)
        call_count = []

        async def work(n):
            await asyncio.sleep(0.02)
            call_count.append(n)
            return n * 2

        # Submit via async (fire+forget) — workers will pick them up
        ids = []
        for i in range(10):
            tid = await executor.submit_async(work, i)
            ids.append(tid)

        # Wait for all to complete
        results = []
        for tid in ids:
            tr = await executor.wait_for(tid, timeout=10.0)
            results.append(tr)

        assert len(call_count) == 10
        all_done = [r.state == TaskState.DONE for r in results]
        assert all(all_done)
        await executor.shutdown()


# ============================================================================
# BackgroundExecutor — Timeout
# ============================================================================

class TestBackgroundExecutorTimeout:
    @pytest.mark.asyncio
    async def test_timeout_kills_task(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def slow():
            await asyncio.sleep(5.0)

        result = await executor.submit(slow, timeout=0.1)
        assert result.state == TaskState.FAILED
        await executor.shutdown()


# ============================================================================
# BackgroundExecutor — Scheduled
# ============================================================================

class TestBackgroundExecutorScheduled:
    @pytest.mark.asyncio
    async def test_scheduled_decorator_registers(self):
        executor = BackgroundExecutor()

        @executor.scheduled(every=60.0)
        async def cron_job():
            pass

        assert len(executor._scheduled) == 1
        schedule, td = executor._scheduled[0]
        assert schedule == 60.0
        assert td.name == "cron_job"

    @pytest.mark.asyncio
    async def test_scheduled_with_retry(self):
        executor = BackgroundExecutor()

        retry = RetryPolicy(max_retries=2)
        @executor.scheduled(every=10.0, retry_policy=retry)
        async def job_with_retry():
            pass

        assert len(executor._scheduled) == 1
        _, td = executor._scheduled[0]
        assert td.retry_policy is not None
        assert td.retry_policy.max_retries == 2

    @pytest.mark.asyncio
    async def test_interval_schedule(self):
        executor = BackgroundExecutor()

        @executor.scheduled(every=IntervalSchedule(seconds=30))
        async def periodic():
            pass

        assert len(executor._scheduled) == 1
        schedule, _ = executor._scheduled[0]
        assert isinstance(schedule, IntervalSchedule)
        assert schedule.seconds == 30


# ============================================================================
# BackgroundExecutor — Lifecycle
# ============================================================================

class TestBackgroundExecutorLifecycle:
    @pytest.mark.asyncio
    async def test_double_start_noop(self):
        executor = BackgroundExecutor()
        await executor.start()
        assert executor._running is True
        # double start should be noop
        await executor.start()
        assert executor._running is True
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_drains_queue(self):
        executor = BackgroundExecutor()
        await executor.start()

        async def fast():
            return "fast"

        ids = [await executor.submit_async(fast) for _ in range(5)]
        await executor.shutdown(timeout=5.0)

        # All should be done
        for tid in ids:
            result = executor.get_result(tid)
            assert result is not None
            assert result.state == TaskState.DONE


# ============================================================================
# Global Singleton
# ============================================================================

class TestGlobalSingleton:
    def test_get_background_executor_creates(self):
        executor = get_background_executor()
        assert isinstance(executor, BackgroundExecutor)

    def test_set_background_executor(self):
        custom = BackgroundExecutor(max_concurrency=42)
        set_background_executor(custom)
        assert get_background_executor() is custom
        assert custom._max_concurrency == 42

    def test_set_then_get(self):
        old = get_background_executor()
        new = BackgroundExecutor()
        set_background_executor(new)
        assert get_background_executor() is new
        # Restore
        set_background_executor(old)
