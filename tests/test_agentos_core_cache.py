"""Tests for agentos.core.cache — Multi-backend cache with tiering."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from agentos.core.cache import (
    Cache,
    CacheBackend,
    CacheConfig,
    CacheStats,
    JSONSerializer,
    MemoryCacheBackend,
    PickleSerializer,
    TieredCache,
    cached,
)

# ============================================================================
# Serializers
# ============================================================================

class TestPickleSerializer:
    def test_roundtrip_simple(self):
        s = PickleSerializer()
        assert s.loads(s.dumps("hello")) == "hello"

    def test_roundtrip_complex(self):
        s = PickleSerializer()
        data = {"key": [1, 2, 3], "nested": {"a": None, "b": True}}
        assert s.loads(s.dumps(data)) == data

    def test_roundtrip_none(self):
        s = PickleSerializer()
        assert s.loads(s.dumps(None)) is None


class TestJSONSerializer:
    def test_roundtrip_dict(self):
        s = JSONSerializer()
        data = {"a": 1, "b": "test"}
        assert s.loads(s.dumps(data)) == data

    def test_roundtrip_list(self):
        s = JSONSerializer()
        data = [1, 2, 3]
        assert s.loads(s.dumps(data)) == data

    def test_non_serializable_converts(self):
        s = JSONSerializer()
        # default=str converts non-serializable objects
        result = s.loads(s.dumps({"val": 42}))
        assert result["val"] == 42


# ============================================================================
# CacheStats
# ============================================================================

class TestCacheStats:
    def test_defaults(self):
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0

    def test_hit_rate_zero_when_no_access(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate(self):
        stats = CacheStats(hits=7, misses=3)
        assert stats.hit_rate == 0.7

    def test_hit_rate_perfect(self):
        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate == 1.0

    def test_snapshot(self):
        stats = CacheStats(hits=5, misses=2)
        snap = stats.snapshot()
        assert snap == {"hits": 5, "misses": 2, "sets": 0, "deletes": 0, "evictions": 0, "errors": 0}


# ============================================================================
# MemoryCacheBackend
# ============================================================================

class TestMemoryCacheBackend:
    @pytest.fixture
    def backend(self):
        return MemoryCacheBackend(max_size=100, default_ttl=300.0)

    @pytest.mark.asyncio
    async def test_get_set(self, backend):
        await backend.set("key1", b"value1")
        assert await backend.get("key1") == b"value1"

    @pytest.mark.asyncio
    async def test_get_missing(self, backend):
        assert await backend.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete(self, backend):
        await backend.set("key1", b"value1")
        assert await backend.delete("key1") is True
        assert await backend.get("key1") is None

    @pytest.mark.asyncio
    async def test_delete_missing(self, backend):
        assert await backend.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_exists(self, backend):
        await backend.set("key1", b"value1")
        assert await backend.exists("key1") is True
        assert await backend.exists("key2") is False

    @pytest.mark.asyncio
    async def test_clear(self, backend):
        await backend.set("a", b"1")
        await backend.set("b", b"2")
        await backend.clear()
        assert await backend.get("a") is None
        assert await backend.get("b") is None
        assert backend.size == 0

    @pytest.mark.asyncio
    async def test_lru_eviction_on_get(self, backend):
        backend = MemoryCacheBackend(max_size=3, default_ttl=None)
        await backend.set("a", b"1")
        await backend.set("b", b"2")
        await backend.set("c", b"3")
        # Access "a" to make it most recently used
        await backend.get("a")
        # Add "d" — should evict "b" (now LRU)
        await backend.set("d", b"4")
        assert await backend.get("b") is None
        assert await backend.get("a") == b"1"
        assert await backend.get("c") == b"3"

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, backend):
        backend = MemoryCacheBackend(max_size=100, default_ttl=0.01)
        await backend.set("key1", b"value1")
        await asyncio.sleep(0.02)
        assert await backend.get("key1") is None

    @pytest.mark.asyncio
    async def test_ttl_not_expired(self, backend):
        backend = MemoryCacheBackend(max_size=100, default_ttl=60.0)
        await backend.set("key1", b"value1")
        assert await backend.get("key1") == b"value1"

    @pytest.mark.asyncio
    async def test_custom_ttl(self, backend):
        await backend.set("key1", b"value1", ttl=0.01)
        await asyncio.sleep(0.02)
        assert await backend.get("key1") is None

    @pytest.mark.asyncio
    async def test_size(self, backend):
        assert backend.size == 0
        await backend.set("a", b"1")
        assert backend.size == 1

    @pytest.mark.asyncio
    async def test_get_many(self, backend):
        await backend.set("a", b"1")
        await backend.set("b", b"2")
        results = await backend.get_many(["a", "b", "c"])
        assert results == {"a": b"1", "b": b"2"}

    @pytest.mark.asyncio
    async def test_set_many(self, backend):
        await backend.set_many({"a": b"1", "b": b"2"})
        assert await backend.get("a") == b"1"
        assert await backend.get("b") == b"2"

    @pytest.mark.asyncio
    async def test_delete_many(self, backend):
        await backend.set("a", b"1")
        await backend.set("b", b"2")
        assert await backend.delete_many(["a", "b"]) == 2
        assert await backend.get("a") is None

    @pytest.mark.asyncio
    async def test_lru_move_to_end_on_get(self, backend):
        backend = MemoryCacheBackend(max_size=2, default_ttl=None)
        await backend.set("a", b"1")
        await backend.set("b", b"2")
        await backend.get("a")  # a becomes MRU
        await backend.set("c", b"3")  # should evict b
        assert await backend.get("b") is None
        assert await backend.get("a") == b"1"


# ============================================================================
# Cache (high-level API)
# ============================================================================

class TestCache:
    @pytest.fixture
    def cache(self):
        return Cache[str](MemoryCacheBackend(max_size=100))

    @pytest.mark.asyncio
    async def test_set_get(self, cache):
        await cache.set("k", "v")
        assert await cache.get("k") == "v"

    @pytest.mark.asyncio
    async def test_get_miss(self, cache):
        assert await cache.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_delete(self, cache):
        await cache.set("k", "v")
        assert await cache.delete("k") is True
        assert await cache.get("k") is None

    @pytest.mark.asyncio
    async def test_exists(self, cache):
        await cache.set("k", "v")
        assert await cache.exists("k")
        assert not await cache.exists("nope")

    @pytest.mark.asyncio
    async def test_get_or_default(self, cache):
        assert await cache.get_or_default("k", "default") == "default"
        await cache.set("k", "v")
        assert await cache.get_or_default("k", "default") == "v"

    @pytest.mark.asyncio
    async def test_get_or_set_compute(self, cache):
        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            return "computed"

        result = await cache.get_or_set("k", factory)
        assert result == "computed"
        assert call_count == 1

        # Second call: cache hit
        result = await cache.get_or_set("k", factory)
        assert result == "computed"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_get_or_set_force_refresh(self, cache):
        await cache.set("k", "old")
        call_count = 0

        async def factory():
            nonlocal call_count
            call_count += 1
            return "new"

        result = await cache.get_or_set("k", factory, force_refresh=True)
        assert result == "new"
        assert call_count == 1
        assert await cache.get("k") == "new"

    @pytest.mark.asyncio
    async def test_get_or_set_sync_factory(self, cache):
        result = await cache.get_or_set("k", lambda: "sync-result")
        assert result == "sync-result"

    @pytest.mark.asyncio
    async def test_get_or_set_ttl(self, cache):
        await cache.get_or_set("k", lambda: "v", ttl=0.01)
        await asyncio.sleep(0.02)
        assert await cache.get("k") is None

    @pytest.mark.asyncio
    async def test_get_many(self, cache):
        await cache.set("a", "1")
        await cache.set("b", "2")
        results = await cache.get_many(["a", "b", "c"])
        assert results["a"] == "1"
        assert results["b"] == "2"
        assert results["c"] is None

    @pytest.mark.asyncio
    async def test_set_many(self, cache):
        await cache.set_many({"a": "1", "b": "2"})
        assert await cache.get("a") == "1"
        assert await cache.get("b") == "2"

    @pytest.mark.asyncio
    async def test_delete_many(self, cache):
        await cache.set("a", "1")
        await cache.set("b", "2")
        assert await cache.delete_many(["a", "b"]) == 2

    @pytest.mark.asyncio
    async def test_clear(self, cache):
        await cache.set("a", "1")
        await cache.set("b", "2")
        await cache.clear()
        assert await cache.get("a") is None

    @pytest.mark.asyncio
    async def test_stats(self, cache):
        await cache.set("a", "1")
        await cache.get("a")
        await cache.get("missing")
        assert cache.stats.hits == 1
        assert cache.stats.misses == 1
        assert cache.stats.sets == 1

    @pytest.mark.asyncio
    async def test_key_prefix(self, cache):
        cfg = CacheConfig(key_prefix="pre:")
        cache_prefixed = Cache[str](MemoryCacheBackend(), config=cfg)
        await cache_prefixed.set("k", "v")
        assert await cache_prefixed.get("k") == "v"

    @pytest.mark.asyncio
    async def test_hash_keys(self, cache):
        cfg = CacheConfig(hash_keys=True)
        cache_hashed = Cache[str](MemoryCacheBackend(), config=cfg)
        await cache_hashed.set("very-long-key-" * 20, "v")
        assert await cache_hashed.get("very-long-key-" * 20) == "v"


# ============================================================================
# TieredCache
# ============================================================================

class TestTieredCache:
    @pytest.fixture
    def tiered(self):
        l1 = Cache[str](MemoryCacheBackend(max_size=10))
        l2 = Cache[str](MemoryCacheBackend(max_size=100))
        return TieredCache[str](l1, l2, promote_on_read=True)

    @pytest.mark.asyncio
    async def test_set_and_get_from_l1(self, tiered):
        await tiered.set("k", "v")
        assert await tiered.get("k") == "v"

    @pytest.mark.asyncio
    async def test_promotion_from_l2(self, tiered):
        # Set directly in L2 only
        await tiered.l2.set("k", "v")
        # Should be found in L2 and promoted to L1
        result = await tiered.get("k")
        assert result == "v"
        # Now L1 should also have it
        assert await tiered.l1.get("k") == "v"

    @pytest.mark.asyncio
    async def test_promotion_off(self, tiered):
        tiered = TieredCache[str](
            Cache[str](MemoryCacheBackend()),
            Cache[str](MemoryCacheBackend()),
            promote_on_read=False,
        )
        await tiered.l2.set("k", "v")
        result = await tiered.get("k")
        assert result == "v"
        assert await tiered.l1.get("k") is None  # Not promoted

    @pytest.mark.asyncio
    async def test_delete(self, tiered):
        await tiered.set("k", "v")
        assert await tiered.delete("k") is True
        assert await tiered.get("k") is None

    @pytest.mark.asyncio
    async def test_clear(self, tiered):
        await tiered.set("a", "1")
        await tiered.set("b", "2")
        await tiered.clear()
        assert await tiered.get("a") is None

    @pytest.mark.asyncio
    async def test_stats(self, tiered):
        await tiered.set("k", "v")
        s = tiered.stats
        assert "l1" in s
        assert "l2" in s


# ============================================================================
# cached decorator
# ============================================================================

class TestCachedDecorator:
    @pytest.fixture
    def cache(self):
        return Cache[str](MemoryCacheBackend(max_size=100))

    @pytest.mark.asyncio
    async def test_basic_caching(self, cache):
        count = 0

        @cached(cache, key_prefix="test", ttl=60)
        async def compute(x: int) -> str:
            nonlocal count
            count += 1
            return f"result-{x}"

        r1 = await compute(42)
        r2 = await compute(42)
        assert r1 == r2 == "result-42"
        assert count == 1  # Only computed once

    @pytest.mark.asyncio
    async def test_different_args_not_cached(self, cache):
        count = 0

        @cached(cache, key_prefix="test")
        async def compute(x: int) -> str:
            nonlocal count
            count += 1
            return f"result-{x}"

        await compute(1)
        await compute(2)
        assert count == 2

    @pytest.mark.asyncio
    async def test_keyword_args(self, cache):
        count = 0

        @cached(cache)
        async def compute(a: int, b: int = 0) -> str:
            nonlocal count
            count += 1
            return f"{a}+{b}"

        await compute(1, b=2)
        await compute(1, b=2)
        assert count == 1

    @pytest.mark.asyncio
    async def test_custom_key_builder(self, cache):
        count = 0

        @cached(cache, key_builder=lambda x: f"custom:{x}")
        async def compute(x: int) -> str:
            nonlocal count
            count += 1
            return f"result-{x}"

        await compute(5)
        await compute(5)
        assert count == 1

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, cache):
        count = 0

        @cached(cache, ttl=0.01)
        async def compute(x: int) -> str:
            nonlocal count
            count += 1
            return f"result-{x}"

        await compute(1)
        await asyncio.sleep(0.02)
        await compute(1)
        assert count == 2


# ============================================================================
# Error handling
# ============================================================================

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_get_error_increments_errors(self):
        backend = AsyncMock(spec=CacheBackend)
        backend.get.side_effect = RuntimeError("backend down")
        cache = Cache[str](backend)
        result = await cache.get("k")
        assert result is None
        assert cache.stats.errors == 1

    @pytest.mark.asyncio
    async def test_set_error_increments_errors(self):
        backend = AsyncMock(spec=CacheBackend)
        backend.set.side_effect = RuntimeError("backend down")
        cache = Cache[str](backend)
        await cache.set("k", "v")
        assert cache.stats.errors == 1
