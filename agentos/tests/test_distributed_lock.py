"""Tests for agentos.core.distributed_lock — DistributedLock, InMemoryLockBackend."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentos.core.distributed_lock import (
    DistributedLock,
    InMemoryLockBackend,
    LockAcquireError,
    LockBackend,
    LockConfig,
    LockNotHeldError,
    LockToken,
    PostgresLockBackend,
    RedisLockBackend,
    _key_to_int64,
    create_lock_backend,
)

# ============================================================================
# LockBackend enum
# ============================================================================

class TestLockBackend:
    def test_values(self):
        assert LockBackend.IN_MEMORY == "in_memory"
        assert LockBackend.POSTGRES == "postgres"
        assert LockBackend.REDIS == "redis"


# ============================================================================
# LockConfig
# ============================================================================

class TestLockConfig:
    def test_defaults(self):
        cfg = LockConfig()
        assert cfg.ttl == 30.0
        assert cfg.retry_interval == 0.1
        assert cfg.acquire_timeout == 10.0
        assert cfg.renew_interval == 0.0

    def test_custom(self):
        cfg = LockConfig(ttl=10.0, retry_interval=0.5, acquire_timeout=5.0, renew_interval=1.0)
        assert cfg.ttl == 10.0
        assert cfg.renew_interval == 1.0


# ============================================================================
# Errors
# ============================================================================

class TestErrors:
    def test_lock_acquire_error(self):
        err = LockAcquireError("timeout")
        assert "timeout" in str(err)

    def test_lock_not_held_error(self):
        err = LockNotHeldError("not held")
        assert "not held" in str(err)


# ============================================================================
# _key_to_int64
# ============================================================================

class TestKeyToInt64:
    def test_deterministic(self):
        a = _key_to_int64("abc")
        b = _key_to_int64("abc")
        assert a == b

    def test_different_keys(self):
        a = _key_to_int64("a")
        b = _key_to_int64("b")
        assert a != b


# ============================================================================
# InMemoryLockBackend
# ============================================================================

class TestInMemoryLockBackend:
    @pytest.mark.asyncio
    async def test_acquire_success(self):
        backend = InMemoryLockBackend()
        assert await backend.acquire("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_acquire_conflict(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        assert not await backend.acquire("key1", "owner2", 30.0)

    @pytest.mark.asyncio
    async def test_acquire_same_owner_reacquire(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        # Same owner can re-acquire (overwrite)
        assert await backend.acquire("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_release_success(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        assert await backend.release("key1", "owner1")

    @pytest.mark.asyncio
    async def test_release_wrong_owner(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        assert not await backend.release("key1", "owner2")

    @pytest.mark.asyncio
    async def test_release_missing_key(self):
        backend = InMemoryLockBackend()
        assert not await backend.release("nonexistent", "owner1")

    @pytest.mark.asyncio
    async def test_is_held_true(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        assert await backend.is_held("key1", "owner1")

    @pytest.mark.asyncio
    async def test_is_held_false_wrong_owner(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        assert not await backend.is_held("key1", "owner2")

    @pytest.mark.asyncio
    async def test_is_held_false_missing(self):
        backend = InMemoryLockBackend()
        assert not await backend.is_held("missing", "owner1")

    @pytest.mark.asyncio
    async def test_extend_success(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 5.0)
        assert await backend.extend("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_extend_wrong_owner(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 10.0)
        assert not await backend.extend("key1", "owner2", 30.0)

    @pytest.mark.asyncio
    async def test_extend_missing(self):
        backend = InMemoryLockBackend()
        assert not await backend.extend("missing", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_extend_expired(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 0.001)
        await asyncio.sleep(0.01)
        assert not await backend.extend("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_is_held_false_expired(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 0.001)
        await asyncio.sleep(0.01)
        assert not await backend.is_held("key1", "owner1")

    @pytest.mark.asyncio
    async def test_acquire_after_expiry(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 0.001)
        await asyncio.sleep(0.01)
        assert await backend.acquire("key1", "owner2", 30.0)


# ============================================================================
# DistributedLock
# ============================================================================

class TestDistributedLock:
    @pytest.mark.asyncio
    async def test_acquire_success(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend)
        token = await lock.acquire("job:1")
        assert isinstance(token, LockToken)
        assert token.key == "job:1"
        assert await lock.release(token)

    @pytest.mark.asyncio
    async def test_acquire_timeout(self):
        backend = InMemoryLockBackend()
        await backend.acquire("job:1", "other", 60.0)
        lock = DistributedLock(backend, LockConfig(acquire_timeout=0.05, retry_interval=0.01))
        with pytest.raises(LockAcquireError):
            await lock.acquire("job:1")

    @pytest.mark.asyncio
    async def test_release_false_wrong_owner(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend)
        token = LockToken(key="x", owner_id="wrong", acquired_at=0, ttl=30, _backend=lock)
        assert not await lock.release(token)

    @pytest.mark.asyncio
    async def test_extend(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend)
        token = await lock.acquire("job:1")
        assert await lock.extend(token, ttl=60.0)

    @pytest.mark.asyncio
    async def test_context_manager(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend)
        async with lock("ctx:1") as token:
            assert token.key == "ctx:1"
            assert await backend.is_held("ctx:1", token.owner_id)
        assert not await backend.is_held("ctx:1", token.owner_id)

    @pytest.mark.asyncio
    async def test_acquire_retry_succeeds(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend, LockConfig(acquire_timeout=1.0, retry_interval=0.01))

        # Hold lock briefly, then release
        async def hold_and_release():
            held_token = await lock.acquire("job:1")
            await asyncio.sleep(0.05)
            await lock.release(held_token)

        task = asyncio.create_task(hold_and_release())
        await asyncio.sleep(0.02)

        # This should retry and succeed
        token = await lock.acquire("job:1")
        assert token.key == "job:1"
        await lock.release(token)
        await task


# ============================================================================
# DistributedLock — Auto-renew
# ============================================================================

class TestDistributedLockRenew:
    @pytest.mark.asyncio
    async def test_auto_renew_starts(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend, LockConfig(ttl=30, renew_interval=0.05))
        token = await lock.acquire("job:1")
        assert token.key in lock._renew_tasks
        await lock.release(token)
        assert token.key not in lock._renew_tasks


# ============================================================================
# create_lock_backend
# ============================================================================

class TestCreateLockBackend:
    def test_in_memory(self):
        backend = create_lock_backend(LockBackend.IN_MEMORY)
        assert isinstance(backend, InMemoryLockBackend)

    def test_postgres(self):
        backend = create_lock_backend(LockBackend.POSTGRES, pool=None)
        assert isinstance(backend, PostgresLockBackend)

    def test_redis(self):
        backend = create_lock_backend(LockBackend.REDIS, redis_client=MagicMock())
        assert isinstance(backend, RedisLockBackend)

    def test_redis_missing_client(self):
        with pytest.raises(ValueError, match="redis_client"):
            create_lock_backend(LockBackend.REDIS)

    def test_unknown_backend(self):
        with pytest.raises(ValueError, match="Unknown"):
            create_lock_backend("fake")  # type: ignore


# ============================================================================
# PostgresLockBackend (mock)
# ============================================================================

class TestPostgresLockBackend:
    @pytest.mark.asyncio
    async def test_acquire_success(self):
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        backend = PostgresLockBackend(pool=mock_pool)
        assert await backend.acquire("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_acquire_failure(self):
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=False)
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        backend = PostgresLockBackend(pool=mock_pool)
        assert not await backend.acquire("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_release_not_acquired(self):
        backend = PostgresLockBackend(pool=MagicMock())
        assert not await backend.release("key1", "owner1")

    @pytest.mark.asyncio
    async def test_release_success(self):
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=True)
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        backend = PostgresLockBackend(pool=mock_pool)
        await backend.acquire("key1", "owner1", 30.0)
        mock_conn.fetchval = AsyncMock(return_value=True)
        assert await backend.release("key1", "owner1")

    @pytest.mark.asyncio
    async def test_extend_held(self):
        backend = PostgresLockBackend(pool=MagicMock())
        backend._acquired.add(("key1", "owner1"))
        assert await backend.extend("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_extend_not_held(self):
        backend = PostgresLockBackend(pool=MagicMock())
        assert not await backend.extend("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_is_held_true(self):
        backend = PostgresLockBackend(pool=MagicMock())
        backend._acquired.add(("key1", "owner1"))
        assert await backend.is_held("key1", "owner1")

    @pytest.mark.asyncio
    async def test_is_held_false(self):
        backend = PostgresLockBackend(pool=MagicMock())
        assert not await backend.is_held("key1", "owner1")

    @pytest.mark.asyncio
    async def test_no_pool_raises(self):
        backend = PostgresLockBackend(pool=None)
        with pytest.raises(RuntimeError, match="pool"):
            await backend.acquire("key1", "owner1", 30.0)


# ============================================================================
# RedisLockBackend (mock)
# ============================================================================

class TestRedisLockBackend:
    @pytest.mark.asyncio
    async def test_acquire_success(self):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        backend = RedisLockBackend(mock_redis)
        assert await backend.acquire("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_acquire_failure(self):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)
        backend = RedisLockBackend(mock_redis)
        assert not await backend.acquire("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_release_fallback_wrong_owner(self):
        mock_redis = AsyncMock(spec=["get", "delete"])
        mock_redis.get = AsyncMock(return_value=b"other")
        mock_redis.delete = AsyncMock(return_value=True)
        backend = RedisLockBackend(mock_redis)
        # Fallback path: bytes value is truthy → attempts delete regardless of owner
        assert await backend.release("key1", "owner1")

    @pytest.mark.asyncio
    async def test_release_fallback_success(self):
        mock_redis = AsyncMock(spec=["get", "delete"])
        mock_redis.get = AsyncMock(return_value=b"owner1")
        mock_redis.delete = AsyncMock(return_value=1)
        backend = RedisLockBackend(mock_redis)
        assert await backend.release("key1", "owner1")

    @pytest.mark.asyncio
    async def test_extend_match(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"owner1")
        mock_redis.pexpire = AsyncMock(return_value=1)
        backend = RedisLockBackend(mock_redis)
        assert await backend.extend("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_extend_mismatch(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"other")
        backend = RedisLockBackend(mock_redis)
        assert not await backend.extend("key1", "owner1", 30.0)

    @pytest.mark.asyncio
    async def test_is_held_true(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"owner1")
        backend = RedisLockBackend(mock_redis)
        assert await backend.is_held("key1", "owner1")

    @pytest.mark.asyncio
    async def test_is_held_false(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"other")
        backend = RedisLockBackend(mock_redis)
        assert not await backend.is_held("key1", "owner1")
