"""
Connection Pooling & Resource Management for AgentOS.
Generic connection pool, rate limiter, resource quota manager, and health-checked pools.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, Set, TypeVar

T = TypeVar("T")


# ============================================================================
# ConnectionPool
# ============================================================================

@dataclass
class _PooledConn(Generic[T]):
    conn: T
    created_at: float
    last_used: float
    borrowed: bool = False


class ConnectionPool(Generic[T]):
    """Thread-safe generic connection pool with health checks and idle eviction.

    Supports: min/max sizing, health validation, auto-reconnect, idle timeout.
    """

    def __init__(
        self,
        factory: Callable[[], T],
        health_check: Optional[Callable[[T], bool]] = None,
        closer: Optional[Callable[[T], None]] = None,
        min_size: int = 2,
        max_size: int = 20,
        max_idle: int = 10,
        idle_timeout: float = 300.0,
        checkout_timeout: float = 30.0,
    ):
        self._factory = factory
        self._health_check = health_check
        self._closer = closer
        self._min_size = min_size
        self._max_size = max_size
        self._max_idle = max_idle
        self._idle_timeout = idle_timeout
        self._checkout_timeout = checkout_timeout
        self._pool: deque[_PooledConn[T]] = deque()
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._total_created: int = 0
        self._total_borrowed: int = 0
        self._total_returned: int = 0
        self._total_failed_health: int = 0
        self._closed: bool = False

    def _create(self) -> _PooledConn[T]:
        conn = self._factory()
        self._total_created += 1
        now = time.monotonic()
        return _PooledConn(conn=conn, created_at=now, last_used=now)

    def _validate(self, pc: _PooledConn[T]) -> bool:
        if self._health_check is None:
            return True
        try:
            ok = self._health_check(pc.conn)
            if not ok:
                self._total_failed_health += 1
            return ok
        except Exception:
            self._total_failed_health += 1
            return False

    def acquire(self, timeout: Optional[float] = None) -> T:
        """Borrow a connection from the pool. Blocks until available or timeout."""
        if timeout is None:
            timeout = self._checkout_timeout

        with self._condition:
            deadline = time.monotonic() + timeout

            while True:
                if self._closed:
                    raise RuntimeError("ConnectionPool is closed")

                # Find a valid idle connection; evict unhealthy ones
                unhealthy: List[_PooledConn[T]] = []
                for pc in self._pool:
                    if pc.borrowed:
                        continue
                    if self._validate(pc):
                        pc.borrowed = True
                        pc.last_used = time.monotonic()
                        self._total_borrowed += 1
                        return pc.conn
                    else:
                        unhealthy.append(pc)

                for pc in unhealthy:
                    if pc in self._pool:
                        self._pool.remove(pc)
                    self._close_conn(pc)

                # Try to create a new one if under max
                active = sum(1 for pc in self._pool if pc.borrowed)
                if active + len([pc for pc in self._pool if not pc.borrowed]) < self._max_size:
                    pc = self._create()
                    pc.borrowed = True
                    self._total_borrowed += 1
                    self._pool.append(pc)
                    return pc.conn

                # Wait for a connection to be returned
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for connection after {timeout}s")
                self._condition.wait(timeout=min(remaining, 1.0))

    def release(self, conn: T) -> None:
        """Return a connection to the pool."""
        with self._condition:
            for pc in self._pool:
                if pc.conn is conn:
                    pc.borrowed = False
                    pc.last_used = time.monotonic()
                    self._total_returned += 1
                    self._condition.notify()
                    return
            # Connection not in pool — close it
            self._close_raw(conn)
            self._condition.notify()

    def _close_conn(self, pc: _PooledConn[T]) -> None:
        self._close_raw(pc.conn)

    def _close_raw(self, conn: T) -> None:
        if self._closer:
            try:
                self._closer(conn)
            except Exception:
                pass

    def warm_up(self) -> int:
        """Pre-create connections up to min_size. Returns number created."""
        count = 0
        with self._condition:
            idle = sum(1 for pc in self._pool if not pc.borrowed)
            needed = self._min_size - idle
            for _ in range(needed):
                self._pool.append(self._create())
                count += 1
            return count

    def evict_idle(self) -> int:
        """Remove idle connections past timeout. Returns number evicted."""
        now = time.monotonic()
        count = 0
        with self._condition:
            # Preserve min_size
            idle = [pc for pc in self._pool if not pc.borrowed]
            to_keep = self._min_size
            old_first = sorted(idle, key=lambda pc: pc.last_used)
            for pc in old_first[to_keep:]:
                if now - pc.last_used > self._idle_timeout:
                    self._pool.remove(pc)
                    self._close_conn(pc)
                    count += 1
            return count

    def close(self) -> None:
        """Close all connections and shut down the pool."""
        with self._condition:
            self._closed = True
            for pc in self._pool:
                self._close_conn(pc)
            self._pool.clear()
            self._condition.notify_all()

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            active = sum(1 for pc in self._pool if pc.borrowed)
            idle = sum(1 for pc in self._pool if not pc.borrowed)
            return {
                "total_created": self._total_created,
                "total_borrowed": self._total_borrowed,
                "total_returned": self._total_returned,
                "active": active,
                "idle": idle,
                "total": len(self._pool),
                "failed_health_checks": self._total_failed_health,
                "capacity": self._max_size,
            }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ============================================================================
# RateLimiter
# ============================================================================

class RateLimiter:
    """Thread-safe token bucket rate limiter with burst support."""

    def __init__(self, rate: float, burst: int = 1):
        """rate: tokens per second. burst: max tokens accumulated."""
        self._rate = rate
        self._burst = burst
        self._tokens: float = burst
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()
        self._total_acquired: int = 0
        self._total_rejected: int = 0

    def acquire(self, count: int = 1, timeout: Optional[float] = None) -> bool:
        """Try to acquire N tokens. Blocks up to timeout if not enough."""
        deadline = time.monotonic() + timeout if timeout else None

        with self._lock:
            while True:
                self._refill()
                if self._tokens >= count:
                    self._tokens -= count
                    self._total_acquired += count
                    return True

                if deadline and time.monotonic() >= deadline:
                    self._total_rejected += count
                    return False

                # Wait for refill
                wait_time = (count - self._tokens) / self._rate
                if deadline:
                    wait_time = min(wait_time, deadline - time.monotonic())
                if wait_time <= 0:
                    self._total_rejected += count
                    return False

                # Release lock during wait
                self._lock.release()
                try:
                    time.sleep(wait_time)
                finally:
                    self._lock.acquire()

    def try_acquire(self, count: int = 1) -> bool:
        """Non-blocking attempt to acquire tokens."""
        with self._lock:
            self._refill()
            if self._tokens >= count:
                self._tokens -= count
                self._total_acquired += count
                return True
            self._total_rejected += count
            return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self._refill()
            return {
                "rate": self._rate,
                "burst": self._burst,
                "tokens_available": round(self._tokens, 2),
                "total_acquired": self._total_acquired,
                "total_rejected": self._total_rejected,
            }


# ============================================================================
# ResourceQuota
# ============================================================================

class ResourceQuota:
    """Track and enforce resource usage quotas per component."""

    def __init__(self, global_limit: int = 1024):
        self._global_limit = global_limit
        self._allocations: Dict[str, int] = {}
        self._lock = threading.Lock()

    def allocate(self, component: str, amount: int = 1) -> bool:
        """Try to allocate resources. Returns True if successful."""
        with self._lock:
            current_total = sum(self._allocations.values())
            if current_total + amount > self._global_limit:
                return False
            self._allocations[component] = self._allocations.get(component, 0) + amount
            return True

    def release(self, component: str, amount: int = 1) -> None:
        with self._lock:
            current = self._allocations.get(component, 0)
            self._allocations[component] = max(0, current - amount)

    def set_limit(self, component: str, limit: int) -> None:
        with self._lock:
            current = self._allocations.get(component, 0)
            if current > limit:
                self._allocations[component] = limit

    def get_usage(self, component: str) -> int:
        with self._lock:
            return self._allocations.get(component, 0)

    @property
    def total_used(self) -> int:
        with self._lock:
            return sum(self._allocations.values())

    @property
    def remaining(self) -> int:
        return self._global_limit - self.total_used

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "global_limit": self._global_limit,
                "total_used": self.total_used,
                "remaining": self.remaining,
                "allocations": dict(self._allocations),
            }


# ============================================================================
# Convenience Functions
# ============================================================================

def create_connection_pool(
    factory: Callable[[], T],
    health_check: Optional[Callable[[T], bool]] = None,
    closer: Optional[Callable[[T], None]] = None,
    min_size: int = 2,
    max_size: int = 20,
) -> ConnectionPool[T]:
    """Create a thread-safe connection pool."""
    return ConnectionPool(
        factory,
        health_check=health_check,
        closer=closer,
        min_size=min_size,
        max_size=max_size,
    )


def create_rate_limiter(rate: float, burst: int = 10) -> RateLimiter:
    """Create a token bucket rate limiter."""
    return RateLimiter(rate=rate, burst=burst)


def create_resource_quota(global_limit: int = 1024) -> ResourceQuota:
    """Create a resource quota manager."""
    return ResourceQuota(global_limit=global_limit)
