"""
RateLimiter — token bucket and sliding window rate limiters.

Supports two algorithms:
    - TokenBucket: supports burst (tokens accumulate up to burst size), smooth refill
    - SlidingWindow: strict per-window limit, no burst

Common interface:
    - try_acquire(key) → bool
    - acquire_or_wait(key, timeout) → bool  (blocking with timeout)
    - reset(key)
    - stats() → dict
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ============================================================================
# Rate Limit Exceeded
# ============================================================================

class RateLimitExceeded(Exception):
    def __init__(self, key: str, limit: float, window: float):
        self.key = key
        self.limit = limit
        self.window = window
        super().__init__(f"Rate limit exceeded for '{key}': {limit}/{window}s")


# ============================================================================
# TokenBucket
# ============================================================================

@dataclass
class _BucketState:
    tokens: float
    last_refill: float


class TokenBucket:
    """Token bucket rate limiter with burst support.

    Usage:
        limiter = TokenBucket(rate=10.0, burst=20.0)  # 10 tokens/sec, burst up to 20
        limiter.try_acquire("api:user:42")  # → True/False
        limiter.try_acquire("api:user:42", tokens=5)  # consume 5 tokens
    """

    def __init__(self, rate: float, burst: Optional[float] = None):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._rate = rate
        self._burst = burst if burst is not None else rate
        self._buckets: Dict[str, _BucketState] = {}
        self._lock = threading.RLock()
        self._total_acquired: int = 0
        self._total_rejected: int = 0

    def try_acquire(self, key: str, tokens: float = 1.0) -> bool:
        """Try to acquire tokens. Returns True if allowed."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _BucketState(tokens=self._burst, last_refill=now)
                self._buckets[key] = bucket
            else:
                # Refill
                elapsed = now - bucket.last_refill
                bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate)
                bucket.last_refill = now

            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                self._total_acquired += 1
                return True
            else:
                self._total_rejected += 1
                return False

    def acquire_or_wait(self, key: str, timeout: Optional[float] = None, tokens: float = 1.0) -> bool:
        """Block until tokens available or timeout."""
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            if self.try_acquire(key, tokens):
                return True
            if deadline and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)

    def reset_all(self) -> None:
        with self._lock:
            self._buckets.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "rate": self._rate,
                "burst": self._burst,
                "active_keys": len(self._buckets),
                "total_acquired": self._total_acquired,
                "total_rejected": self._total_rejected,
            }

    @property
    def rate(self) -> float:
        return self._rate


# ============================================================================
# SlidingWindow
# ============================================================================

class SlidingWindow:
    """Sliding window rate limiter — strict per-window limit, no burst.

    Usage:
        limiter = SlidingWindow(limit=100, window=60.0)  # 100 req per 60s
        limiter.try_acquire("api:endpoint")  # → True/False
    """

    def __init__(self, limit: int, window: float = 60.0):
        if limit <= 0:
            raise ValueError("limit must be positive")
        self._limit = limit
        self._window = window
        self._windows: Dict[str, List[float]] = {}
        self._lock = threading.RLock()
        self._total_acquired: int = 0
        self._total_rejected: int = 0

    def try_acquire(self, key: str) -> bool:
        """Try to acquire a slot. Returns True if within limit."""
        now = time.monotonic()
        with self._lock:
            timestamps = self._windows.get(key)
            if timestamps is None:
                timestamps = []
                self._windows[key] = timestamps

            # Evict expired entries
            cutoff = now - self._window
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)

            if len(timestamps) < self._limit:
                timestamps.append(now)
                self._total_acquired += 1
                return True
            else:
                self._total_rejected += 1
                return False

    def acquire_or_wait(self, key: str, timeout: Optional[float] = None) -> bool:
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            if self.try_acquire(key):
                return True
            if deadline and time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def reset(self, key: str) -> None:
        with self._lock:
            self._windows.pop(key, None)

    def reset_all(self) -> None:
        with self._lock:
            self._windows.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "limit": self._limit,
                "window": self._window,
                "active_keys": len(self._windows),
                "total_acquired": self._total_acquired,
                "total_rejected": self._total_rejected,
            }

    @property
    def limit(self) -> int:
        return self._limit
