"""
Lightweight Task Scheduler & Job Queue for AgentOS.

PriorityTaskQueue — bounded priority queue with deadline-aware scheduling.
TaskScheduler — interval/delay/cron-like scheduling with persistence hooks.
WorkerPool — simple thread-pool backed by the task queue.
"""

import heapq
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple


# ============================================================================
# Task & Result Types
# ============================================================================

class TaskStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    EXPIRED = auto()
    CANCELLED = auto()


@dataclass(order=True)
class _PrioritizedTask:
    """Internal heap item. Lower priority value = higher urgency."""
    priority: int
    deadline: float
    seq: int  # tiebreaker for stable ordering
    task: "Task" = field(compare=False)


@dataclass
class Task:
    """A schedulable task with metadata."""
    task_id: str
    func: Callable
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    deadline: Optional[float] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    def run(self):
        self.started_at = time.monotonic()
        self.status = TaskStatus.RUNNING
        try:
            self.result = self.func(*self.args, **self.kwargs)
            self.status = TaskStatus.COMPLETED
        except Exception as e:
            self.error = str(e)
            self.status = TaskStatus.FAILED
        finally:
            self.completed_at = time.monotonic()

    @property
    def elapsed(self) -> Optional[float]:
        if self.started_at is None:
            return None
        return (self.completed_at or time.monotonic()) - self.started_at


# ============================================================================
# PriorityTaskQueue
# ============================================================================

class PriorityTaskQueue:
    """Thread-safe bounded priority queue for tasks.

    Lower priority value = executed first. Deadlines auto-expire stale tasks.
    """

    def __init__(self, max_size: int = 1000):
        self._max_size = max_size
        self._heap: List[_PrioritizedTask] = []
        self._lookup: Dict[str, _PrioritizedTask] = {}
        self._lock = threading.RLock()
        self._seq: int = 0
        self._total_enqueued: int = 0
        self._total_dequeued: int = 0
        self._total_expired: int = 0

    def enqueue(self, task: Task) -> bool:
        with self._lock:
            if len(self._heap) >= self._max_size:
                return False
            self._seq += 1
            pt = _PrioritizedTask(
                priority=task.priority,
                deadline=task.deadline or float('inf'),
                seq=self._seq,
                task=task,
            )
            heapq.heappush(self._heap, pt)
            self._lookup[task.task_id] = pt
            self._total_enqueued += 1
            return True

    def dequeue(self) -> Optional[Task]:
        with self._lock:
            self._clean_expired()
            while self._heap:
                pt = heapq.heappop(self._heap)
                task = pt.task
                if task.status == TaskStatus.CANCELLED:
                    self._lookup.pop(task.task_id, None)
                    continue
                if task.deadline and time.monotonic() > task.deadline:
                    task.status = TaskStatus.EXPIRED
                    self._lookup.pop(task.task_id, None)
                    self._total_expired += 1
                    continue
                self._lookup.pop(task.task_id, None)
                self._total_dequeued += 1
                return task
            return None

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            pt = self._lookup.pop(task_id, None)
            if pt:
                pt.task.status = TaskStatus.CANCELLED
                return True
            return False

    def _clean_expired(self):
        """Remove cancelled tasks from heap top."""
        now = time.monotonic()
        while self._heap:
            pt = self._heap[0]
            if pt.task.status == TaskStatus.CANCELLED:
                heapq.heappop(self._heap)
                self._lookup.pop(pt.task.task_id, None)
            elif pt.deadline != float('inf') and now > pt.deadline:
                pt.task.status = TaskStatus.EXPIRED
                heapq.heappop(self._heap)
                self._lookup.pop(pt.task.task_id, None)
                self._total_expired += 1
            else:
                break

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._heap)

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._heap),
                "max_size": self._max_size,
                "total_enqueued": self._total_enqueued,
                "total_dequeued": self._total_dequeued,
                "total_expired": self._total_expired,
            }


# ============================================================================
# TaskScheduler
# ============================================================================

class TaskScheduler:
    """Schedule tasks at intervals or after delays. Runs in a background thread."""

    def __init__(self):
        self._queue = PriorityTaskQueue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._scheduled_count: int = 0
        self._executed_count: int = 0

    def submit(self, task: Task) -> bool:
        """Submit a task for immediate execution."""
        ok = self._queue.enqueue(task)
        if ok:
            self._scheduled_count += 1
        return ok

    def schedule_after(self, func: Callable, delay: float, *args, **kwargs) -> Task:
        """Schedule a task to run after delay seconds."""
        task = Task(
            task_id=str(uuid.uuid4()),
            func=func,
            args=args,
            kwargs=kwargs,
            deadline=time.monotonic() + delay,
            priority=int(delay * 1000),  # sooner = lower priority
        )
        self.submit(task)
        return task

    def schedule_at_interval(
        self, func: Callable, interval: float, *args, **kwargs
    ) -> None:
        """Repeatedly schedule a task at fixed intervals. Uses a daemon thread."""

        def _loop():
            while self._running:
                t = Task(
                    task_id=str(uuid.uuid4()),
                    func=func,
                    args=args,
                    kwargs=kwargs,
                )
                self.submit(t)
                self._executed_count += 1
                time.sleep(interval)

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run_once(self) -> Optional[Task]:
        """Pull and run one task. Returns the executed task or None."""
        task = self._queue.dequeue()
        if task:
            task.run()
            self._executed_count += 1
            return task
        return None

    def run_loop(self, max_tasks: int = 0) -> int:
        """Run tasks until queue empty or max_tasks reached. Returns count executed."""
        count = 0
        self._running = True
        while self._running:
            task = self._queue.dequeue()
            if task is None:
                break
            task.run()
            count += 1
            if 0 < max_tasks <= count:
                break
        self._running = False
        self._executed_count += count
        return count

    @property
    def pending(self) -> int:
        return self._queue.size

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            **self._queue.stats,
            "scheduled_count": self._scheduled_count,
            "executed_count": self._executed_count,
            "pending": self.pending,
        }


# ============================================================================
# WorkerPool
# ============================================================================

class WorkerPool:
    """Simple thread pool pulling from a PriorityTaskQueue."""

    def __init__(self, num_workers: int = 4, max_queue_size: int = 1000):
        self._num_workers = num_workers
        self._queue = PriorityTaskQueue(max_size=max_queue_size)
        self._running = False
        self._workers: List[threading.Thread] = []
        self._lock = threading.Lock()

    def submit(self, func: Callable, *args, **kwargs) -> Task:
        task = Task(
            task_id=str(uuid.uuid4()),
            func=func,
            args=args,
            kwargs=kwargs,
        )
        ok = self._queue.enqueue(task)
        if not ok:
            raise RuntimeError("WorkerPool queue is full")
        return task

    def start(self) -> None:
        self._running = True
        for _ in range(self._num_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True)
            t.start()
            self._workers.append(t)

    def stop(self, wait: bool = True) -> None:
        self._running = False
        if wait:
            for t in self._workers:
                t.join(timeout=5.0)

    def _worker_loop(self) -> None:
        while self._running:
            task = self._queue.dequeue()
            if task is None:
                time.sleep(0.01)
                continue
            task.run()

    @property
    def pending(self) -> int:
        return self._queue.size

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            **self._queue.stats,
            "workers": self._num_workers,
            "running": self._running,
        }
