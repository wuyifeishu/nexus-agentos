"""Tests for agentos.core.cache — MemoryCacheBackend, Cache, TieredCache, Serializers."""

import asyncio

import pytest

from agentos.core.cache import (
    Cache,
    CacheConfig,
    CacheStats,
    JSONSerializer,
    MemoryCacheBackend,
    PickleSerializer,
    RedisCacheBackend,
    TieredCache,
    _build_signature,
    cached,
)

# ============================================================================
# CacheStats
# ============================================================================

class TestCacheStats:
    def test_hit_rate_empty(self):
        s = CacheStats()
        assert s.hit_rate == 0.0

    def test_hit_rate_half(self):
        s = CacheStats(hits=5, misses=5)
        assert s.hit_rate == 0.5

    def test_hit_rate_all_hits(self):
        s = CacheStats(hits=10)
        assert s.hit_rate == 1.0

    def test_snapshot(self):
        s = CacheStats(hits=3, misses=2, errors=1)
        snap = s.snapshot()
        assert snap == {"hits": 3, "misses": 2, "sets": 0, "deletes": 0, "evictions": 0, "errors": 1}


# ============================================================================
# Serializers
# ============================================================================

class TestPickleSerializer:
    def test_roundtrip(self):
        s = PickleSerializer()
        data = {"hello": [1, 2, 3], "nested": {"a": True}}
        raw = s.dumps(data)
        assert s.loads(raw) == data

    def test_primitives(self):
        s = PickleSerializer()
        assert s.loads(s.dumps(42)) == 42
        assert s.loads(s.dumps("hello")) == "hello"


class TestJSONSerializer:
    def test_roundtrip(self):
        s = JSONSerializer()
        data = {"hello": "world", "n": 123}
        raw = s.dumps(data)
        assert s.loads(raw) == data

    def test_default_str(self):
        s = JSONSerializer()
        # bytes aren't JSON-serializable; default=str uses repr
        raw = s.dumps({"key": b"value"})
        result = s.loads(raw)
        assert isinstance(result["key"], str)


# ============================================================================
# MemoryCacheBackend
# ============================================================================

class TestMemoryCacheBackend:
    @pytest.mark.asyncio
    async def test_set_get(self):
        b = MemoryCacheBackend()
        await b.set("k", b"v")
        assert await b.get("k") == b"v"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        b = MemoryCacheBackend()
        assert await b.get("missing") is None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        b = MemoryCacheBackend(default_ttl=0.001)
        await b.set("k", b"v")
        await asyncio.sleep(0.01)
        assert await b.get("k") is None

    @pytest.mark.asyncio
    async def test_custom_ttl(self):
        b = MemoryCacheBackend(default_ttl=60)
        await b.set("k", b"v", ttl=0.001)
        await asyncio.sleep(0.01)
        assert await b.get("k") is None

    @pytest.mark.asyncio
    async def test_no_ttl(self):
        b = MemoryCacheBackend(default_ttl=None)
        await b.set("k", b"v")
        await asyncio.sleep(0.01)
        assert await b.get("k") == b"v"

    @pytest.mark.asyncio
    async def test_delete(self):
        b = MemoryCacheBackend()
        await b.set("k", b"v")
        assert await b.delete("k") is True
        assert await b.get("k") is None

    @pytest.mark.asyncio
    async def test_delete_missing(self):
        b = MemoryCacheBackend()
        assert await b.delete("missing") is False

    @pytest.mark.asyncio
    async def test_exists(self):
        b = MemoryCacheBackend()
        await b.set("k", b"v")
        assert await b.exists("k") is True
        assert await b.exists("missing") is False

    @pytest.mark.asyncio
    async def test_clear(self):
        b = MemoryCacheBackend()
        await b.set("a", b"1")
        await b.set("b", b"2")
        await b.clear()
        assert await b.get("a") is None
        assert await b.get("b") is None

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        b = MemoryCacheBackend(max_size=2)
        await b.set("a", b"1")
        await b.set("b", b"2")
        await b.set("c", b"3")
        assert await b.get("a") is None  # evicted
        assert await b.get("b") == b"2"
        assert await b.get("c") == b"3"

    @pytest.mark.asyncio
    async def test_lru_promotion(self):
        b = MemoryCacheBackend(max_size=2)
        await b.set("a", b"1")
        await b.set("b", b"2")
        await b.get("a")  # promote a
        await b.set("c", b"3")
        assert await b.get("a") == b"1"  # not evicted
        assert await b.get("b") is None  # evicted

    @pytest.mark.asyncio
    async def test_size(self):
        b = MemoryCacheBackend(max_size=100)
        await b.set("a", b"1")
        await b.set("b", b"2")
        assert b.size == 2

    @pytest.mark.asyncio
    async def test_get_many(self):
        b = MemoryCacheBackend()
        await b.set("a", b"1")
        await b.set("b", b"2")
        result = await b.get_many(["a", "b", "c"])
        assert result == {"a": b"1", "b": b"2"}

    @pytest.mark.asyncio
    async def test_set_many(self):
        b = MemoryCacheBackend()
        await b.set_many({"a": b"1", "b": b"2"})
        assert await b.get("a") == b"1"
        assert await b.get("b") == b"2"

    @pytest.mark.asyncio
    async def test_delete_many(self):
        b = MemoryCacheBackend()
        await b.set("a", b"1")
        await b.set("b", b"2")
        count = await b.delete_many(["a", "b", "c"])
        assert count == 2
        assert await b.get("a") is None


# ============================================================================
# Cache (high-level API)
# ============================================================================

class TestCache:
    @pytest.mark.asyncio
    async def test_set_get(self):
        c = Cache[str](MemoryCacheBackend())
        await c.set("k", "hello")
        assert await c.get("k") == "hello"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        c = Cache[int](MemoryCacheBackend())
        assert await c.get("k") is None

    @pytest.mark.asyncio
    async def test_exists(self):
        c = Cache[str](MemoryCacheBackend())
        await c.set("k", "v")
        assert await c.exists("k")
        assert not await c.exists("missing")

    @pytest.mark.asyncio
    async def test_delete(self):
        c = Cache[str](MemoryCacheBackend())
        await c.set("k", "v")
        assert await c.delete("k")
        assert await c.get("k") is None

    @pytest.mark.asyncio
    async def test_clear(self):
        c = Cache[str](MemoryCacheBackend())
        await c.set("a", "1")
        await c.set("b", "2")
        await c.clear()
        assert await c.get("a") is None

    @pytest.mark.asyncio
    async def test_get_or_default(self):
        c = Cache[str](MemoryCacheBackend())
        assert await c.get_or_default("k", "default") == "default"
        await c.set("k", "real")
        assert await c.get_or_default("k", "default") == "real"

    @pytest.mark.asyncio
    async def test_get_or_set(self):
        c = Cache[int](MemoryCacheBackend())
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return 42

        v1 = await c.get_or_set("k", factory)
        v2 = await c.get_or_set("k", factory)
        assert v1 == 42
        assert v2 == 42
        assert call_count == 1  # factory called once

    @pytest.mark.asyncio
    async def test_get_or_set_force_refresh(self):
        c = Cache[int](MemoryCacheBackend())
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return call_count

        await c.set("k", 0)
        v = await c.get_or_set("k", factory, force_refresh=True)
        assert v == 1

    @pytest.mark.asyncio
    async def test_get_or_set_async_factory(self):
        c = Cache[int](MemoryCacheBackend())

        async def factory():
            return 99

        v = await c.get_or_set("k", factory)
        assert v == 99

    @pytest.mark.asyncio
    async def test_stats(self):
        c = Cache[str](MemoryCacheBackend())
        await c.set("a", "1")
        await c.get("a")
        await c.get("missing")
        assert c.stats.hits == 1
        assert c.stats.misses == 1
        assert c.stats.sets == 1

    @pytest.mark.asyncio
    async def test_key_prefix(self):
        config = CacheConfig(key_prefix="pfx:")
        c = Cache[str](MemoryCacheBackend(), config)
        await c.set("k", "v")
        assert await c.get("k") == "v"

    @pytest.mark.asyncio
    async def test_hash_keys(self):
        config = CacheConfig(hash_keys=True)
        c = Cache[str](MemoryCacheBackend(), config)
        await c.set("very_long_key" * 10, "v")
        assert await c.get("very_long_key" * 10) == "v"

    @pytest.mark.asyncio
    async def test_get_many(self):
        c = Cache[str](MemoryCacheBackend())
        await c.set("a", "1")
        await c.set("b", "2")
        result = await c.get_many(["a", "b", "c"])
        assert result == {"a": "1", "b": "2", "c": None}

    @pytest.mark.asyncio
    async def test_set_many(self):
        c = Cache[str](MemoryCacheBackend())
        await c.set_many({"a": "1", "b": "2"})
        assert await c.get("a") == "1"
        assert await c.get("b") == "2"

    @pytest.mark.asyncio
    async def test_delete_many(self):
        c = Cache[str](MemoryCacheBackend())
        await c.set("a", "1")
        await c.set("b", "2")
        count = await c.delete_many(["a", "b", "c"])
        assert count == 2

    @pytest.mark.asyncio
    async def test_json_serializer(self):
        config = CacheConfig(serializer=JSONSerializer())
        c = Cache[dict](MemoryCacheBackend(), config)
        await c.set("k", {"a": 1})
        assert await c.get("k") == {"a": 1}

    @pytest.mark.asyncio
    async def test_pickle_complex(self):
        c = Cache[dict](MemoryCacheBackend())
        await c.set("k", {"nested": {1, 2, 3}})
        assert await c.get("k") == {"nested": {1, 2, 3}}


# ============================================================================
# TieredCache
# ============================================================================

class TestTieredCache:
    @pytest.mark.asyncio
    async def test_get_l1_hit(self):
        l1 = Cache[int](MemoryCacheBackend())
        l2 = Cache[int](MemoryCacheBackend())
        tc = TieredCache(l1, l2)
        await l1.set("k", 1)
        assert await tc.get("k") == 1

    @pytest.mark.asyncio
    async def test_get_l2_fallback_and_promote(self):
        l1 = Cache[int](MemoryCacheBackend())
        l2 = Cache[int](MemoryCacheBackend())
        tc = TieredCache(l1, l2)
        await l2.set("k", 42)
        # Not in L1, should hit L2 and promote
        assert await tc.get("k") == 42
        assert await l1.get("k") == 42  # promoted

    @pytest.mark.asyncio
    async def test_get_l2_no_promote(self):
        l1 = Cache[int](MemoryCacheBackend())
        l2 = Cache[int](MemoryCacheBackend())
        tc = TieredCache(l1, l2, promote_on_read=False)
        await l2.set("k", 42)
        assert await tc.get("k") == 42
        assert await l1.get("k") is None  # not promoted

    @pytest.mark.asyncio
    async def test_set(self):
        l1 = Cache[int](MemoryCacheBackend())
        l2 = Cache[int](MemoryCacheBackend())
        tc = TieredCache(l1, l2)
        await tc.set("k", 99)
        assert await l1.get("k") == 99
        assert await l2.get("k") == 99

    @pytest.mark.asyncio
    async def test_delete(self):
        l1 = Cache[int](MemoryCacheBackend())
        l2 = Cache[int](MemoryCacheBackend())
        tc = TieredCache(l1, l2)
        await tc.set("k", 1)
        assert await tc.delete("k")
        assert await l1.get("k") is None
        assert await l2.get("k") is None

    @pytest.mark.asyncio
    async def test_clear(self):
        l1 = Cache[int](MemoryCacheBackend())
        l2 = Cache[int](MemoryCacheBackend())
        tc = TieredCache(l1, l2)
        await tc.set("a", 1)
        await tc.clear()
        assert await l1.get("a") is None

    @pytest.mark.asyncio
    async def test_stats(self):
        l1 = Cache[int](MemoryCacheBackend())
        l2 = Cache[int](MemoryCacheBackend())
        tc = TieredCache(l1, l2)
        stats = tc.stats
        assert "l1" in stats
        assert "l2" in stats


# ============================================================================
# cached decorator
# ============================================================================

class TestCachedDecorator:
    @pytest.mark.asyncio
    async def test_cached(self):
        c = Cache[int](MemoryCacheBackend())
        call_count = 0

        @cached(c, key_prefix="test")
        async def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        v1 = await compute(5)
        v2 = await compute(5)
        assert v1 == 10
        assert v2 == 10
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_different_args_bypass_cache(self):
        c = Cache[int](MemoryCacheBackend())
        call_count = 0

        @cached(c)
        async def compute(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        await compute(1)
        await compute(2)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_custom_key_builder(self):
        c = Cache[str](MemoryCacheBackend())
        call_count = 0

        @cached(c, key_builder=lambda user_id: f"user:{user_id}")
        async def fetch(user_id: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"data-{user_id}"

        v1 = await fetch("u1")
        assert v1 == "data-u1"
        _ = await fetch("u1")
        assert call_count == 1


# ============================================================================
# _build_signature
# ============================================================================

class TestBuildSignature:
    def test_short(self):
        sig = _build_signature((1, 2), {"name": "test"})
        assert "1" in sig
        assert "name=test" in sig

    def test_long_uses_md5(self):
        long_arg = "x" * 300
        sig = _build_signature((long_arg,), {})
        assert len(sig) == 32  # MD5 hex length


# ============================================================================
# RedisCacheBackend (light — import check only)
# ============================================================================

class TestRedisCacheBackend:
    def test_init(self):
        b = RedisCacheBackend(url="redis://localhost:6379/0")
        assert b._url == "redis://localhost:6379/0"

    def test_key_prefix(self):
        b = RedisCacheBackend(prefix="test:")
        assert b._key("foo") == "test:foo"
