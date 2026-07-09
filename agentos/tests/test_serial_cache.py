"""Tests for agentos.tools.serial_cache — Serializer, TTLCache, SmartCache."""

import json
import pickle
import threading
import time

import pytest

from agentos.tools.serial_cache import (
    EvictionPolicy,
    SerialFormat,
    Serializer,
    SmartCache,
    TTLCache,
)

# ============================================================================
# SerialFormat
# ============================================================================

class TestSerialFormat:
    def test_enum_values(self):
        assert SerialFormat.JSON.value == "json"
        assert SerialFormat.PICKLE.value == "pickle"
        assert SerialFormat.MSGPACK.value == "msgpack"
        assert SerialFormat.AUTO.value == "auto"

    def test_detect_explicit_json(self):
        fmt = SerialFormat.JSON
        assert fmt.detect(b'{"a":1}') == SerialFormat.JSON

    def test_detect_explicit_pickle(self):
        fmt = SerialFormat.PICKLE
        assert fmt.detect(b"\x80\x04") == SerialFormat.PICKLE

    def test_detect_auto_json(self):
        fmt = SerialFormat.AUTO
        assert fmt.detect(b'{"a":1}') == SerialFormat.JSON
        assert fmt.detect(b"[1,2,3]") == SerialFormat.JSON

    def test_detect_auto_pickle(self):
        fmt = SerialFormat.AUTO
        data = pickle.dumps({"x": 1})
        assert fmt.detect(data) == SerialFormat.PICKLE

    def test_detect_auto_unknown(self):
        fmt = SerialFormat.AUTO
        with pytest.raises(ValueError, match="Cannot auto-detect"):
            fmt.detect(b"\xff\xfe")


# ============================================================================
# Serializer
# ============================================================================

class TestSerializer:
    def test_default_format(self):
        s = Serializer()
        assert s._fmt == SerialFormat.JSON

    def test_custom_format(self):
        s = Serializer(fmt=SerialFormat.PICKLE)
        assert s._fmt == SerialFormat.PICKLE

    def test_auto_format_falls_back_to_json(self):
        s = Serializer(fmt=SerialFormat.AUTO)
        data = s.dumps({"a": 1})
        result = s.loads(data)
        assert result == {"a": 1}

    def test_dumps_json(self):
        s = Serializer(fmt=SerialFormat.JSON)
        data = s.dumps({"hello": "world"})
        assert json.loads(data) == {"hello": "world"}

    def test_dumps_pickle(self):
        s = Serializer(fmt=SerialFormat.PICKLE)
        data = s.dumps({"x": 42})
        assert pickle.loads(data) == {"x": 42}

    def test_loads_json(self):
        s = Serializer()
        data = json.dumps({"a": 1, "b": 2}).encode("utf-8")
        result = s.loads(data)
        assert result == {"a": 1, "b": 2}

    def test_loads_pickle(self):
        s = Serializer()
        data = pickle.dumps({"z": 99})
        result = s.loads(data)
        assert result == {"z": 99}

    def test_loads_explicit_format(self):
        s = Serializer()
        data = json.dumps([1, 2, 3]).encode("utf-8")
        result = s.loads(data, fmt=SerialFormat.JSON)
        assert result == [1, 2, 3]

    def test_roundtrip_json(self):
        s = Serializer(fmt=SerialFormat.JSON)
        obj = {"nested": {"key": [1, 2, 3]}}
        assert s.loads(s.dumps(obj)) == obj

    def test_roundtrip_pickle(self):
        s = Serializer(fmt=SerialFormat.PICKLE)
        obj = {"tuple": (1, 2), "set": {3, 4}}
        assert s.loads(s.dumps(obj)) == obj

    def test_stats(self):
        s = Serializer()
        s.dumps({"a": 1})
        s.loads(json.dumps({"b": 2}).encode())
        st = s.stats
        assert st["total_serialized"] == 1
        assert st["total_deserialized"] == 1
        assert st["format"] == "json"

    def test_unsupported_format(self):
        s = Serializer(fmt=SerialFormat.PICKLE)
        # Create a serializer with a bad internal state and test dumps
        with pytest.raises(ValueError, match="Unsupported"):
            s.dumps({}, use_msgpack=False)
            s._fmt = "bad_fmt"
            s.dumps({})

    def test_use_msgpack_flag(self):
        pytest.importorskip("msgpack")
        s = Serializer(fmt=SerialFormat.JSON)
        data = s.dumps({"a": 1}, use_msgpack=True)
        import msgpack
        assert msgpack.unpackb(data) == {"a": 1}

    def test_loads_msgpack(self):
        pytest.importorskip("msgpack")
        import msgpack
        s = Serializer()
        data = msgpack.packb({"m": "p"})
        result = s.loads(data)
        assert result == {"m": "p"}

    def test_stats_pickle_format(self):
        s = Serializer(fmt=SerialFormat.PICKLE)
        s.dumps({"x": 1})
        assert s.stats["format"] == "pickle"


# ============================================================================
# EvictionPolicy
# ============================================================================

class TestEvictionPolicy:
    def test_enum_values(self):
        assert EvictionPolicy.LRU.value == "lru"
        assert EvictionPolicy.LFU.value == "lfu"
        assert EvictionPolicy.TTL_ONLY.value == "ttl_only"


# ============================================================================
# TTLCache — Basic Operations
# ============================================================================

class TestTTLCacheBasic:
    def test_defaults(self):
        cache = TTLCache[int]()
        assert cache._max_size == 1000
        assert cache._ttl == 300.0
        assert cache._policy == EvictionPolicy.LRU
        assert cache.size == 0

    def test_custom_params(self):
        cache = TTLCache[str](max_size=10, ttl=60.0, policy=EvictionPolicy.LFU)
        assert cache._max_size == 10
        assert cache._ttl == 60.0
        assert cache._policy == EvictionPolicy.LFU

    def test_set_get(self):
        cache = TTLCache[int]()
        cache.set("a", 1)
        assert cache.get("a") == 1

    def test_get_missing(self):
        cache = TTLCache[str]()
        assert cache.get("no-key") is None

    def test_set_overwrite(self):
        cache = TTLCache[int]()
        cache.set("a", 1)
        cache.set("a", 99)
        assert cache.get("a") == 99
        assert cache.size == 1

    def test_delete(self):
        cache = TTLCache[int]()
        cache.set("x", 42)
        assert cache.delete("x") is True
        assert cache.get("x") is None
        assert cache.size == 0

    def test_delete_missing(self):
        cache = TTLCache[int]()
        assert cache.delete("nope") is False

    def test_clear(self):
        cache = TTLCache[int]()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None

    def test_size(self):
        cache = TTLCache[int]()
        assert cache.size == 0
        cache.set("a", 1)
        assert cache.size == 1
        cache.set("b", 2)
        assert cache.size == 2


# ============================================================================
# TTLCache — TTL Expiration
# ============================================================================

class TestTTLCacheTTL:
    def test_expired_entry(self):
        cache = TTLCache[int](ttl=0.05)
        cache.set("a", 1)
        assert cache.get("a") == 1
        time.sleep(0.1)
        assert cache.get("a") is None

    def test_custom_ttl_per_entry(self):
        cache = TTLCache[int](ttl=10.0)
        cache.set("a", 1, ttl=0.05)
        assert cache.get("a") == 1
        time.sleep(0.1)
        assert cache.get("a") is None

    def test_cleanup(self):
        cache = TTLCache[int](ttl=0.05)
        cache.set("a", 1)
        cache.set("b", 2)
        time.sleep(0.1)
        removed = cache.cleanup()
        assert removed == 2
        assert cache.size == 0

    def test_cleanup_partial(self):
        cache = TTLCache[int](ttl=0.05)
        cache.set("a", 1)
        time.sleep(0.1)
        cache.set("b", 2, ttl=10.0)
        removed = cache.cleanup()
        assert removed == 1
        assert cache.size == 1
        assert cache.get("b") == 2


# ============================================================================
# TTLCache — Eviction
# ============================================================================

class TestTTLCacheEviction:
    def test_lru_eviction(self):
        cache = TTLCache[int](max_size=2, ttl=300, policy=EvictionPolicy.LRU)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("a")  # access "a" — now "b" is least recently used
        cache.set("c", 3)
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3

    def test_lfu_eviction(self):
        cache = TTLCache[int](max_size=2, ttl=300, policy=EvictionPolicy.LFU)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("b")  # b access_count = 1
        cache.get("b")  # b access_count = 2
        cache.get("a")  # a access_count = 1
        cache.set("c", 3)
        # a has lowest access_count (1), should be evicted
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_ttl_only_eviction(self):
        cache = TTLCache[int](max_size=2, ttl=300, policy=EvictionPolicy.TTL_ONLY)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("b")  # access b
        cache.set("c", 3)
        # TTL_ONLY evicts oldest (first inserted) regardless of access
        assert cache.get("a") is None
        assert cache.get("b") == 2


# ============================================================================
# TTLCache — Stats
# ============================================================================

class TestTTLCacheStats:
    def test_default_stats(self):
        cache = TTLCache[int](max_size=50, ttl=10, policy=EvictionPolicy.LFU)
        s = cache.stats
        assert s["size"] == 0
        assert s["max_size"] == 50
        assert s["ttl"] == 10
        assert s["policy"] == "lfu"
        assert s["hits"] == 0
        assert s["misses"] == 0
        assert s["evictions"] == 0

    def test_hits_misses(self):
        cache = TTLCache[int]()
        cache.set("a", 1)
        cache.get("a")  # hit
        cache.get("b")  # miss
        s = cache.stats
        assert s["hits"] == 1
        assert s["misses"] == 1

    def test_hit_rate(self):
        cache = TTLCache[int]()
        cache.set("a", 1)
        cache.get("a")  # hit
        cache.get("a")  # hit
        cache.get("b")  # miss
        s = cache.stats
        assert s["hit_rate"] == round(2 / 3, 3)

    def test_hit_rate_no_ops(self):
        cache = TTLCache[int]()
        s = cache.stats
        assert s["hit_rate"] == 0.0

    def test_evictions_count(self):
        cache = TTLCache[int](max_size=2, ttl=300, policy=EvictionPolicy.LRU)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # evicts "a"
        assert cache.stats["evictions"] == 1


# ============================================================================
# TTLCache — Thread Safety
# ============================================================================

class TestTTLCacheThreadSafety:
    def test_concurrent_access(self):
        cache = TTLCache[int]()
        errors = []

        def worker(start_idx):
            try:
                for i in range(start_idx, start_idx + 50):
                    cache.set(f"k{i}", i)
                    cache.get(f"k{i}")
                    cache.delete(f"k{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ============================================================================
# SmartCache
# ============================================================================

class TestSmartCache:
    def test_get_missing(self):
        sc = SmartCache[int]()
        assert sc.get("x") is None

    def test_get_or_compute(self):
        sc = SmartCache[int]()
        result = sc.get_or_compute("key", lambda: 42)
        assert result == 42
        # Second call should use cache
        result = sc.get_or_compute("key", lambda: 99)
        assert result == 42

    def test_get_or_compute_complex(self):
        sc = SmartCache[str](ttl=10.0)
        calls = []

        def factory():
            calls.append(1)
            return "computed"

        r1 = sc.get_or_compute("k", factory)
        assert r1 == "computed"
        assert len(calls) == 1
        r2 = sc.get_or_compute("k", factory)
        assert r2 == "computed"
        assert len(calls) == 1

    def test_get_or_compute_expired(self):
        sc = SmartCache[int](ttl=0.05)
        sc.get_or_compute("k", lambda: 42)
        time.sleep(0.1)
        result = sc.get_or_compute("k", lambda: 99)
        assert result == 99  # recomputed after expiry

    def test_get_or_compute_custom_ttl(self):
        sc = SmartCache[int]()
        r1 = sc.get_or_compute("k", lambda: 42, ttl=0.05)
        assert r1 == 42
        time.sleep(0.1)
        r2 = sc.get_or_compute("k", lambda: 99)
        assert r2 == 99

    def test_set_and_get(self):
        sc = SmartCache[int]()
        sc.set("x", 100)
        assert sc.get("x") == 100

    def test_delete(self):
        sc = SmartCache[int]()
        sc.set("x", 1)
        assert sc.delete("x") is True
        assert sc.get("x") is None

    def test_clear(self):
        sc = SmartCache[int]()
        sc.set("a", 1)
        sc.set("b", 2)
        sc.clear()
        assert sc.size == 0

    def test_size(self):
        sc = SmartCache[int]()
        assert sc.size == 0
        sc.set("a", 1)
        assert sc.size == 1
        sc.set("b", 2)
        assert sc.size == 2

    def test_stats(self):
        sc = SmartCache[int]()
        sc.get_or_compute("k", lambda: 42)
        s = sc.stats
        assert s["size"] == 1
        assert s["hits"] >= 0
        assert s["max_size"] == 1000

    def test_dump_load(self):
        sc = SmartCache[str]()
        sc.set("a", "hello")
        sc.set("b", "world")

        data = sc.dump()
        assert len(data) > 0

        sc2 = SmartCache[str]()
        loaded = sc2.load(data)
        assert loaded == 2
        assert sc2.get("a") == "hello"
        assert sc2.get("b") == "world"

    def test_dump_load_expired_filters(self):
        sc = SmartCache[int]()
        sc.set("live", 42, ttl=10.0)
        sc.get_or_compute("dead", lambda: 1, ttl=0.01)
        time.sleep(0.05)

        data = sc.dump()
        sc2 = SmartCache[int]()
        loaded = sc2.load(data)
        assert loaded == 1
        assert sc2.get("live") == 42
        assert sc2.get("dead") is None

    def test_custom_params_passthrough(self):
        sc = SmartCache[int](max_size=5, ttl=30.0, policy=EvictionPolicy.LFU)
        assert sc.size == 0
        assert sc._cache._max_size == 5
