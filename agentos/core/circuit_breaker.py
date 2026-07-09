"""AgentOS Circuit Breaker — protect against cascading failures.

Production-grade circuit breaker pattern with:
- 3 states: CLOSED → OPEN → HALF_OPEN → CLOSED
- Configurable failure threshold, timeout, and half-open probe limit
- Per-endpoint isolation with shared registry
- Optional fallback function support
- Thread-safe, asyncio-native

Design: ~280 lines, zero external deps beyond stdlib + asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================
# State machine
# ============================================================================


class CircuitState(StrEnum):
    CLOSED = "closed"  # Normal operation — requests pass through
    OPEN = "open"  # Failing — requests are rejected immediately
    HALF_OPEN = "half_open"  # Probing — limited requests allowed to test recovery


@dataclass
class CircuitConfig:
    """Circuit breaker configuration."""

    failure_threshold: int = 5  # Consecutive failures to trip OPEN
    success_threshold: int = 2  # Consecutive successes in HALF_OPEN to reset
    timeout_seconds: float = 60.0  # Seconds in OPEN before transitioning to HALF_OPEN
    half_open_max_requests: int = 1  # Max concurrent requests in HALF_OPEN
    excluded_exceptions: tuple = ()  # Exceptions that don't count as failures


@dataclass
class CircuitStats:
    """Per-circuit statistics."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    total_failures: int = 0
    total_successes: int = 0
    opened_at: float = 0.0
    half_open_requests: int = 0

    def reset(self) -> None:
        self.failure_count = 0
        self.success_count = 0
        self.half_open_requests = 0


# ============================================================================
# Circuit Breaker
# ============================================================================


class CircuitBreaker:
    """Thread-safe circuit breaker for a single endpoint."""

    def __init__(
        self,
        name: str,
        config: CircuitConfig | None = None,
    ):
        self.name = name
        self.config = config or CircuitConfig()
        self.stats = CircuitStats()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self.stats.state

    async def _transition(self, new_state: CircuitState) -> None:
        old = self.stats.state
        if old == new_state:
            return
        self.stats.state = new_state
        if new_state == CircuitState.OPEN:
            self.stats.opened_at = time.monotonic()
            self.stats.reset()
            logger.warning(
                "Circuit '%s' OPENED after %d consecutive failures",
                self.name,
                self.config.failure_threshold,
            )
        elif new_state == CircuitState.CLOSED:
            self.stats.reset()
            logger.info("Circuit '%s' CLOSED — service recovered", self.name)
        elif new_state == CircuitState.HALF_OPEN:
            self.stats.reset()
            logger.info("Circuit '%s' HALF_OPEN — probing", self.name)

    def _should_retry_open(self) -> bool:
        """Check if OPEN state has expired and should move to HALF_OPEN."""
        elapsed = time.monotonic() - self.stats.opened_at
        return elapsed >= self.config.timeout_seconds

    async def _on_success(self) -> None:
        async with self._lock:
            self.stats.total_successes += 1
            self.stats.last_success_time = time.monotonic()

            if self.stats.state == CircuitState.HALF_OPEN:
                self.stats.success_count += 1
                if self.stats.success_count >= self.config.success_threshold:
                    await self._transition(CircuitState.CLOSED)
            else:
                self.stats.failure_count = 0  # Reset on success when CLOSED

    async def _on_failure(self, exc: Exception) -> None:
        async with self._lock:
            if isinstance(exc, self.config.excluded_exceptions):
                return

            self.stats.total_failures += 1
            self.stats.last_failure_time = time.monotonic()

            if self.stats.state == CircuitState.HALF_OPEN:
                await self._transition(CircuitState.OPEN)
            else:
                self.stats.failure_count += 1
                if self.stats.failure_count >= self.config.failure_threshold:
                    await self._transition(CircuitState.OPEN)

    async def acquire(self) -> bool:
        """Try to acquire permission to make a request.

        Returns True if request should proceed, False if circuit is OPEN.
        """
        async with self._lock:
            state = self.stats.state

            if state == CircuitState.CLOSED:
                return True

            if state == CircuitState.OPEN:
                if self._should_retry_open():
                    await self._transition(CircuitState.HALF_OPEN)
                    # Re-read state after transition
                    state = self.stats.state
                else:
                    return False

            if state == CircuitState.HALF_OPEN:
                if self.stats.half_open_requests < self.config.half_open_max_requests:
                    self.stats.half_open_requests += 1
                    return True
                return False

            return False  # unreachable, but defensive

    async def release(self) -> None:
        """Release half-open slot after request completes."""
        async with self._lock:
            if self.stats.state == CircuitState.HALF_OPEN:
                self.stats.half_open_requests = max(0, self.stats.half_open_requests - 1)

    async def call(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: Callable[..., Awaitable[T]] | None = None,
        **kwargs: Any,
    ) -> T:
        """Execute fn through the circuit breaker.

        Raises CircuitOpenError if circuit is open and no fallback provided.
        """
        if not await self.acquire():
            if fallback is not None:
                logger.debug("Circuit '%s' open — using fallback", self.name)
                return await fallback(*args, **kwargs)
            raise CircuitOpenError(f"Circuit '{self.name}' is OPEN — request rejected")

        try:
            result = await fn(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as exc:
            await self._on_failure(exc)
            raise
        finally:
            await self.release()


# ============================================================================
# Registry
# ============================================================================


class CircuitRegistry:
    """Global registry of circuit breakers, keyed by endpoint name."""

    def __init__(self):
        self._circuits: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        config: CircuitConfig | None = None,
    ) -> CircuitBreaker:
        async with self._lock:
            if name not in self._circuits:
                self._circuits[name] = CircuitBreaker(name=name, config=config)
            return self._circuits[name]

    def get_all_stats(self) -> dict[str, CircuitStats]:
        """Export all circuit stats for monitoring."""
        return {name: cb.stats for name, cb in self._circuits.items()}

    async def reset_all(self) -> None:
        """Reset all circuits to CLOSED (for testing/admin)."""
        async with self._lock:
            for cb in self._circuits.values():
                cb.stats.reset()
                cb.stats.state = CircuitState.CLOSED

    async def force_open(self, name: str) -> None:
        """Force a circuit OPEN (for manual intervention)."""
        async with self._lock:
            if name in self._circuits:
                await self._circuits[name]._transition(CircuitState.OPEN)

    async def force_closed(self, name: str) -> None:
        """Force a circuit CLOSED (for manual intervention)."""
        async with self._lock:
            if name in self._circuits:
                await self._circuits[name]._transition(CircuitState.CLOSED)


# ============================================================================
# Decorator
# ============================================================================


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout_seconds: float = 60.0,
    success_threshold: int = 2,
    excluded_exceptions: tuple = (),
):
    """Decorator: wrap an async function with a circuit breaker.

    Usage:
        @circuit_breaker("llm_api", failure_threshold=3, timeout_seconds=30)
        async def call_llm(prompt: str) -> str: ...
    """
    config = CircuitConfig(
        failure_threshold=failure_threshold,
        timeout_seconds=timeout_seconds,
        success_threshold=success_threshold,
        excluded_exceptions=excluded_exceptions,
    )
    cb = CircuitBreaker(name=name, config=config)

    def decorator(fn: Callable[..., Awaitable[T]]):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await cb.call(fn, *args, **kwargs)

        wrapper._circuit_breaker = cb  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ============================================================================
# Exceptions
# ============================================================================


class CircuitOpenError(Exception):
    """Raised when request is rejected because circuit is OPEN."""



# ============================================================================
# Module-level defaults
# ============================================================================

# Global registry — use this shared instance across the app
default_registry = CircuitRegistry()
