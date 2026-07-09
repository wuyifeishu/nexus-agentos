"""AgentOS Rate Limiter — multi-strategy throttling for production APIs.

Strategies:
- TokenBucket: classic token refill, burst-tolerant
- SlidingWindow: precise time-window counting
- ConcurrentLimiter: limit in-flight requests (semaphore-based)
- CompositeLimiter: chain multiple limiters together

Design: ~280 lines, zero external deps beyond stdlib + asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================
# Core limiters
# ============================================================================


class TokenBucket:
    """Classic token bucket for rate limiting with burst support.

    Tokens refill at a fixed rate up to capacity. Each request costs 1 token.
    """

    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: Tokens per second refill rate
            capacity: Maximum tokens (burst size)
        """
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if capacity <= 0:
            raise ValueError("capacity must be > 0")

        self.rate = rate
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    async def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens. Returns True if successful, False otherwise."""
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def wait_and_acquire(self, tokens: int = 1, timeout: float | None = None) -> bool:
        """Wait until tokens are available or timeout expires."""
        deadline = (time.monotonic() + timeout) if timeout is not None else None

        while True:
            if await self.acquire(tokens):
                return True

            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

                # Calculate wait time
                needed = tokens - self._tokens
                wait_time = needed / self.rate

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait_time = min(wait_time, remaining)

            await asyncio.sleep(wait_time)

    @property
    def available_tokens(self) -> float:
        return self._tokens

    @property
    def fill_level(self) -> float:
        """0.0 (empty) to 1.0 (full)."""
        return self._tokens / self.capacity


class SlidingWindow:
    """Sliding window rate limiter using precise timestamps.

    Tracks request timestamps in a deque for O(1) amortized cleanup.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        if max_requests <= 0:
            raise ValueError("max_requests must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    def _cleanup(self, now: float) -> None:
        cutoff = now - self.window_seconds
        # Find first timestamp within window
        idx = 0
        for ts in self._timestamps:
            if ts >= cutoff:
                break
            idx += 1
        if idx > 0:
            self._timestamps = self._timestamps[idx:]

    async def acquire(self) -> bool:
        """Try to add a request to the window. Returns True if within limit."""
        async with self._lock:
            now = time.monotonic()
            self._cleanup(now)
            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return True
            return False

    @property
    def current_count(self) -> int:
        return len(self._timestamps)

    @property
    def remaining(self) -> int:
        return max(0, self.max_requests - len(self._timestamps))


class ConcurrentLimiter:
    """Limit the number of in-flight concurrent operations."""

    def __init__(self, max_concurrent: int):
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be > 0")
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def acquire(self) -> bool:
        """Acquire a slot. Returns False if cancelled."""
        try:
            await self._semaphore.acquire()
            return True
        except asyncio.CancelledError:
            return False

    def release(self) -> None:
        """Release a slot."""
        self._semaphore.release()

    @property
    def available(self) -> int:
        return self._semaphore._value  # pyright: ignore[reportPrivateUsage]


class CompositeLimiter:
    """Chain multiple limiters — all must pass for a request to proceed."""

    def __init__(self, limiters: list):
        self.limiters = limiters

    async def acquire(self) -> bool:
        """Try to acquire from all limiters simultaneously."""
        results = await asyncio.gather(
            *[limiter.acquire() for limiter in self.limiters],
            return_exceptions=True,
        )
        for r in results:
            if r is False or isinstance(r, Exception):
                return False
        return all(results)


# ============================================================================
# Rate limit decorator / context manager
# ============================================================================


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""



class RateLimiter:
    """Unified rate limiter wrapping any strategy."""

    def __init__(
        self,
        name: str = "default",
        strategy=None,
    ):
        self.name = name
        self.strategy = strategy

    async def __aenter__(self):
        ok = await self.strategy.acquire() if self.strategy else True
        if not ok:
            raise RateLimitError(f"Rate limit exceeded: {self.name}")
        return self

    async def __aexit__(self, *args):
        if isinstance(self.strategy, ConcurrentLimiter):
            self.strategy.release()

    @classmethod
    def token_bucket(cls, name: str, rate: float, capacity: int) -> RateLimiter:
        return cls(name=name, strategy=TokenBucket(rate=rate, capacity=capacity))

    @classmethod
    def sliding_window(cls, name: str, max_requests: int, window_seconds: float) -> RateLimiter:
        return cls(
            name=name,
            strategy=SlidingWindow(max_requests=max_requests, window_seconds=window_seconds),
        )

    @classmethod
    def concurrent(cls, name: str, max_concurrent: int) -> RateLimiter:
        return cls(name=name, strategy=ConcurrentLimiter(max_concurrent=max_concurrent))


# ============================================================================
# Endpoint-level registry
# ============================================================================


@dataclass
class EndpointRateLimit:
    """Per-endpoint rate limit configuration."""

    endpoint: str
    requests_per_second: float | None = None
    requests_per_minute: int | None = None
    concurrent: int | None = None
    burst: int = 1


class RateLimitRegistry:
    """Manage per-endpoint rate limiters."""

    def __init__(self):
        self._limiters: dict[str, RateLimiter] = {}
        self._lock = asyncio.Lock()

    async def configure(self, spec: EndpointRateLimit) -> RateLimiter:
        async with self._lock:
            limiters = []

            if spec.requests_per_second is not None:
                limiters.append(
                    TokenBucket(
                        rate=spec.requests_per_second,
                        capacity=max(spec.burst, 1),
                    )
                )

            if spec.requests_per_minute is not None:
                limiters.append(
                    SlidingWindow(
                        max_requests=spec.requests_per_minute,
                        window_seconds=60.0,
                    )
                )

            if spec.concurrent is not None:
                limiters.append(ConcurrentLimiter(max_concurrent=spec.concurrent))

            strategy = (
                CompositeLimiter(limiters)
                if len(limiters) > 1
                else limiters[0] if limiters else None
            )

            limiter = RateLimiter(name=spec.endpoint, strategy=strategy)
            self._limiters[spec.endpoint] = limiter
            return limiter

    async def get(self, endpoint: str) -> RateLimiter | None:
        return self._limiters.get(endpoint)

    async def acquire(self, endpoint: str) -> bool:
        limiter = self._limiters.get(endpoint)
        if limiter is None:
            return True
        return await limiter.strategy.acquire() if limiter.strategy else True
