"""
AgentOS v0.40 Task Queue — 异步任务调度与重试。
支持：内存队列（开发）/ Redis队列（生产）、优先级、重试、死信队列。
"""

from __future__ import annotations

import asyncio
import heapq
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any


class TaskState(StrEnum):
    """任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    DEAD = "dead"  # 死信


class TaskPriority(int, Enum):
    """任务优先级枚举。"""

    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


@dataclass(order=True)
class QueuedTask:
    """带优先级的任务节点（priority取负以实现最大堆）。"""

    priority: int  # -priority for max-heap
    created_at: float = field(compare=False)
    task: ScheduledTask = field(compare=False)


@dataclass
class ScheduledTask:
    """调度任务。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    payload: dict = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.PENDING
    max_retries: int = 3
    retry_delay: float = 1.0  # 秒
    timeout: float = 60.0
    callback: Callable | None = field(default=None, repr=False)
    result: Any = None
    error: str = ""
    retry_count: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float = 0
    completed_at: float = 0
    _tags: dict = field(default_factory=dict)


class MemoryQueue:
    """基于堆内存的任务队列 — 开发环境默认。"""

    def __init__(self, max_size: int = 10000):
        self._heap: list[QueuedTask] = []
        self._pending: dict[str, ScheduledTask] = {}
        self._dead: list[ScheduledTask] = []
        self.max_size = max_size
        self._lock = asyncio.Lock()

    async def enqueue(self, task: ScheduledTask) -> str:
        async with self._lock:
            if len(self._pending) >= self.max_size:
                raise RuntimeError(f"Queue full ({self.max_size})")
            self._pending[task.id] = task
            heapq.heappush(
                self._heap,
                QueuedTask(priority=-task.priority.value, created_at=task.created_at, task=task),
            )
            return task.id

    async def dequeue(self) -> ScheduledTask | None:
        async with self._lock:
            while self._heap:
                qt = heapq.heappop(self._heap)
                task = self._pending.pop(qt.task.id, None)
                if task and task.state == TaskState.PENDING:
                    return task
            return None

    async def peek(self) -> ScheduledTask | None:
        async with self._lock:
            if self._heap:
                return self._heap[0].task
            return None

    def pending_count(self) -> int:
        return len(self._heap)

    def dead_count(self) -> int:
        return len(self._dead)

    async def move_to_dead(self, task: ScheduledTask):
        async with self._lock:
            task.state = TaskState.DEAD
            self._dead.append(task)
            self._pending.pop(task.id, None)

    def stats(self) -> dict:
        return {"pending": len(self._heap), "dead": len(self._dead), "max_size": self.max_size}


class TaskQueue:
    """任务队列管理器。"""

    def __init__(self, queue: MemoryQueue | None = None, concurrency: int = 4):
        self._queue = queue or MemoryQueue()
        self._concurrency = concurrency
        self._running: set[str] = set()
        self._callbacks: dict[str, Callable] = {}
        self._semaphore = asyncio.Semaphore(concurrency)
        self._running_flag = False

    def register_callback(self, task_name: str, handler: Callable):
        """注册任务处理器。"""
        self._callbacks[task_name] = handler

    async def submit(self, task: ScheduledTask) -> str:
        if task.name not in self._callbacks:
            raise ValueError(f"No handler registered for task: {task.name}")
        task_id = await self._queue.enqueue(task)
        return task_id

    async def start(self):
        """启动Worker循环。"""
        self._running_flag = True
        while self._running_flag:
            task = await self._queue.dequeue()
            if not task:
                await asyncio.sleep(0.1)
                continue
            asyncio.create_task(self._execute(task))

    def stop(self):
        self._running_flag = False

    async def _execute(self, task: ScheduledTask):
        async with self._semaphore:
            self._running.add(task.id)
            task.state = TaskState.RUNNING
            task.started_at = time.time()

            handler = self._callbacks.get(task.name)
            if not handler:
                task.state = TaskState.FAILED
                task.error = f"No handler: {task.name}"
                self._running.discard(task.id)
                return

            try:
                result = handler(task.payload)
                if asyncio.iscoroutine(result):
                    result = await asyncio.wait_for(result, timeout=task.timeout)
                task.result = result
                task.state = TaskState.SUCCESS
            except TimeoutError:
                task.error = f"Timeout after {task.timeout}s"
                await self._handle_failure(task)
            except Exception as e:
                task.error = str(e)
                await self._handle_failure(task)
            finally:
                task.completed_at = time.time()
                self._running.discard(task.id)

    async def _handle_failure(self, task: ScheduledTask):
        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.state = TaskState.RETRYING
            await asyncio.sleep(task.retry_delay * (2 ** (task.retry_count - 1)))  # 指数退避
            task.state = TaskState.PENDING
            task.priority = TaskPriority(task.priority.value + 10)  # 提升优先级
            await self._queue.enqueue(task)
        else:
            task.state = TaskState.FAILED
            await self._queue.move_to_dead(task)

    def cancel(self, task_id: str):
        """取消任务。"""
        task = self._queue._pending.get(task_id)
        if task and task.state in (TaskState.PENDING, TaskState.RETRYING):
            task.state = TaskState.CANCELLED

    def stats(self) -> dict:
        return {
            "running": len(self._running),
            "concurrency": self._concurrency,
            "queue": self._queue.stats(),
            "handlers": list(self._callbacks.keys()),
        }
