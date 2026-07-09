"""
Memory Optimization Tools for AgentOS.
Object pooling, LRU caching, memory monitoring, and smart caching with TTL.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


# ============================================================================
# ObjectPool
# ============================================================================


class ObjectPool(Generic[T]):
    """Thread-safe object pool with auto-expiry and size limits.

    Reuses pre-allocated objects instead of creating/destroying them repeatedly.
    """

    def __init__(
        self,
        factory: Callable[[], T],
        max_size: int = 100,
        max_idle: int = 30,
        idle_timeout: float = 300.0,
    ):
        self._factory = factory
        self._max_size = max_size
        self._max_idle = max_idle
        self._idle_timeout = idle_timeout
        self._pool: list[_PooledItem[T]] = []
        self._lock = threading.Lock()
        self._created: int = 0
        self._borrowed: int = 0
        self._returned: int = 0

    def acquire(self) -> T:
        """Borrow an object from the pool or create a new one."""
        with self._lock:
            now = time.monotonic()
            self._evict_expired(now)

            if self._pool:
                item = self._pool.pop()
                item.idle = False
                self._borrowed += 1
                return item.obj

            if self._created < self._max_size:
                self._created += 1
                self._borrowed += 1
                return self._factory()

        # Pool fully allocated; create temporary object outside pool
        self._borrowed += 1
        return self._factory()

    def release(self, obj: T) -> None:
        """Return an object to the pool for reuse."""
        with self._lock:
            self._returned += 1
            self._evict_expired(time.monotonic())

            if len(self._pool) < self._max_idle:
                self._pool.append(_PooledItem(obj=obj, idle=True, acquired_at=time.monotonic()))
            # else: discard excess objects

    def _evict_expired(self, now: float) -> None:
        self._pool[:] = [item for item in self._pool if now - item.acquired_at < self._idle_timeout]

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "created": self._created,
                "borrowed": self._borrowed,
                "returned": self._returned,
                "idle": len(self._pool),
                "active": self._borrowed - self._returned,
            }

    def __len__(self) -> int:
        return len(self._pool)


@dataclass
class _PooledItem(Generic[T]):
    obj: T
    idle: bool
    acquired_at: float


# ============================================================================
# LRUCache
# ============================================================================


class LRUCache(Generic[T]):
    """Thread-safe LRU cache with capacity limit and optional TTL."""

    def __init__(self, capacity: int = 1024, ttl: float | None = None):
        self._capacity = capacity
        self._ttl = ttl
        self._cache: OrderedDict[str, _CacheEntry[T]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    def get(self, key: str) -> T | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if self._ttl and time.monotonic() - entry.timestamp > self._ttl:
                del self._cache[key]
                self._misses += 1
                self._evictions += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value

    def put(self, key: str, value: T) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = _CacheEntry(value=value, timestamp=time.monotonic())
                return
            if len(self._cache) >= self._capacity:
                self._cache.popitem(last=False)
                self._evictions += 1
            self._cache[key] = _CacheEntry(value=value, timestamp=time.monotonic())

    def remove(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._cache),
                "capacity": self._capacity,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self.hit_rate, 4),
                "evictions": self._evictions,
            }

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        return key in self._cache


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    timestamp: float


# ============================================================================
# SmartCache
# ============================================================================


class SmartCache(Generic[T]):
    """Multi-tier cache with compute-on-miss and automatic invalidation."""

    def __init__(self, compute: Callable[[str], T], capacity: int = 1024, ttl: float = 300.0):
        self._lru = LRUCache[T](capacity=capacity, ttl=ttl)
        self._compute = compute
        self._lock = threading.Lock()

    def get(self, key: str) -> T:
        """Get from cache or compute and cache on miss."""
        cached = self._lru.get(key)
        if cached is not None:
            return cached
        with self._lock:
            # Double-check after acquiring lock
            cached = self._lru.get(key)
            if cached is not None:
                return cached
            value = self._compute(key)
            self._lru.put(key, value)
            return value

    def prefetch(self, keys: list[str]) -> int:
        """Pre-compute and cache values for a list of keys. Returns count cached."""
        count = 0
        for key in keys:
            if key not in self._lru:
                try:
                    self.get(key)
                    count += 1
                except Exception:
                    pass
        return count

    def invalidate(self, key: str) -> bool:
        return self._lru.remove(key)

    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys containing pattern substring. Returns count removed."""
        count = 0
        for key in list(self._lru._cache.keys()):
            if pattern in key:
                if self._lru.remove(key):
                    count += 1
        return count

    def clear(self) -> None:
        self._lru.clear()

    @property
    def stats(self) -> dict[str, Any]:
        return self._lru.stats

    def __len__(self) -> int:
        return len(self._lru)


# ============================================================================
# MemoryMonitor
# ============================================================================


class MemoryMonitor:
    """Monitor per-component memory usage with high-water mark tracking."""

    _singleton = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._singleton is None:
            with cls._lock:
                if cls._singleton is None:
                    cls._singleton = super().__new__(cls)
                    cls._singleton._initialized = False
        return cls._singleton

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._components: dict[str, _ComponentMetrics] = {}
        self._lock = threading.Lock()

    def register(self, name: str) -> None:
        with self._lock:
            if name not in self._components:
                self._components[name] = _ComponentMetrics(name=name)

    def record_alloc(self, name: str, size_bytes: int) -> None:
        with self._lock:
            comp = self._components.get(name)
            if comp:
                comp.current_bytes += size_bytes
                comp.total_allocations += 1
                comp.peak_bytes = max(comp.peak_bytes, comp.current_bytes)

    def record_free(self, name: str, size_bytes: int) -> None:
        with self._lock:
            comp = self._components.get(name)
            if comp:
                comp.current_bytes = max(0, comp.current_bytes - size_bytes)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: comp.to_dict() for name, comp in self._components.items()}

    def alert(self, name: str, threshold_bytes: int) -> bool:
        """Check if a component exceeds memory threshold."""
        with self._lock:
            comp = self._components.get(name)
            if comp:
                return comp.current_bytes > threshold_bytes
            return False

    @property
    def total_current(self) -> int:
        with self._lock:
            return sum(c.current_bytes for c in self._components.values())


@dataclass
class _ComponentMetrics:
    name: str
    current_bytes: int = 0
    peak_bytes: int = 0
    total_allocations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "current_bytes": self.current_bytes,
            "peak_bytes": self.peak_bytes,
            "total_allocations": self.total_allocations,
        }


# ============================================================================
# Convenience Functions
# ============================================================================


def create_object_pool(
    factory: Callable[[], T],
    max_size: int = 100,
    max_idle: int = 30,
    idle_timeout: float = 300.0,
) -> ObjectPool[T]:
    """Create a thread-safe object pool."""
    return ObjectPool(factory, max_size=max_size, max_idle=max_idle, idle_timeout=idle_timeout)


def create_lru_cache(capacity: int = 1024, ttl: float | None = None) -> LRUCache[Any]:
    """Create a thread-safe LRU cache."""
    return LRUCache(capacity=capacity, ttl=ttl)


def create_smart_cache(
    compute: Callable[[str], T],
    capacity: int = 1024,
    ttl: float = 300.0,
) -> SmartCache[T]:
    """Create a smart cache with compute-on-miss."""
    return SmartCache(compute, capacity=capacity, ttl=ttl)


def get_memory_monitor() -> MemoryMonitor:
    """Get the singleton memory monitor."""
    return MemoryMonitor()
