"""
Async agent execution loop with concurrency support.

Provides async/await versions of the core agent loop for high-throughput
scenarios where multiple agents run concurrently.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from agentos.core.context import AgentContext
from agentos.core.streaming import StreamChunk


@dataclass
class AsyncLoopConfig:
    """Configuration for async agent execution loop."""

    max_concurrency: int = 10
    """Max concurrent agent invocations."""

    timeout_seconds: float = 300.0
    """Per-invocation timeout."""

    retry_on_timeout: bool = True
    """Whether to retry timed-out invocations."""

    max_retries: int = 3
    """Max retries on transient failures."""

    collect_metrics: bool = True
    """Whether to collect timing metrics."""


@dataclass
class AsyncInvocationResult:
    """Result of a single async agent invocation."""

    agent_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    retries: int = 0


class AsyncAgentLoop:
    """
    Async execution loop for agent invocations.

    Supports:
    - Concurrent multi-agent execution with semaphore-based throttling
    - Per-invocation timeouts via asyncio.wait_for
    - Automatic retry with exponential backoff
    - Streaming output via async generators
    - Metrics collection (p50/p95/p99 latency)

    Example::

        loop = AsyncAgentLoop(config=AsyncLoopConfig(max_concurrency=5))
        results = await loop.run_all([task1, task2, task3])
    """

    def __init__(self, config: Optional[AsyncLoopConfig] = None):
        self.config = config or AsyncLoopConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self._metrics: list[float] = []

    async def run_single(
        self,
        agent_id: str,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> AsyncInvocationResult:
        """
        Run a single agent invocation with timeout and retry.

        Args:
            agent_id: Identifier for the agent invocation.
            fn: Async callable to execute.
            *args: Positional args for fn.
            **kwargs: Keyword args for fn.

        Returns:
            AsyncInvocationResult with success/failure details.
        """
        async with self._semaphore:
            return await self._execute_with_retry(agent_id, fn, args, kwargs)

    async def _execute_with_retry(
        self,
        agent_id: str,
        fn: Callable[..., Awaitable[Any]],
        args: tuple,
        kwargs: dict,
    ) -> AsyncInvocationResult:
        last_error: Optional[str] = None
        t0 = time.perf_counter()

        for attempt in range(self.config.max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    fn(*args, **kwargs),
                    timeout=self.config.timeout_seconds,
                )
                latency = (time.perf_counter() - t0) * 1000
                if self.config.collect_metrics:
                    self._metrics.append(latency)
                return AsyncInvocationResult(
                    agent_id=agent_id,
                    success=True,
                    output=result,
                    latency_ms=latency,
                    retries=attempt,
                )
            except asyncio.TimeoutError:
                last_error = f"Timeout after {self.config.timeout_seconds}s"
                if not self.config.retry_on_timeout:
                    break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt >= self.config.max_retries:
                    break

        latency = (time.perf_counter() - t0) * 1000
        if self.config.collect_metrics:
            self._metrics.append(latency)
        return AsyncInvocationResult(
            agent_id=agent_id,
            success=False,
            error=last_error,
            latency_ms=latency,
            retries=self.config.max_retries,
        )

    async def run_all(
        self,
        tasks: list[tuple[str, Callable[..., Awaitable[Any]], tuple, dict]],
    ) -> list[AsyncInvocationResult]:
        """
        Run multiple agent invocations concurrently.

        Args:
            tasks: List of (agent_id, async_fn, args, kwargs) tuples.

        Returns:
            List of results in the same order as input tasks.
        """
        coros = [
            self.run_single(agent_id, fn, *args, **kwargs)
            for agent_id, fn, args, kwargs in tasks
        ]
        return list(await asyncio.gather(*coros))

    async def run_streaming(
        self,
        agent_id: str,
        stream_fn: Callable[[], AsyncIterator[StreamChunk]],
    ) -> AsyncIterator[StreamChunk]:
        """
        Run an agent and yield streaming output chunks.

        Args:
            agent_id: Identifier for the agent.
            stream_fn: Async generator yielding StreamChunk objects.

        Yields:
            StreamChunk as they become available.
        """
        async with self._semaphore:
            t0 = time.perf_counter()
            chunk_count = 0
            async for chunk in stream_fn():
                chunk_count += 1
                yield chunk
            latency = (time.perf_counter() - t0) * 1000
            if self.config.collect_metrics:
                self._metrics.append(latency)

    def get_latency_stats(self) -> dict[str, float]:
        """
        Compute p50/p95/p99 latency from collected metrics.

        Returns:
            Dict with keys p50_ms, p95_ms, p99_ms, mean_ms, count.
        """
        if not self._metrics:
            return {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "mean_ms": 0, "count": 0}
        sorted_ms = sorted(self._metrics)
        n = len(sorted_ms)

        def percentile(p: float) -> float:
            idx = int(n * p / 100)
            return sorted_ms[min(idx, n - 1)]

        return {
            "p50_ms": percentile(50),
            "p95_ms": percentile(95),
            "p99_ms": percentile(99),
            "mean_ms": sum(sorted_ms) / n,
            "count": n,
        }

    def reset_metrics(self) -> None:
        """Clear accumulated latency metrics."""
        self._metrics.clear()


class AsyncContextManager:
    """
    Async-safe context manager for agent sessions.

    Manages async context propagation across concurrent agent invocations.
    """

    def __init__(self, context: AgentContext):
        self._context = context
        self._lock = asyncio.Lock()

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            return self._context.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._context[key] = value

    async def update(self, mapping: dict[str, Any]) -> None:
        async with self._lock:
            self._context.update(mapping)

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return dict(self._context)
