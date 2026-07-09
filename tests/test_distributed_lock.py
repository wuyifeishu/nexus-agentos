"""Tests for agentos.core.distributed_lock — 22 test cases."""

import asyncio

import pytest

from agentos.core.distributed_lock import (
    DistributedLock,
    InMemoryLockBackend,
    LockAcquireError,
    LockBackend,
    LockConfig,
    LockToken,
    PostgresLockBackend,
    create_lock_backend,
)

# ============================================================================
# InMemoryLockBackend
# ============================================================================

class TestInMemoryBackend:
    """Test InMemoryLockBackend."""

    @pytest.mark.asyncio
    async def test_acquire_success(self):
        backend = InMemoryLockBackend()
        ok = await backend.acquire("key1", "owner1", 30.0)
        assert ok is True

    @pytest.mark.asyncio
    async def test_acquire_conflict(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        ok = await backend.acquire("key1", "owner2", 30.0)
        assert ok is False

    @pytest.mark.asyncio
    async def test_acquire_same_owner_reentrant(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        ok = await backend.acquire("key1", "owner1", 30.0)
        assert ok is True

    @pytest.mark.asyncio
    async def test_release_owned(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        ok = await backend.release("key1", "owner1")
        assert ok is True

    @pytest.mark.asyncio
    async def test_release_not_owned(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        ok = await backend.release("key1", "owner2")
        assert ok is False

    @pytest.mark.asyncio
    async def test_release_nonexistent(self):
        backend = InMemoryLockBackend()
        ok = await backend.release("key1", "owner1")
        assert ok is False

    @pytest.mark.asyncio
    async def test_extend_ttl(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 1.0)
        ok = await backend.extend("key1", "owner1", 30.0)
        assert ok is True

    @pytest.mark.asyncio
    async def test_extend_not_owned(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        ok = await backend.extend("key1", "owner2", 30.0)
        assert ok is False

    @pytest.mark.asyncio
    async def test_extend_expired(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 0.01)
        await asyncio.sleep(0.05)
        ok = await backend.extend("key1", "owner1", 30.0)
        assert ok is False

    @pytest.mark.asyncio
    async def test_is_held(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 30.0)
        assert await backend.is_held("key1", "owner1") is True
        assert await backend.is_held("key1", "owner2") is False

    @pytest.mark.asyncio
    async def test_is_held_expired(self):
        backend = InMemoryLockBackend()
        await backend.acquire("key1", "owner1", 0.01)
        await asyncio.sleep(0.05)
        assert await backend.is_held("key1", "owner1") is False


# ============================================================================
# DistributedLock (high-level)
# ============================================================================

class TestDistributedLock:
    """Test DistributedLock high-level API."""

    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend, LockConfig(ttl=30.0))
        token = await lock.acquire("job:123")
        assert isinstance(token, LockToken)
        assert token.key == "job:123"

        released = await lock.release(token)
        assert released is True

    @pytest.mark.asyncio
    async def test_acquire_conflict(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend, LockConfig(ttl=30.0, acquire_timeout=0.5))

        token = await lock.acquire("key1")
        with pytest.raises(LockAcquireError):
            await lock.acquire("key1")

        await lock.release(token)

    @pytest.mark.asyncio
    async def test_context_manager(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend, LockConfig(ttl=30.0))

        async with lock("critical-section") as token:
            assert token.key == "critical-section"

        # Lock should be released after context exit
        token2 = await lock.acquire("critical-section")
        await lock.release(token2)

    @pytest.mark.asyncio
    async def test_extend_token(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend, LockConfig(ttl=1.0))
        token = await lock.acquire("key1")
        ok = await lock.extend(token, 30.0)
        assert ok is True
        await lock.release(token)

    @pytest.mark.asyncio
    async def test_release_invalid_token(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend, LockConfig(ttl=30.0))
        token = LockToken(key="x", owner_id="fake", acquired_at=0, ttl=30, _backend=lock)
        ok = await lock.release(token)
        assert ok is False

    @pytest.mark.asyncio
    async def test_parallel_acquisition_serialized(self):
        backend = InMemoryLockBackend()
        lock = DistributedLock(backend, LockConfig(ttl=30.0, acquire_timeout=5.0))
        acquired_order = []

        async def worker(name):
            async with lock("shared"):
                acquired_order.append(name)
                await asyncio.sleep(0.05)

        await asyncio.gather(worker("a"), worker("b"), worker("c"))
        assert len(acquired_order) == 3


# ============================================================================
# Factory
# ============================================================================

class TestFactory:
    """Test create_lock_backend factory."""

    def test_in_memory_factory(self):
        backend = create_lock_backend(LockBackend.IN_MEMORY)
        assert isinstance(backend, InMemoryLockBackend)

    def test_redis_no_client_raises(self):
        with pytest.raises(ValueError, match="redis_client"):
            create_lock_backend(LockBackend.REDIS)

    def test_postgres_factory(self):
        backend = create_lock_backend(LockBackend.POSTGRES, pool=None)
        assert isinstance(backend, PostgresLockBackend)

    def test_unknown_backend(self):
        with pytest.raises(ValueError):
            create_lock_backend("invalid_backend")


# ============================================================================
# _key_to_int64
# ============================================================================

class TestKeyToInt64:
    """Test advisory lock key hashing."""

    def test_deterministic(self):
        from agentos.core.distributed_lock import _key_to_int64
        a = _key_to_int64("hello")
        b = _key_to_int64("hello")
        assert a == b

    def test_different_keys(self):
        from agentos.core.distributed_lock import _key_to_int64
        a = _key_to_int64("hello")
        b = _key_to_int64("world")
        assert a != b

    def test_positive_range(self):
        from agentos.core.distributed_lock import _key_to_int64
        for key in ["a", "longer_key_name", "short", "12345"]:
            val = _key_to_int64(key)
            assert 0 <= val < 2**63 - 1
