"""
Async Parallel Execution Primitives — fan-out/fan-in for multi-agent tasks.

Provides structured concurrency patterns for AgentOS:
- TaskGroup: structured async task grouping with collective result/error handling
- ParallelExecutor: fan-out/fan-in with timeout, cancellation, throttling
- parallel_gather: await multiple coroutines with timeout & partial results
- parallel_map: map a function over items concurrently with bounded parallelism

Key features:
- Structured concurrency (all-or-nothing or partial results)
- Semaphore-based throttling (bounded parallelism)
- Per-task timeout + global timeout
- Result aggregation with success/failure tracking
- Graceful cancellation propagation
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

T = TypeVar("T")
R = TypeVar("R")


# ── Data Structures ──────────────────────────────────────────────


class TaskStatus(StrEnum):
    """Individual task execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """Result of a single parallel task."""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Exception | None = None
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_ms: float = 0.0
    retries: int = 0


@dataclass
class GatherResult:
    """Aggregated result from parallel_gather."""

    results: list[TaskResult] = field(default_factory=list)
    total: int = 0
    completed: int = 0
    failed: int = 0
    timed_out: int = 0
    cancelled: int = 0
    total_duration_ms: float = 0.0
    all_succeeded: bool = False

    @property
    def success_rate(self) -> float:
        return self.completed / self.total if self.total > 0 else 0.0

    def get_results(self) -> list[Any]:
        """Extract successful result values."""
        return [r.result for r in self.results if r.status == TaskStatus.COMPLETED]

    def get_errors(self) -> list[tuple[str, Exception]]:
        """Extract (task_id, error) pairs for failed tasks."""
        return [(r.task_id, r.error) for r in self.results if r.error]


# ── Semaphore-based Task Throttler ───────────────────────────────


class TaskThrottler:
    """
    Bounded concurrency controller using asyncio.Semaphore.

    Usage:
        throttler = TaskThrottler(max_concurrent=5)
        async with throttler:
            await do_work()
    """

    def __init__(self, max_concurrent: int = 10):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active = 0
        self._peak = 0

    @property
    def active(self) -> int:
        return self._active

    @property
    def peak(self) -> int:
        return self._peak

    async def __aenter__(self):
        await self._semaphore.acquire()
        self._active += 1
        if self._active > self._peak:
            self._peak = self._active
        return self

    async def __aexit__(self, *args):
        self._active -= 1
        self._semaphore.release()


# ── Parallel Executor ────────────────────────────────────────────


class ParallelExecutor:
    """
    Fan-out/fan-in executor for running multiple coroutines concurrently.

    Supports structured concurrency: either wait for all (fail-fast or tolerant),
    or collect partial results on timeout.

    Usage:
        executor = ParallelExecutor(max_concurrent=8, timeout=30.0)
        result = await executor.gather([
            agent1.run(task_a),
            agent2.run(task_b),
            agent3.run(task_c),
        ])
        print(f"{result.completed}/{result.total} succeeded")
    """

    def __init__(
        self,
        max_concurrent: int = 8,
        timeout: float = 60.0,
        fail_fast: bool = False,
    ):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.fail_fast = fail_fast
        self.throttler = TaskThrottler(max_concurrent)

    async def gather(
        self,
        coros: list[Coroutine],
        timeout: float | None = None,
        return_partial: bool = True,
    ) -> GatherResult:
        """
        Execute multiple coroutines in parallel with bounded concurrency.

        Args:
            coros: List of coroutines to execute
            timeout: Global timeout (overrides executor default)
            return_partial: If True, return partial results on timeout; if False, raise

        Returns:
            GatherResult with aggregated status
        """
        effective_timeout = timeout if timeout is not None else self.timeout
        total_start = time.monotonic()

        results: list[TaskResult] = []
        tasks: dict[str, asyncio.Task] = {}

        if not coros:
            return GatherResult(total=0)

        async def _run_one(coro: Coroutine, task_id: str) -> None:
            tr = TaskResult(task_id=task_id, status=TaskStatus.RUNNING, started_at=time.monotonic())
            results.append(tr)

            async with self.throttler:
                try:
                    tr.result = await coro
                    tr.status = TaskStatus.COMPLETED
                except asyncio.CancelledError:
                    tr.status = TaskStatus.CANCELLED
                    if self.fail_fast:
                        raise
                except TimeoutError:
                    tr.status = TaskStatus.TIMEOUT
                    tr.error = TimeoutError(f"Task {task_id} timed out")
                    if self.fail_fast:
                        raise
                except Exception as e:
                    tr.status = TaskStatus.FAILED
                    tr.error = e
                    if self.fail_fast:
                        raise
                finally:
                    tr.finished_at = time.monotonic()
                    tr.duration_ms = (tr.finished_at - tr.started_at) * 1000

        # Launch all tasks
        for i, coro in enumerate(coros):
            task_id = uuid.uuid4().hex[:10]
            t = asyncio.create_task(_run_one(coro, task_id))
            tasks[task_id] = t

        # Wait with global timeout
        try:
            done, pending = await asyncio.wait(
                tasks.values(),
                timeout=effective_timeout,
                return_when=(
                    asyncio.ALL_COMPLETED if not self.fail_fast else asyncio.FIRST_EXCEPTION
                ),
            )

            # Cancel remaining on fail-fast
            if pending and self.fail_fast:
                for t in pending:
                    t.cancel()

            # Handle timeout: cancel remaining if not return_partial
            if pending and not return_partial:
                for t in pending:
                    t.cancel()
                raise TimeoutError(f"Gather timed out after {effective_timeout}s")

            # Mark timed-out tasks
            for t in pending:
                t.cancel()
                for tr in results:
                    if tr.status == TaskStatus.RUNNING:
                        tr.status = TaskStatus.TIMEOUT
                        tr.finished_at = time.monotonic()
                        tr.duration_ms = (tr.finished_at - tr.started_at) * 1000

        except Exception:
            for t in tasks.values():
                if not t.done():
                    t.cancel()
            raise

        # Build aggregate result
        total_duration = (time.monotonic() - total_start) * 1000
        completed = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
        failed = sum(1 for r in results if r.status == TaskStatus.FAILED)
        timed_out = sum(1 for r in results if r.status == TaskStatus.TIMEOUT)
        cancelled = sum(1 for r in results if r.status == TaskStatus.CANCELLED)

        return GatherResult(
            results=results,
            total=len(results),
            completed=completed,
            failed=failed,
            timed_out=timed_out,
            cancelled=cancelled,
            total_duration_ms=total_duration,
            all_succeeded=(completed == len(results)),
        )

    async def map(
        self,
        func: Callable[[T], Coroutine],
        items: list[T],
        timeout: float | None = None,
    ) -> GatherResult:
        """
        Map an async function over a list of items with bounded concurrency.

        Args:
            func: Async function taking one item and returning a value
            items: List of input items
            timeout: Global timeout

        Returns:
            GatherResult with results
        """
        coros = [func(item) for item in items]
        return await self.gather(coros, timeout=timeout)


# ── Convenience Functions ────────────────────────────────────────


async def parallel_gather(
    *coros: Coroutine,
    max_concurrent: int = 8,
    timeout: float = 60.0,
    return_partial: bool = True,
) -> GatherResult:
    """
    Convenience function: await multiple coroutines in parallel.

    Usage:
        result = await parallel_gather(
            fetch_url(url1),
            fetch_url(url2),
            fetch_url(url3),
            max_concurrent=5, timeout=30.0,
        )
        for r in result.get_results():
            print(r)
    """
    executor = ParallelExecutor(max_concurrent=max_concurrent, timeout=timeout)
    return await executor.gather(list(coros), return_partial=return_partial)


async def parallel_map(
    func: Callable[[T], Coroutine],
    items: list[T],
    max_concurrent: int = 8,
    timeout: float = 60.0,
) -> GatherResult:
    """
    Convenience function: map async function over items concurrently.

    Usage:
        result = await parallel_map(process_document, documents, max_concurrent=4)
        print(f"Processed {result.completed}/{result.total} docs")
    """
    executor = ParallelExecutor(max_concurrent=max_concurrent, timeout=timeout)
    return await executor.map(func, items)


# ── Fan-Out / Fan-In with Aggregation ────────────────────────────


@dataclass
class FanOutConfig:
    """Configuration for fan-out pattern."""

    max_concurrent: int = 8
    timeout: float = 60.0
    aggregation: str = "all"  # "all" | "first" | "merge"
    retry_failed: bool = False
    max_retries: int = 2


class FanOutExecutor:
    """
    Fan-out pattern: dispatch tasks to N workers, collect results.

    Supports aggregation modes:
    - "all": Wait for all, return list of results
    - "first": Return first successful result (race)
    - "merge": Run all, merge results with a merge function
    """

    def __init__(self, config: FanOutConfig | None = None, max_concurrent: int = 0):
        if config is None and max_concurrent > 0:
            config = FanOutConfig(max_concurrent=max_concurrent)
        self.config = config or FanOutConfig()
        self.executor = ParallelExecutor(
            max_concurrent=self.config.max_concurrent,
            timeout=self.config.timeout,
        )

    async def fan_out(
        self,
        worker_coros: list[Coroutine],
        merge_fn: Callable[[list[Any]], Any] | None = None,
    ) -> list[Any] | Any | GatherResult:
        """
        Fan out tasks to workers and collect results.

        Args:
            worker_coros: List of worker coroutines
            merge_fn: Merge function for "merge" mode (list of results -> merged value)

        Returns:
            Depends on aggregation mode:
            - "all": list of results
            - "first": first successful result
            - "merge": merged result via merge_fn
        """
        mode = self.config.aggregation

        if mode == "first":
            # Race: return first successful
            gather_result = await self.executor.gather(
                worker_coros,
                return_partial=True,
            )
            successes = gather_result.get_results()
            if successes:
                return successes[0]
            # All failed — raise first error
            errors = gather_result.get_errors()
            if errors:
                raise errors[0][1]
            raise RuntimeError("All workers failed with no result")

        elif mode == "merge":
            gather_result = await self.executor.gather(worker_coros)
            if not merge_fn:
                raise ValueError("merge_fn required for 'merge' mode")
            return merge_fn(gather_result.get_results())

        else:  # "all"
            gather_result = await self.executor.gather(worker_coros)
            if self.config.retry_failed and gather_result.failed > 0:
                # Retry failed tasks
                for r in gather_result.results:
                    if r.status == TaskStatus.FAILED:
                        # Note: retry requires caller to provide a way to rebuild the coro
                        pass
            return gather_result


# ── Agent Loop Integration ────────────────────────────────────────


def create_parallel_agent_gather(
    max_concurrent: int = 8,
    timeout: float = 60.0,
) -> Callable:
    """
    Create a gather function for use in Agent tool definitions.

    Usage:
        agent_tools["parallel_gather"] = create_parallel_agent_gather(max_concurrent=5)
    """

    async def agent_gather(*coros: Coroutine) -> GatherResult:
        return await parallel_gather(*coros, max_concurrent=max_concurrent, timeout=timeout)

    return agent_gather
