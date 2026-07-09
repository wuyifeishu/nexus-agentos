"""Tests for agentos.tools.serial_cache."""

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
# Serializer Tests
# ============================================================================

class TestSerializer:
    def test_json_roundtrip(self):
        s = Serializer(fmt=SerialFormat.JSON)
        data = {"a": 1, "b": [2, 3], "c": "hello"}
        raw = s.dumps(data)
        result = s.loads(raw)
        assert result == data

    def test_pickle_roundtrip(self):
        s = Serializer(fmt=SerialFormat.PICKLE)
        data = {"x": 42, "y": [1, 2, 3]}
        raw = s.dumps(data)
        result = s.loads(raw)
        assert result == data

    def test_auto_detect_json(self):
        s = Serializer()
        raw = b'{"key": "value"}'
        result = s.loads(raw)
        assert result == {"key": "value"}

    def test_auto_detect_pickle(self):
        import pickle
        s = Serializer()
        raw = pickle.dumps({"hello": "world"})
        result = s.loads(raw)
        assert result == {"hello": "world"}

    def test_stats(self):
        s = Serializer()
        s.dumps({"a": 1})
        s.loads(b'{"b": 2}')
        d = s.stats
        assert d["total_serialized"] == 1
        assert d["total_deserialized"] == 1

    def test_json_list(self):
        s = Serializer(fmt=SerialFormat.JSON)
        data = [1, 2, 3]
        raw = s.dumps(data)
        assert s.loads(raw) == data


# ============================================================================
# TTLCache Tests
# ============================================================================

class TestTTLCache:
    def test_set_get(self):
        c = TTLCache[str]()
        c.set("a", "hello")
        assert c.get("a") == "hello"

    def test_ttl_expiry(self):
        c = TTLCache[int](ttl=0.01)
        c.set("x", 42)
        time.sleep(0.02)
        c.cleanup()
        assert c.get("x") is None

    def test_miss(self):
        c = TTLCache[int]()
        assert c.get("nope") is None

    def test_delete(self):
        c = TTLCache[int]()
        c.set("k", 100)
        assert c.delete("k") is True
        assert c.delete("k") is False
        assert c.get("k") is None

    def test_clear(self):
        c = TTLCache[int]()
        for i in range(5):
            c.set(str(i), i)
        c.clear()
        assert c.size == 0

    def test_max_size_eviction(self):
        c = TTLCache[int](max_size=3, policy=EvictionPolicy.LRU)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        # Access a to make it recently used
        c.get("a")
        c.set("d", 4)
        assert c.get("b") is None  # b should be evicted (LRU)
        assert c.get("a") == 1

    def test_lfu_eviction(self):
        c = TTLCache[int](max_size=3, policy=EvictionPolicy.LFU)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.get("a"); c.get("a")  # a:2 accesses
        c.get("b")               # b:1 access
        # c has 0 accesses, lowest → evicted
        c.set("d", 4)
        assert c.get("c") is None
        assert c.get("a") == 1
        assert c.get("b") == 2

    def test_stats(self):
        c = TTLCache[int]()
        c.set("x", 1)
        c.get("x"); c.get("x")
        c.get("y")  # miss
        s = c.stats
        assert s["hits"] == 2
        assert s["misses"] == 1
        assert s["hit_rate"] == pytest.approx(2/3, abs=1e-3)

    def test_cleanup(self):
        c = TTLCache[int](ttl=0.01)
        c.set("old", 1)
        time.sleep(0.02)
        count = c.cleanup()
        assert count == 1
        assert c.size == 0

    def test_generic_type(self):
        c = TTLCache[list]()
        c.set("lst", [1, 2, 3])
        assert c.get("lst") == [1, 2, 3]


# ============================================================================
# SmartCache Tests
# ============================================================================

class TestSmartCache:
    def test_get_or_compute(self):
        sc = SmartCache[int]()
        call_count = [0]

        def factory():
            call_count[0] += 1
            return call_count[0] * 10

        assert sc.get_or_compute("k", factory) == 10
        assert sc.get_or_compute("k", factory) == 10  # cached
        assert call_count[0] == 1

    def test_dump_load(self):
        sc = SmartCache[str]()
        sc.set("a", "alpha")
        sc.set("b", "beta")
        data = sc.dump()
        sc2 = SmartCache[str]()
        loaded = sc2.load(data)
        assert loaded == 2
        assert sc2.get("a") == "alpha"
        assert sc2.get("b") == "beta"

    def test_dump_load_expired_skip(self):
        sc = SmartCache[str]()
        sc.set("fresh", "yes")
        sc.set("expired", "no", ttl=-10)
        data = sc.dump()
        sc2 = SmartCache[str]()
        loaded = sc2.load(data)
        assert loaded == 1
        assert sc2.get("fresh") == "yes"
        assert sc2.get("expired") is None

    def test_stats_delegation(self):
        sc = SmartCache[int]()
        sc.get_or_compute("x", lambda: 42)
        s = sc.stats
        assert s["misses"] == 1

    def test_delete_clear(self):
        sc = SmartCache[int]()
        sc.set("a", 1)
        sc.set("b", 2)
        assert sc.delete("a") is True
        assert sc.size == 1
        sc.clear()
        assert sc.size == 0
