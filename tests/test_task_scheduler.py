"""Tests for agentos.tools.task_scheduler."""

import time

from agentos.tools.task_scheduler import (
    PriorityTaskQueue,
    Task,
    TaskScheduler,
    TaskStatus,
    WorkerPool,
)

# ============================================================================
# Task Tests
# ============================================================================

class TestTask:
    def test_run_success(self):
        t = Task(
            task_id="t1",
            func=lambda x: x * 2,
            args=(21,),
        )
        t.run()
        assert t.status == TaskStatus.COMPLETED
        assert t.result == 42
        assert t.elapsed is not None

    def test_run_failure(self):
        def boom():
            raise ValueError("kaboom")
        t = Task(task_id="t2", func=boom)
        t.run()
        assert t.status == TaskStatus.FAILED
        assert "kaboom" in t.error

    def test_run_kwargs(self):
        t = Task(task_id="t3", func=lambda a, b=0: a + b, args=(3,), kwargs={"b": 4})
        t.run()
        assert t.result == 7


# ============================================================================
# PriorityTaskQueue Tests
# ============================================================================

class TestPriorityTaskQueue:
    def test_enqueue_dequeue(self):
        q = PriorityTaskQueue(max_size=10)
        t = Task("1", lambda: 42)
        assert q.enqueue(t) is True
        assert q.size == 1
        out = q.dequeue()
        assert out is t

    def test_priority_ordering(self):
        q = PriorityTaskQueue()
        t_low = Task("low", lambda: "low", priority=10)
        t_high = Task("high", lambda: "high", priority=1)
        t_mid = Task("mid", lambda: "mid", priority=5)
        q.enqueue(t_low)
        q.enqueue(t_high)
        q.enqueue(t_mid)
        assert q.dequeue().task_id == "high"
        assert q.dequeue().task_id == "mid"
        assert q.dequeue().task_id == "low"

    def test_max_size(self):
        q = PriorityTaskQueue(max_size=2)
        assert q.enqueue(Task("1", lambda: 1))
        assert q.enqueue(Task("2", lambda: 2))
        assert not q.enqueue(Task("3", lambda: 3))

    def test_cancel(self):
        q = PriorityTaskQueue()
        q.enqueue(Task("cancel_me", lambda: 1))
        assert q.cancel("cancel_me") is True
        assert q.dequeue() is None

    def test_cancel_nonexistent(self):
        q = PriorityTaskQueue()
        assert q.cancel("ghost") is False

    def test_deadline_expired(self):
        q = PriorityTaskQueue()
        t = Task("soon", lambda: 1, deadline=time.monotonic() - 10)
        q.enqueue(t)
        out = q.dequeue()
        assert out is None
        assert t.status == TaskStatus.EXPIRED

    def test_stats(self):
        q = PriorityTaskQueue(max_size=5)
        q.enqueue(Task("a", lambda: 1))
        q.enqueue(Task("b", lambda: 2))
        s = q.stats
        assert s["size"] == 2
        assert s["max_size"] == 5
        assert s["total_enqueued"] == 2


# ============================================================================
# TaskScheduler Tests
# ============================================================================

class TestTaskScheduler:
    def test_submit_and_run(self):
        s = TaskScheduler()
        results = []
        s.submit(Task("t1", lambda: results.append(1)))
        s.submit(Task("t2", lambda: results.append(2)))
        s.run_loop()
        assert results == [1, 2]

    def test_schedule_after(self):
        s = TaskScheduler()
        task = s.schedule_after(lambda: None, delay=0.01)
        assert s.pending == 1
        assert task.deadline is not None

    def test_run_once_empty(self):
        s = TaskScheduler()
        result = s.run_once()
        assert result is None

    def test_run_loop_max_tasks(self):
        s = TaskScheduler()
        for i in range(5):
            s.submit(Task(str(i), lambda x: x, args=(i,)))
        count = s.run_loop(max_tasks=3)
        assert count == 3
        assert s.pending == 2

    def test_stats(self):
        s = TaskScheduler()
        s.submit(Task("x", lambda: 1))
        d = s.stats
        assert d["pending"] == 1


# ============================================================================
# WorkerPool Tests
# ============================================================================

class TestWorkerPool:
    def test_submit_and_wait(self):
        pool = WorkerPool(num_workers=2)
        results = []

        def append(v):
            results.append(v)

        pool.submit(append, 1)
        pool.submit(append, 2)
        pool.start()
        time.sleep(0.1)
        pool.stop()
        assert sorted(results) == [1, 2]

    def test_pending_count(self):
        pool = WorkerPool(num_workers=1, max_queue_size=10)
        for i in range(5):
            pool.submit(lambda x: x, i)
        assert pool.pending == 5

    def test_stats(self):
        pool = WorkerPool(num_workers=3, max_queue_size=50)
        pool.submit(lambda: 1)
        s = pool.stats
        assert s["workers"] == 3
        assert s["size"] == 1
        assert s["max_size"] == 50

    def test_multiple_workers(self):
        pool = WorkerPool(num_workers=4)
        import threading
        seen_threads = set()
        lock = threading.Lock()

        def record():
            with lock:
                seen_threads.add(threading.current_thread().ident)
            time.sleep(0.01)  # give other workers a chance

        for _ in range(8):
            pool.submit(record)
        pool.start()
        time.sleep(0.3)
        pool.stop()
        assert len(seen_threads) >= 2
