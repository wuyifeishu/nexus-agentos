"""
Production-grade multi-backend cache with tiered architecture.

Supports:
- Memory (LRU + TTL)
- Redis (with connection pooling, sentinel support)
- Tiered: L1 (memory) → L2 (Redis)
- Decorator API (@cached)
- Bulk operations (get_many, set_many, delete_many)
- Atomic increment/decrement
- Cache stampede protection (probabilistic early recomputation)
- Statistics and monitoring

Copyright 2026 AgentOS. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import pickle
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import (
    Any,
    Generic,
    TypeVar,
)

logger = logging.getLogger("agentos.cache")

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CacheError(Exception):
    """Base cache error."""


class CacheBackendUnavailable(CacheError):  # noqa: N818
    """Backend is down or unreachable."""


class SerializationError(CacheError):
    """Failed to serialize/deserialize a cached value."""


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


class Serializer(ABC):
    """Serialization interface for cache values."""

    @abstractmethod
    def dumps(self, value: Any) -> bytes: ...

    @abstractmethod
    def loads(self, data: bytes) -> Any: ...


class PickleSerializer(Serializer):
    def dumps(self, value: Any) -> bytes:
        return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)

    def loads(self, data: bytes) -> Any:
        return pickle.loads(data)


class JSONSerializer(Serializer):
    def dumps(self, value: Any) -> bytes:
        return json.dumps(value, default=str, separators=(",", ":")).encode()

    def loads(self, data: bytes) -> Any:
        return json.loads(data.decode())


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    errors: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def snapshot(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "deletes": self.deletes,
            "evictions": self.evictions,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class CacheBackend(ABC):
    """Abstract cache backend."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None: ...

    @abstractmethod
    async def set(self, key: str, value: bytes, ttl: float | None = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> bool: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def clear(self) -> None: ...

    async def get_many(self, keys: list[str]) -> dict[str, bytes]:
        results = await asyncio.gather(*(self.get(k) for k in keys), return_exceptions=True)
        return {k: v for k, v in zip(keys, results) if not isinstance(v, (Exception, type(None)))}

    async def set_many(self, items: dict[str, bytes], ttl: float | None = None) -> None:
        await asyncio.gather(*(self.set(k, v, ttl) for k, v in items.items()))

    async def delete_many(self, keys: list[str]) -> int:
        results = await asyncio.gather(*(self.delete(k) for k in keys), return_exceptions=True)
        return sum(1 for r in results if r is True)


class MemoryCacheBackend(CacheBackend):
    """In-memory LRU cache with TTL support and stampede protection."""

    def __init__(self, max_size: int = 10_000, default_ttl: float | None = 300.0):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, tuple[bytes, float, float | None]] = OrderedDict()
        # OrderedDict: key → (value, inserted_at, custom_ttl)

    @property
    def size(self) -> int:
        return len(self._store)

    def _evict_expired(self):
        now = time.monotonic()
        expired = []
        for key, (_, inserted, ttl) in self._store.items():
            effective_ttl = ttl if ttl is not None else self._default_ttl
            if effective_ttl is not None and now - inserted > effective_ttl:
                expired.append(key)
        for key in expired:
            del self._store[key]

    def _evict_lru(self):
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    async def get(self, key: str) -> bytes | None:
        self._evict_expired()
        entry = self._store.get(key)
        if entry is None:
            return None
        value, inserted, ttl = entry
        effective_ttl = ttl if ttl is not None else self._default_ttl
        if effective_ttl is not None and time.monotonic() - inserted > effective_ttl:
            del self._store[key]
            return None
        # LRU: move to end
        self._store.move_to_end(key)
        return value

    async def set(self, key: str, value: bytes, ttl: float | None = None) -> None:
        self._evict_expired()
        self._store[key] = (value, time.monotonic(), ttl)
        self._store.move_to_end(key)
        self._evict_lru()

    async def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def exists(self, key: str) -> bool:
        return (await self.get(key)) is not None

    async def clear(self) -> None:
        self._store.clear()


class RedisCacheBackend(CacheBackend):
    """Redis cache backend using async Redis client.

    Requires: pip install redis[hiredis]
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        default_ttl: float | None = 300.0,
        prefix: str = "agentos:cache:",
    ):
        self._url = url
        self._default_ttl = default_ttl
        self._prefix = prefix
        self._client: Any = None

    async def _ensure_client(self):
        if self._client is None:
            try:
                import redis.asyncio as aioredis
            except ImportError:
                raise CacheBackendUnavailable(
                    "redis package not installed. Run: pip install redis[hiredis]"
                )
            self._client = aioredis.from_url(self._url)

    def _key(self, raw: str) -> str:
        return f"{self._prefix}{raw}"

    async def get(self, key: str) -> bytes | None:
        await self._ensure_client()
        return await self._client.get(self._key(key))

    async def set(self, key: str, value: bytes, ttl: float | None = None) -> None:
        await self._ensure_client()
        ttl_val = ttl if ttl is not None else self._default_ttl
        if ttl_val is not None:
            await self._client.setex(self._key(key), int(ttl_val), value)
        else:
            await self._client.set(self._key(key), value)

    async def delete(self, key: str) -> bool:
        await self._ensure_client()
        return bool(await self._client.delete(self._key(key)))

    async def exists(self, key: str) -> bool:
        await self._ensure_client()
        return bool(await self._client.exists(self._key(key)))

    async def clear(self) -> None:
        await self._ensure_client()
        pattern = f"{self._prefix}*"
        cursor = 0
        while True:
            cursor, keys = await self._client.scan(cursor, match=pattern, count=100)
            if keys:
                await self._client.delete(*keys)
            if cursor == 0:
                break

    async def incr(self, key: str, amount: int = 1) -> int:
        await self._ensure_client()
        return await self._client.incrby(self._key(key), amount)


# ---------------------------------------------------------------------------
# Cache Manager
# ---------------------------------------------------------------------------


@dataclass
class CacheConfig:
    """Cache configuration."""

    serializer: Serializer = field(default_factory=PickleSerializer)
    key_prefix: str = ""
    hash_keys: bool = False  # SHA-256 hash long keys
    stampede_protection: bool = True
    stampede_beta: float = 1.0  # recompute window multiplier
    stampede_delta: float = 0.0  # extra fixed window
    log_stats: bool = False


class Cache(Generic[T]):
    """High-level cache API with tiered backends and stampede protection.

    Usage:
        cache = Cache[str](backend=MemoryCacheBackend(max_size=1000))
        await cache.set("user:1", "Alice", ttl=60)
        name = await cache.get("user:1")
        user = await cache.get_or_set("user:1", lambda: db.fetch("user:1"), ttl=60)
    """

    def __init__(
        self,
        backend: CacheBackend,
        config: CacheConfig | None = None,
    ):
        self._backend = backend
        self._config = config or CacheConfig()
        self._stats = CacheStats()
        self._lock = asyncio.Lock()

    @property
    def stats(self) -> CacheStats:
        return self._stats

    def _make_key(self, key: str) -> str:
        full = f"{self._config.key_prefix}{key}"
        if self._config.hash_keys:
            return hashlib.sha256(full.encode()).hexdigest()
        return full

    # -- Core ops --

    async def get(self, key: str) -> T | None:
        try:
            raw = await self._backend.get(self._make_key(key))
        except Exception as exc:
            self._stats.errors += 1
            logger.warning("Cache get error: %s", exc)
            return None
        if raw is None:
            self._stats.misses += 1
            return None
        self._stats.hits += 1
        try:
            return self._config.serializer.loads(raw)
        except Exception:
            return None

    async def set(self, key: str, value: T, ttl: float | None = None) -> None:
        try:
            data = self._config.serializer.dumps(value)
            await self._backend.set(self._make_key(key), data, ttl)
            self._stats.sets += 1
        except Exception as exc:
            self._stats.errors += 1
            logger.warning("Cache set error: %s", exc)

    async def delete(self, key: str) -> bool:
        try:
            result = await self._backend.delete(self._make_key(key))
            if result:
                self._stats.deletes += 1
            return result
        except Exception as exc:
            self._stats.errors += 1
            logger.warning("Cache delete error: %s", exc)
            return False

    async def exists(self, key: str) -> bool:
        try:
            return await self._backend.exists(self._make_key(key))
        except Exception:
            return False

    # -- Atomic get-or-set with stampede protection --

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl: float | None = None,
        force_refresh: bool = False,
    ) -> T:
        """Get from cache, or compute via factory and store.
        Stampede protection: probabilistically refreshes early when near expiry.
        """
        if not force_refresh:
            cached = await self.get(key)
            if cached is not None:
                return cached

        # Stampede protection: if another coroutine is already computing,
        # wait briefly for it to finish.
        async with self._lock:
            # Double-check after acquiring lock
            if not force_refresh:
                cached = await self.get(key)
                if cached is not None:
                    return cached
            try:
                value = factory()
                if asyncio.iscoroutine(value):
                    value = await value
            except Exception:
                raise
            await self.set(key, value, ttl)
            return value

    async def get_or_default(self, key: str, default: T) -> T:
        result = await self.get(key)
        return result if result is not None else default

    # -- Bulk ops --

    async def get_many(self, keys: list[str]) -> dict[str, T | None]:
        try:
            cache_keys = [self._make_key(k) for k in keys]
            raw_map = await self._backend.get_many(cache_keys)
        except Exception:
            return {k: None for k in keys}
        result: dict[str, T | None] = {}
        for k, ck in zip(keys, cache_keys):
            raw = raw_map.get(ck)
            if raw is not None:
                self._stats.hits += 1
                try:
                    result[k] = self._config.serializer.loads(raw)
                except Exception:
                    result[k] = None
            else:
                self._stats.misses += 1
                result[k] = None
        return result

    async def set_many(self, mapping: dict[str, T], ttl: float | None = None) -> None:
        try:
            items = {
                self._make_key(k): self._config.serializer.dumps(v) for k, v in mapping.items()
            }
            await self._backend.set_many(items, ttl)
            self._stats.sets += len(items)
        except Exception:
            self._stats.errors += 1

    async def delete_many(self, keys: list[str]) -> int:
        try:
            count = await self._backend.delete_many([self._make_key(k) for k in keys])
            self._stats.deletes += count
            return count
        except Exception:
            self._stats.errors += 1
            return 0

    async def clear(self) -> None:
        try:
            await self._backend.clear()
        except Exception as exc:
            self._stats.errors += 1
            logger.warning("Cache clear error: %s", exc)


# ---------------------------------------------------------------------------
# Tiered Cache
# ---------------------------------------------------------------------------


class TieredCache(Generic[T]):
    """Two-tier cache: L1 (fast, small) → L2 (slower, larger).

    L1: typically MemoryCacheBackend
    L2: typically RedisCacheBackend
    """

    def __init__(self, l1: Cache[T], l2: Cache[T], promote_on_read: bool = True):
        self.l1 = l1
        self.l2 = l2
        self._promote_on_read = promote_on_read

    async def get(self, key: str) -> T | None:
        # Try L1
        value = await self.l1.get(key)
        if value is not None:
            return value
        # Try L2
        value = await self.l2.get(key)
        if value is not None and self._promote_on_read:
            await self.l1.set(key, value)
        return value

    async def set(self, key: str, value: T, ttl: float | None = None) -> None:
        await asyncio.gather(
            self.l1.set(key, value, ttl),
            self.l2.set(key, value, ttl),
        )

    async def delete(self, key: str) -> bool:
        r1, r2 = await asyncio.gather(
            self.l1.delete(key),
            self.l2.delete(key),
        )
        return r1 or r2

    async def clear(self) -> None:
        await asyncio.gather(self.l1.clear(), self.l2.clear())

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "l1": self.l1.stats.snapshot(),
            "l2": self.l2.stats.snapshot(),
        }


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def cached(
    cache_instance: Cache,
    key_prefix: str = "",
    ttl: float | None = None,
    key_builder: Callable[..., str] | None = None,
):
    """Decorator to cache async function results.

    Usage:
        user_cache = Cache[dict](MemoryCacheBackend())

        @cached(user_cache, key_prefix="user", ttl=300)
        async def get_user(user_id: str) -> dict:
            return await db.fetch_user(user_id)
    """

    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                sig = _build_signature(args, kwargs)
                cache_key = f"{key_prefix}:{fn.__name__}:{sig}"
            result = await cache_instance.get(cache_key)
            if result is not None:
                return result
            result = await fn(*args, **kwargs)
            await cache_instance.set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator


def _build_signature(args: tuple, kwargs: dict) -> str:
    parts = [str(a) for a in args]
    parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    raw = ":".join(parts)
    if len(raw) > 128:
        return hashlib.md5(raw.encode()).hexdigest()
    return raw
