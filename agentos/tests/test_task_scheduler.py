"""Tests for agentos.tools.task_scheduler — Task, PriorityTaskQueue, TaskScheduler, WorkerPool."""

import threading
import time

import pytest

from agentos.tools.task_scheduler import (
    PriorityTaskQueue,
    Task,
    TaskScheduler,
    TaskStatus,
    WorkerPool,
)

# ============================================================================
# TaskStatus
# ============================================================================

class TestTaskStatus:
    def test_enum_members(self):
        assert TaskStatus.PENDING is not None
        assert TaskStatus.RUNNING is not None
        assert TaskStatus.COMPLETED is not None
        assert TaskStatus.FAILED is not None
        assert TaskStatus.EXPIRED is not None
        assert TaskStatus.CANCELLED is not None

    def test_unique_values(self):
        values = [s.value for s in TaskStatus]
        assert len(values) == len(set(values))


# ============================================================================
# Task
# ============================================================================

class TestTask:
    def test_creation_defaults(self):
        t = Task(task_id="t1", func=lambda: 1)
        assert t.task_id == "t1"
        assert t.args == ()
        assert t.kwargs == {}
        assert t.priority == 0
        assert t.deadline is None
        assert t.status == TaskStatus.PENDING
        assert t.result is None
        assert t.error is None
        assert t.started_at is None
        assert t.completed_at is None

    def test_creation_with_args(self):
        t = Task(task_id="t2", func=lambda x: x, args=(5,), kwargs={"k": "v"},
                 priority=3, deadline=100.0)
        assert t.args == (5,)
        assert t.kwargs == {"k": "v"}
        assert t.priority == 3
        assert t.deadline == 100.0

    def test_run_success(self):
        t = Task(task_id="t3", func=lambda a, b: a + b, args=(1, 2))
        t.run()
        assert t.status == TaskStatus.COMPLETED
        assert t.result == 3
        assert t.error is None
        assert t.started_at is not None
        assert t.completed_at is not None

    def test_run_failure(self):
        def boom():
            raise ValueError("kaboom")

        t = Task(task_id="t4", func=boom)
        t.run()
        assert t.status == TaskStatus.FAILED
        assert t.result is None
        assert t.error == "kaboom"
        assert t.completed_at is not None

    def test_elapsed_returns_float(self):
        t = Task(task_id="t5", func=lambda: 1)
        assert t.elapsed is None  # not started
        t.run()
        assert isinstance(t.elapsed, float)
        assert t.elapsed >= 0

    def test_elapsed_before_start(self):
        t = Task(task_id="t6", func=lambda: 1)
        assert t.elapsed is None


# ============================================================================
# PriorityTaskQueue — Basic Operations
# ============================================================================

class TestPriorityTaskQueueBasic:
    def test_creation_defaults(self):
        q = PriorityTaskQueue()
        assert q.size == 0
        assert q._max_size == 1000

    def test_creation_custom_size(self):
        q = PriorityTaskQueue(max_size=10)
        assert q._max_size == 10

    def test_enqueue_dequeue(self):
        q = PriorityTaskQueue()
        t = Task(task_id="t1", func=lambda: 42)
        assert q.enqueue(t) is True
        assert q.size == 1

        result = q.dequeue()
        assert result is t
        assert q.size == 0

    def test_dequeue_empty(self):
        q = PriorityTaskQueue()
        assert q.dequeue() is None

    def test_enqueue_full(self):
        q = PriorityTaskQueue(max_size=2)
        q.enqueue(Task(task_id="a", func=lambda: 1))
        q.enqueue(Task(task_id="b", func=lambda: 2))
        assert q.enqueue(Task(task_id="c", func=lambda: 3)) is False
        assert q.size == 2

    def test_priority_ordering(self):
        q = PriorityTaskQueue()
        t1 = Task(task_id="low", func=lambda: 1, priority=10)
        t2 = Task(task_id="high", func=lambda: 2, priority=1)
        q.enqueue(t1)
        q.enqueue(t2)

        first = q.dequeue()
        second = q.dequeue()
        assert first.task_id == "high"
        assert second.task_id == "low"

    def test_same_priority_fifo(self):
        q = PriorityTaskQueue()
        t1 = Task(task_id="first", func=lambda: 1, priority=5)
        t2 = Task(task_id="second", func=lambda: 2, priority=5)
        q.enqueue(t1)
        q.enqueue(t2)

        assert q.dequeue().task_id == "first"
        assert q.dequeue().task_id == "second"


# ============================================================================
# PriorityTaskQueue — Cancellation
# ============================================================================

class TestPriorityTaskQueueCancel:
    def test_cancel_existing(self):
        q = PriorityTaskQueue()
        t = Task(task_id="x", func=lambda: 1)
        q.enqueue(t)
        assert q.cancel("x") is True
        assert q.size == 1  # still on heap (cleaned on dequeue)
        assert t.status == TaskStatus.CANCELLED

    def test_cancel_nonexistent(self):
        q = PriorityTaskQueue()
        assert q.cancel("no-such") is False

    def test_cancel_removed_on_dequeue(self):
        q = PriorityTaskQueue()
        t1 = Task(task_id="c", func=lambda: 1)
        t2 = Task(task_id="d", func=lambda: 2)
        q.enqueue(t1)
        q.enqueue(t2)
        q.cancel("c")
        result = q.dequeue()
        assert result is t2  # cancelled t1 skipped, t2 returned
        assert q.dequeue() is None


# ============================================================================
# PriorityTaskQueue — Expiration
# ============================================================================

class TestPriorityTaskQueueExpire:
    def test_deadline_expired(self):
        q = PriorityTaskQueue()
        t = Task(task_id="e", func=lambda: 1, deadline=time.monotonic() - 10)
        q.enqueue(t)
        result = q.dequeue()
        assert result is None
        assert t.status == TaskStatus.EXPIRED

    def test_deadline_future(self):
        q = PriorityTaskQueue()
        t = Task(task_id="f", func=lambda: 1, deadline=time.monotonic() + 3600)
        q.enqueue(t)
        result = q.dequeue()
        assert result is t
        assert t.status == TaskStatus.PENDING  # not expired

    def test_cancelled_before_expired(self):
        q = PriorityTaskQueue()
        t = Task(task_id="g", func=lambda: 1, deadline=time.monotonic() - 10)
        q.enqueue(t)
        q.cancel("g")
        result = q.dequeue()
        assert result is None  # cancelled and removed
        assert t.status == TaskStatus.CANCELLED

    def test_expired_stats(self):
        q = PriorityTaskQueue()
        t = Task(task_id="h", func=lambda: 1, deadline=time.monotonic() - 10)
        q.enqueue(t)
        q.dequeue()
        assert q.stats["total_expired"] == 1


# ============================================================================
# PriorityTaskQueue — Stats
# ============================================================================

class TestPriorityTaskQueueStats:
    def test_default_stats(self):
        q = PriorityTaskQueue(max_size=500)
        s = q.stats
        assert s["size"] == 0
        assert s["max_size"] == 500
        assert s["total_enqueued"] == 0
        assert s["total_dequeued"] == 0
        assert s["total_expired"] == 0

    def test_stats_after_ops(self):
        q = PriorityTaskQueue()
        q.enqueue(Task(task_id="a", func=lambda: 1))
        q.enqueue(Task(task_id="b", func=lambda: 2))
        q.dequeue()
        s = q.stats
        assert s["total_enqueued"] == 2
        assert s["total_dequeued"] == 1
        assert s["size"] == 1

    def test_stats_includes_expired(self):
        q = PriorityTaskQueue()
        t = Task(task_id="x", func=lambda: 1, deadline=time.monotonic() - 1)
        q.enqueue(t)
        q.dequeue()
        s = q.stats
        assert s["total_expired"] == 1


# ============================================================================
# TaskScheduler — Submit & Immediate Execution
# ============================================================================

class TestTaskSchedulerSubmit:
    def test_submit_and_run_once(self):
        sched = TaskScheduler()
        t = Task(task_id="t1", func=lambda: 99)
        assert sched.submit(t) is True
        result = sched.run_once()
        assert result is t
        assert t.status == TaskStatus.COMPLETED
        assert t.result == 99

    def test_submit_queue_full(self):
        sched = TaskScheduler()
        sched._queue = PriorityTaskQueue(max_size=1)
        t1 = Task(task_id="a", func=lambda: 1)
        t2 = Task(task_id="b", func=lambda: 2)
        assert sched.submit(t1) is True
        assert sched.submit(t2) is False

    def test_run_once_empty(self):
        sched = TaskScheduler()
        assert sched.run_once() is None

    def test_pending_count(self):
        sched = TaskScheduler()
        assert sched.pending == 0
        sched.submit(Task(task_id="x", func=lambda: 1))
        assert sched.pending == 1
        sched.run_once()
        assert sched.pending == 0

    def test_run_loop(self):
        sched = TaskScheduler()
        sched.submit(Task(task_id="a", func=lambda: 1))
        sched.submit(Task(task_id="b", func=lambda: 2))
        sched.submit(Task(task_id="c", func=lambda: 3))

        count = sched.run_loop()
        assert count == 3
        assert sched.pending == 0

    def test_run_loop_max_tasks(self):
        sched = TaskScheduler()
        for i in range(5):
            sched.submit(Task(task_id=f"t{i}", func=lambda: i))

        count = sched.run_loop(max_tasks=2)
        assert count == 2
        assert sched.pending == 3


# ============================================================================
# TaskScheduler — Schedule After
# ============================================================================

class TestTaskSchedulerScheduleAfter:
    def test_schedule_after_fires(self):
        sched = TaskScheduler()
        sched.start()
        t = sched.schedule_after(lambda: 42, 0.05)
        time.sleep(0.15)
        sched.stop()
        # Note: schedule_after sets deadline; task must be dequeued manually or via run_loop
        assert t.status == TaskStatus.PENDING  # not auto-executed, just scheduled

    def test_schedule_after_task_attributes(self):
        sched = TaskScheduler()
        t = sched.schedule_after(lambda x: x, 1.5, 10)
        assert t.priority == 1500  # int(delay * 1000)
        assert t.deadline is not None
        assert t.args == (10,)


# ============================================================================
# TaskScheduler — Start / Stop / Stats
# ============================================================================

class TestTaskSchedulerLifecycle:
    def test_start_stop(self):
        sched = TaskScheduler()
        assert sched._running is False
        sched.start()
        assert sched._running is True
        sched.stop()
        assert sched._running is False

    def test_stats(self):
        sched = TaskScheduler()
        sched.submit(Task(task_id="x", func=lambda: 1))
        sched.run_once()

        s = sched.stats
        assert s["scheduled_count"] == 1
        assert s["executed_count"] == 1
        assert s["pending"] == 0

    def test_schedule_at_interval(self):
        results = []

        def put():
            results.append(1)

        sched = TaskScheduler()
        sched.start()
        sched.schedule_at_interval(put, 0.05)
        time.sleep(0.15)
        sched.stop()

        # The interval thread submits tasks to the queue, but they aren't
        # auto-executed without a run_loop. The tasks are queued as PENDING.
        assert sched._scheduled_count >= 2  # at least 2 submissions in 0.15s


# ============================================================================
# WorkerPool
# ============================================================================

class TestWorkerPool:
    def test_creation(self):
        pool = WorkerPool(num_workers=2, max_queue_size=100)
        assert pool._num_workers == 2
        assert pool._running is False
        assert pool.pending == 0

    def test_submit_before_start(self):
        pool = WorkerPool(num_workers=2)
        t = pool.submit(lambda: 42)
        assert t.status == TaskStatus.PENDING
        assert pool.pending == 1

    def test_submit_full_queue(self):
        pool = WorkerPool(num_workers=1, max_queue_size=1)
        pool.submit(lambda: 1)
        with pytest.raises(RuntimeError, match="full"):
            pool.submit(lambda: 2)

    def test_start_stop_workers(self):
        results = []
        pool = WorkerPool(num_workers=2, max_queue_size=10)
        pool.submit(lambda: results.append("a"))
        pool.submit(lambda: results.append("b"))

        pool.start()
        time.sleep(0.15)
        pool.stop()

        assert len(results) == 2
        assert "a" in results
        assert "b" in results

    def test_multiple_tasks_workers(self):
        results = []
        lock = threading.Lock()

        def add(n):
            time.sleep(0.02)
            with lock:
                results.append(n)

        pool = WorkerPool(num_workers=3, max_queue_size=20)
        for i in range(9):
            pool.submit(lambda n=i: add(n))

        pool.start()
        time.sleep(0.3)
        pool.stop()

        assert len(results) == 9

    def test_stop_with_wait(self):
        pool = WorkerPool(num_workers=2, max_queue_size=10)
        pool.submit(lambda: time.sleep(0.05))
        pool.start()
        time.sleep(0.02)
        pool.stop(wait=True)
        assert pool._running is False

    def test_stop_no_wait(self):
        pool = WorkerPool(num_workers=2, max_queue_size=10)
        pool.submit(lambda: time.sleep(0.5))
        pool.start()
        time.sleep(0.02)
        pool.stop(wait=False)
        assert pool._running is False

    def test_stats(self):
        pool = WorkerPool(num_workers=3, max_queue_size=10)
        s = pool.stats
        assert s["workers"] == 3
        assert s["running"] is False
        assert s["size"] == 0

    def test_stats_after_execution(self):
        pool = WorkerPool(num_workers=2, max_queue_size=20)
        for _ in range(5):
            pool.submit(lambda: None)
        pool.start()
        time.sleep(0.15)
        pool.stop()

        s = pool.stats
        assert s["total_dequeued"] == 5

    def test_concurrent_submit(self):
        pool = WorkerPool(num_workers=4, max_queue_size=100)
        pool.start()

        errors = []

        def submitter():
            try:
                for _ in range(10):
                    pool.submit(lambda: time.sleep(0.01))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=submitter) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        pool.stop()
        assert len(errors) == 0
        s = pool.stats
        assert s["total_enqueued"] == 40
