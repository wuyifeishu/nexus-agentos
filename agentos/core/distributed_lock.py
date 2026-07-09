"""AgentOS Distributed Lock — production-grade distributed mutex.

Backends:
- InMemoryLock: single-process (test/local dev)
- PostgresLock: advisory lock via pg_advisory_lock
- RedisLock: Redlock-inspired with TTL + renew

Design: ~340 lines, async-first, context-manager compatible.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Data types
# ============================================================================


class LockBackend(StrEnum):
    IN_MEMORY = "in_memory"
    POSTGRES = "postgres"
    REDIS = "redis"


@dataclass
class LockConfig:
    """Configuration for distributed lock acquisition."""

    ttl: float = 30.0  # Seconds until lock auto-expires
    retry_interval: float = 0.1  # Polling interval when waiting
    acquire_timeout: float = 10.0  # Max time to wait for lock
    renew_interval: float = 0.0  # Auto-renew interval (0 = disabled)


@dataclass
class LockToken:
    """Token representing a held lock — required to release."""

    key: str
    owner_id: str
    acquired_at: float
    ttl: float
    _backend: Any = field(repr=False)  # Backend reference for release


class LockAcquireError(Exception):
    """Failed to acquire lock within timeout."""


class LockNotHeldError(Exception):
    """Attempted to release a lock not held by this owner."""


# ============================================================================
# Abstract backend
# ============================================================================


class AbstractLockBackend(ABC):
    """Interface all lock backends must implement."""

    @abstractmethod
    async def acquire(self, key: str, owner_id: str, ttl: float) -> bool:
        """Try to acquire lock. Returns True on success."""

    @abstractmethod
    async def release(self, key: str, owner_id: str) -> bool:
        """Release lock. Returns True if this owner held it."""

    @abstractmethod
    async def extend(self, key: str, owner_id: str, ttl: float) -> bool:
        """Extend TTL. Returns True if this owner still holds it."""

    @abstractmethod
    async def is_held(self, key: str, owner_id: str) -> bool:
        """Check if this owner holds the lock."""


# ============================================================================
# In-Memory backend
# ============================================================================


class InMemoryLockBackend(AbstractLockBackend):
    """Single-process in-memory lock — for testing and single-worker scenarios."""

    def __init__(self):
        self._locks: dict[str, tuple[str, float]] = {}  # key → (owner_id, expiry)
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, owner_id: str, ttl: float) -> bool:
        async with self._lock:
            now = time.monotonic()
            if key in self._locks:
                owner, expiry = self._locks[key]
                if expiry > now and owner != owner_id:
                    return False
            self._locks[key] = (owner_id, now + ttl)
            return True

    async def release(self, key: str, owner_id: str) -> bool:
        async with self._lock:
            if key not in self._locks:
                return False
            owner, expiry = self._locks[key]
            if owner != owner_id:
                return False
            del self._locks[key]
            return True

    async def extend(self, key: str, owner_id: str, ttl: float) -> bool:
        async with self._lock:
            if key not in self._locks:
                return False
            owner, expiry = self._locks[key]
            if owner != owner_id:
                return False
            if expiry < time.monotonic():
                del self._locks[key]
                return False
            self._locks[key] = (owner_id, time.monotonic() + ttl)
            return True

    async def is_held(self, key: str, owner_id: str) -> bool:
        async with self._lock:
            if key not in self._locks:
                return False
            owner, expiry = self._locks[key]
            return owner == owner_id and expiry > time.monotonic()


# ============================================================================
# Postgres advisory lock backend
# ============================================================================

ADVISORY_LOCK_SQL = """
SELECT pg_try_advisory_lock(%s) AS acquired;
"""

ADVISORY_UNLOCK_SQL = """
SELECT pg_advisory_unlock(%s) AS released;
"""


# Hash key to an int64 for advisory lock
def _key_to_int64(key: str) -> int:
    import hashlib

    return int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) % (2**63 - 1)


class PostgresLockBackend(AbstractLockBackend):
    """PostgreSQL advisory-lock based backend.

    Uses pg_try_advisory_lock for non-blocking acquire.
    Client must provide a pool (asyncpg or similar) via _pool attribute.
    """

    def __init__(self, pool: Any = None):
        self._pool = pool
        self._acquired: set[tuple[str, str]] = set()  # (key, owner_id) tracking

    async def _get_conn(self):
        if self._pool is None:
            raise RuntimeError("PostgresLockBackend requires a pool")
        return await self._pool.acquire()

    async def acquire(self, key: str, owner_id: str, ttl: float) -> bool:
        conn = await self._get_conn()
        try:
            lock_id = _key_to_int64(key)
            result = await conn.fetchval("SELECT pg_try_advisory_lock($1) AS acquired;", lock_id)
            if result:
                self._acquired.add((key, owner_id))
                return True
            return False
        finally:
            await self._pool.release(conn)

    async def release(self, key: str, owner_id: str) -> bool:
        if (key, owner_id) not in self._acquired:
            return False
        conn = await self._get_conn()
        try:
            lock_id = _key_to_int64(key)
            result = await conn.fetchval("SELECT pg_advisory_unlock($1) AS released;", lock_id)
            if result:
                self._acquired.discard((key, owner_id))
            return bool(result)
        finally:
            await self._pool.release(conn)

    async def extend(self, key: str, owner_id: str, ttl: float) -> bool:
        # Advisory locks don't expire — always held until released
        return (key, owner_id) in self._acquired

    async def is_held(self, key: str, owner_id: str) -> bool:
        return (key, owner_id) in self._acquired


# ============================================================================
# Redis lock backend (Redlock-inspired)
# ============================================================================

SET_IF_NOT_EXISTS = """
local v = redis.call('GET', KEYS[1])
if v == false then
    redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
    return 1
end
return 0
"""

RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

EXTEND_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


class RedisLockBackend(AbstractLockBackend):
    """Redis-based distributed lock using Lua scripts for atomicity.

    Uses SET NX PX for acquire, Lua-scripted DEL for safe release.
    """

    def __init__(self, redis_client: Any):
        self._redis = redis_client

    async def acquire(self, key: str, owner_id: str, ttl: float) -> bool:
        result = await self._redis.set(key, owner_id, nx=True, px=int(ttl * 1000))
        return bool(result)

    async def release(self, key: str, owner_id: str) -> bool:
        script = (
            self._redis.register_script(RELEASE_SCRIPT)
            if hasattr(self._redis, "register_script")
            else None
        )
        if script:
            result = await script(keys=[key], args=[owner_id])
            return int(result) == 1
        # Fallback for sync redis clients
        current = await self._redis.get(key)
        if current and current.decode() if isinstance(current, bytes) else current == owner_id:
            return bool(await self._redis.delete(key))
        return False

    async def extend(self, key: str, owner_id: str, ttl: float) -> bool:
        current = await self._redis.get(key)
        owner = current.decode() if isinstance(current, bytes) else current
        if owner == owner_id:
            return bool(await self._redis.pexpire(key, int(ttl * 1000)))
        return False

    async def is_held(self, key: str, owner_id: str) -> bool:
        current = await self._redis.get(key)
        owner = current.decode() if isinstance(current, bytes) else current
        return owner == owner_id


# ============================================================================
# High-level Lock Manager
# ============================================================================


class DistributedLock:
    """High-level distributed lock with auto-renew and context manager support.

    Usage:
        lock = DistributedLock(backend, LockConfig(ttl=30))
        token = await lock.acquire("job:123")
        try:
            # critical section
        finally:
            await lock.release(token)

        # Context manager
        async with lock("job:123"):
            # critical section
    """

    def __init__(self, backend: AbstractLockBackend, config: LockConfig = LockConfig()):
        self._backend = backend
        self._config = config
        self._renew_tasks: dict[str, asyncio.Task] = {}

    async def acquire(self, key: str) -> LockToken:
        """Acquire lock, blocking up to acquire_timeout."""
        owner_id = uuid.uuid4().hex
        deadline = time.monotonic() + self._config.acquire_timeout

        while True:
            if await self._backend.acquire(key, owner_id, self._config.ttl):
                token = LockToken(
                    key=key,
                    owner_id=owner_id,
                    acquired_at=time.monotonic(),
                    ttl=self._config.ttl,
                    _backend=self,
                )
                if self._config.renew_interval > 0:
                    self._start_renew(key, owner_id)
                return token

            if time.monotonic() >= deadline:
                raise LockAcquireError(
                    f"Failed to acquire lock '{key}' within {self._config.acquire_timeout}s"
                )
            await asyncio.sleep(self._config.retry_interval)

    async def release(self, token: LockToken) -> bool:
        """Release a held lock."""
        if token.key in self._renew_tasks:
            self._renew_tasks.pop(token.key).cancel()
        return await self._backend.release(token.key, token.owner_id)

    async def extend(self, token: LockToken, ttl: float | None = None) -> bool:
        """Extend the TTL of a held lock."""
        return await self._backend.extend(token.key, token.owner_id, ttl or self._config.ttl)

    def _start_renew(self, key: str, owner_id: str):
        """Start auto-renew background task."""

        async def _renew():
            while True:
                await asyncio.sleep(self._config.renew_interval)
                ok = await self._backend.extend(key, owner_id, self._config.ttl)
                if not ok:
                    logger.warning("Lock renew failed for key=%s — lost ownership", key)
                    break

        self._renew_tasks[key] = asyncio.ensure_future(_renew())

    @asynccontextmanager
    async def __call__(self, key: str) -> AsyncIterator[LockToken]:
        token = await self.acquire(key)
        try:
            yield token
        finally:
            await self.release(token)


# ============================================================================
# Factory
# ============================================================================


def create_lock_backend(backend: LockBackend, **kwargs: Any) -> AbstractLockBackend:
    """Factory for creating lock backends."""
    if backend == LockBackend.IN_MEMORY:
        return InMemoryLockBackend()
    if backend == LockBackend.REDIS:
        redis_client = kwargs.get("redis_client")
        if redis_client is None:
            raise ValueError("RedisLockBackend requires 'redis_client'")
        return RedisLockBackend(redis_client)
    if backend == LockBackend.POSTGRES:
        pool = kwargs.get("pool")
        return PostgresLockBackend(pool=pool)
    raise ValueError(f"Unknown lock backend: {backend}")
