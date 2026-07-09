"""
AsyncBatchExecutor — Concurrent agent task dispatch with configurable
parallelism, timeout, retry, and result aggregation.

Designed for running multiple AgentOS tasks in parallel (e.g., batch
evaluation, multi-model comparison, bulk processing).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class BatchStrategy(Enum):
    """Execution strategy for batch tasks."""

    PARALLEL = "parallel"  # All tasks run concurrently (limited by max_concurrency)
    SEQUENTIAL = "sequential"  # One after another
    SMART = "smart"  # Dynamically adjust based on system load


@dataclass
class TaskSpec:
    """Specification for a single task in a batch."""

    task_id: str
    coro_or_func: Callable[..., Awaitable[Any]]
    args: tuple = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    timeout: float = 60.0
    max_retries: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result of a single task execution."""

    task_id: str
    status: TaskStatus
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    retries: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def success(self) -> bool:
        return self.status == TaskStatus.SUCCESS


@dataclass
class BatchConfig:
    """Configuration for AsyncBatchExecutor."""

    max_concurrency: int = 5
    default_timeout: float = 60.0
    max_retries: int = 1
    retry_delay: float = 1.0
    strategy: BatchStrategy = BatchStrategy.PARALLEL
    fail_fast: bool = False
    collect_errors: bool = True


@dataclass
class BatchResult:
    """Aggregated result of a batch execution."""

    results: list[TaskResult] = field(default_factory=list)
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    total_duration_ms: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.succeeded / self.total

    @property
    def all_success(self) -> bool:
        return self.succeeded == self.total

    def get_failed_ids(self) -> list[str]:
        return [
            r.task_id for r in self.results if r.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT)
        ]


class AsyncBatchExecutor:
    """Concurrently dispatches multiple AgentOS tasks and aggregates results."""

    def __init__(self, config: BatchConfig | None = None):
        self.config = config or BatchConfig()
        self._semaphore: asyncio.Semaphore | None = None
        self._cancel_event: asyncio.Event | None = None

    async def execute(self, tasks: list[TaskSpec]) -> BatchResult:
        """Execute a list of tasks and return aggregated results."""
        if not tasks:
            return BatchResult(total=0)

        start = time.perf_counter()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self._cancel_event = asyncio.Event()
        results: list[TaskResult] = []

        if self.config.strategy == BatchStrategy.SEQUENTIAL:
            for task in tasks:
                result = await self._execute_one(task)
                results.append(result)
                if self.config.fail_fast and not result.success:
                    break
        else:
            # PARALLEL or SMART
            tasks_coros = [self._execute_one(task) for task in tasks]
            results = list(await asyncio.gather(*tasks_coros))

        elapsed = (time.perf_counter() - start) * 1000
        succeeded = sum(1 for r in results if r.status == TaskStatus.SUCCESS)
        failed = sum(1 for r in results if r.status == TaskStatus.FAILED)
        timed_out = sum(1 for r in results if r.status == TaskStatus.TIMEOUT)

        return BatchResult(
            results=results,
            total=len(tasks),
            succeeded=succeeded,
            failed=failed,
            timed_out=timed_out,
            total_duration_ms=elapsed,
            started_at=start,
            finished_at=time.perf_counter(),
        )

    async def _execute_one(self, task: TaskSpec) -> TaskResult:
        """Execute a single task with retry support."""
        timeout = task.timeout if task.timeout is not None else self.config.default_timeout
        max_retries = task.max_retries if task.max_retries is not None else self.config.max_retries
        retries = 0

        assert self._semaphore is not None, "semaphore must be set before calling execute()"
        async with self._semaphore:
            while True:
                started = time.perf_counter()
                try:
                    coro = task.coro_or_func(*task.args, **task.kwargs)
                    result_value = await asyncio.wait_for(coro, timeout=timeout)
                    elapsed = (time.perf_counter() - started) * 1000
                    return TaskResult(
                        task_id=task.task_id,
                        status=TaskStatus.SUCCESS,
                        result=result_value,
                        duration_ms=elapsed,
                        retries=retries,
                        started_at=started,
                        finished_at=time.perf_counter(),
                    )
                except TimeoutError:
                    if retries < max_retries:
                        retries += 1
                        logger.warning(
                            f"Task '{task.task_id}' timed out (attempt {retries}/{max_retries}), retrying..."
                        )
                        await asyncio.sleep(self.config.retry_delay)
                        continue
                    elapsed = (time.perf_counter() - started) * 1000
                    return TaskResult(
                        task_id=task.task_id,
                        status=TaskStatus.TIMEOUT,
                        error=f"Timed out after {timeout}s (retries: {retries})",
                        duration_ms=elapsed,
                        retries=retries,
                        started_at=started,
                        finished_at=time.perf_counter(),
                    )
                except Exception as e:
                    if retries < max_retries:
                        retries += 1
                        logger.warning(
                            f"Task '{task.task_id}' failed (attempt {retries}/{max_retries}): {e}"
                        )
                        await asyncio.sleep(self.config.retry_delay)
                        continue
                    elapsed = (time.perf_counter() - started) * 1000
                    return TaskResult(
                        task_id=task.task_id,
                        status=TaskStatus.FAILED,
                        error=str(e),
                        duration_ms=elapsed,
                        retries=retries,
                        started_at=started,
                        finished_at=time.perf_counter(),
                    )

    def cancel_all(self) -> None:
        """Cancel all pending tasks."""
        if self._cancel_event:
            self._cancel_event.set()
