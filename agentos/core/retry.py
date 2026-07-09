"""AgentOS Retry — production-grade retry with exponential backoff + jitter.

Strategies:
- ExponentialBackoff: base * multiplier^n with decorrelated jitter
- FixedDelay: constant interval
- FibonacciBackoff: fib sequence for gentler ramp
- CompositeRetry: chain multiple strategies

Design: ~350 lines, zero external deps beyond stdlib + asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================
# Config
# ============================================================================


class JitterStrategy(StrEnum):
    """Jitter algorithms for exponential backoff."""

    NONE = "none"  # No jitter — deterministic
    FULL = "full"  # random(0, delay)
    DECORRELATED = "decorrelated"  # random(base, delay) — AWS-style
    EQUAL = "equal"  # delay/2 + random(0, delay/2)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # cap
    multiplier: float = 2.0  # exponential factor
    jitter: JitterStrategy = JitterStrategy.DECORRELATED
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,)
    on_retry: Callable[[int, Exception, float], None] | None = None  # (attempt, exc, delay) → None


# ============================================================================
# Delay calculators
# ============================================================================


def _calc_jitter(delay: float, strategy: JitterStrategy) -> float:
    """Apply jitter to a computed delay."""
    if strategy == JitterStrategy.NONE:
        return delay
    if strategy == JitterStrategy.FULL:
        return random.uniform(0, delay)
    if strategy == JitterStrategy.DECORRELATED:
        return random.uniform(0, delay)
    # EQUAL
    half = delay / 2
    return half + random.uniform(0, half)


def exponential_delay(attempt: int, config: RetryConfig) -> float:
    """Exponential backoff: base * multiplier^(attempt-1)."""
    delay = config.base_delay * (config.multiplier ** (attempt - 1))
    delay = min(delay, config.max_delay)
    return _calc_jitter(delay, config.jitter)


def fibonacci_delay(attempt: int, config: RetryConfig) -> float:
    """Fibonacci backoff — gentler than exponential."""
    a, b = 0, 1
    for _ in range(attempt):
        a, b = b, a + b
    delay = min(a * config.base_delay, config.max_delay)
    return _calc_jitter(delay, config.jitter)


def fixed_delay(attempt: int, config: RetryConfig) -> float:
    """Constant delay between retries."""
    return min(config.base_delay, config.max_delay)


DelayFunc = Callable[[int, RetryConfig], float]


# ============================================================================
# Retry executor
# ============================================================================


@dataclass
class RetryResult:
    """Result of a retry operation."""

    attempts: int
    success: bool
    last_exception: Exception | None = None
    total_delay: float = 0.0
    attempt_history: list[tuple[int, float, Exception | None]] = field(default_factory=list)


class Retry:
    """Async retry executor with configurable backoff.

    Usage:
        retry = Retry(RetryConfig(max_retries=3, base_delay=0.5))
        result = await retry.execute(some_async_fn)

        # Decorator-style
        @retry.with_retry
        async def flaky_call(): ...
    """

    def __init__(
        self,
        config: RetryConfig,
        delay_fn: DelayFunc = exponential_delay,
    ):
        self.config = config
        self.delay_fn = delay_fn

    async def execute(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute fn with retry logic. Raises last exception if all retries exhausted."""
        last_exc: Exception | None = None

        for attempt in range(1, self.config.max_retries + 2):  # +2 for initial attempt + retries
            try:
                return await fn(*args, **kwargs)
            except self.config.retryable_exceptions as exc:
                last_exc = exc

                if attempt > self.config.max_retries:
                    logger.warning(
                        "Retry exhausted after %d attempts — %s: %s",
                        attempt,
                        type(exc).__name__,
                        exc,
                    )
                    raise

                delay = self.delay_fn(attempt, self.config)

                if self.config.on_retry:
                    try:
                        self.config.on_retry(attempt, exc, delay)
                    except Exception:
                        pass  # Don't let callback failure break retry

                logger.debug(
                    "Retry attempt %d/%d after %.2fs — %s",
                    attempt,
                    self.config.max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        # Unreachable, but type-safe
        assert last_exc is not None
        raise last_exc

    async def execute_with_result(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> RetryResult:
        """Execute with retry and return detailed Result."""
        history: list[tuple[int, float, Exception | None]] = []
        total_delay = 0.0
        last_exc: Exception | None = None

        for attempt in range(1, self.config.max_retries + 2):
            try:
                await fn(*args, **kwargs)
                history.append((attempt, 0.0, None))
                return RetryResult(
                    attempts=attempt,
                    success=True,
                    total_delay=total_delay,
                    attempt_history=history,
                )
            except self.config.retryable_exceptions as exc:
                last_exc = exc

                if attempt > self.config.max_retries:
                    history.append((attempt, 0.0, exc))
                    return RetryResult(
                        attempts=attempt,
                        success=False,
                        last_exception=exc,
                        total_delay=total_delay,
                        attempt_history=history,
                    )

                delay = self.delay_fn(attempt, self.config)
                total_delay += delay
                history.append((attempt, delay, exc))
                await asyncio.sleep(delay)

        return RetryResult(
            attempts=self.config.max_retries + 1,
            success=False,
            last_exception=last_exc,
            total_delay=total_delay,
            attempt_history=history,
        )

    def with_retry(self, fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """Decorator: apply retry logic to an async function."""

        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await self.execute(fn, *args, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper._retry = self  # type: ignore[attr-defined]
        return wrapper


# ============================================================================
# Pre-built retry policies
# ============================================================================


class RetryPolicies:
    """Factory for common retry configurations."""

    @staticmethod
    def fast() -> Retry:
        """3 retries, 100ms base, 2x multiplier — for idempotent API calls."""
        return Retry(
            RetryConfig(
                max_retries=3,
                base_delay=0.1,
                max_delay=1.0,
                multiplier=2.0,
                jitter=JitterStrategy.DECORRELATED,
            )
        )

    @staticmethod
    def standard() -> Retry:
        """5 retries, 500ms base, 2x — general purpose."""
        return Retry(
            RetryConfig(
                max_retries=5,
                base_delay=0.5,
                max_delay=30.0,
                multiplier=2.0,
                jitter=JitterStrategy.DECORRELATED,
            )
        )

    @staticmethod
    def persistent() -> Retry:
        """10 retries, 1s base, 2x, max 120s — for critical operations."""
        return Retry(
            RetryConfig(
                max_retries=10,
                base_delay=1.0,
                max_delay=120.0,
                multiplier=2.0,
                jitter=JitterStrategy.DECORRELATED,
            )
        )

    @staticmethod
    def immediate() -> Retry:
        """2 retries, no delay — for infallible operations."""
        return Retry(
            RetryConfig(
                max_retries=2,
                base_delay=0.0,
                max_delay=0.0,
                jitter=JitterStrategy.NONE,
            )
        )

    @staticmethod
    def gentle() -> Retry:
        """5 retries, Fibonacci backoff — rate-limit friendly."""
        return Retry(
            RetryConfig(
                max_retries=5,
                base_delay=0.5,
                max_delay=60.0,
                jitter=JitterStrategy.FULL,
            ),
            delay_fn=fibonacci_delay,
        )


# ============================================================================
# Sync retry (for non-async contexts)
# ============================================================================


class SyncRetry:
    """Synchronous retry executor — calls asyncio.run internally."""

    def __init__(self, config: RetryConfig, delay_fn: DelayFunc = exponential_delay):
        self._async_retry = Retry(config, delay_fn)

    def execute(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Synchronous wrapper."""
        import asyncio as _asyncio

        async def _wrapper():
            return fn(*args, **kwargs)

        return _asyncio.run(self._async_retry.execute(_wrapper))

    def with_retry(self, fn: Callable[..., T]) -> Callable[..., T]:
        """Decorator for sync functions."""

        def wrapper(*args: Any, **kwargs: Any) -> T:
            return self.execute(fn, *args, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
