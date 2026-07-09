"""Tests for agentos.tools.serial_cache — Serializer, TTLCache, SmartCache."""

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
    def test_auto_detect_json(self):
        fmt = SerialFormat.AUTO.detect(b'{"key": 1}')
        assert fmt == SerialFormat.JSON

    def test_auto_detect_pickle_80_03(self):
        fmt = SerialFormat.AUTO.detect(b'\x80\x03ABC')
        assert fmt == SerialFormat.PICKLE

    def test_auto_detect_pickle_80_04(self):
        fmt = SerialFormat.AUTO.detect(b'\x80\x04XYZ')
        assert fmt == SerialFormat.PICKLE

    def test_auto_detect_pickle_80_05(self):
        fmt = SerialFormat.AUTO.detect(b'\x80\x05data')
        assert fmt == SerialFormat.PICKLE

    def test_non_auto_returns_self(self):
        assert SerialFormat.JSON.detect(b'anything') == SerialFormat.JSON
        assert SerialFormat.PICKLE.detect(b'anything') == SerialFormat.PICKLE
        assert SerialFormat.MSGPACK.detect(b'anything') == SerialFormat.MSGPACK

    def test_auto_detect_unknown_raises(self):
        with pytest.raises(ValueError, match="auto-detect"):
            SerialFormat.AUTO.detect(b'\xff\xff\xff')


# ============================================================================
# Serializer
# ============================================================================

class TestSerializer:
    def test_json_roundtrip(self):
        s = Serializer(SerialFormat.JSON)
        data = {"a": 1, "b": [2, 3]}
        raw = s.dumps(data)
        assert s.loads(raw) == data

    def test_pickle_roundtrip(self):
        s = Serializer(SerialFormat.PICKLE)
        data = {"set": {1, 2, 3}, "tuple": (4, 5)}
        raw = s.dumps(data)
        assert s.loads(raw) == data

    def test_default_to_json(self):
        s = Serializer()
        raw = s.dumps([1, 2])
        assert raw == b'[1, 2]'

    def test_auto_format_roundtrip_json(self):
        s = Serializer(SerialFormat.JSON)
        raw = s.dumps({"k": "v"})
        assert s.loads(raw) == {"k": "v"}

    def test_auto_format_roundtrip_pickle(self):
        s = Serializer(SerialFormat.PICKLE)
        raw = s.dumps({"k": "v"})
        assert s.loads(raw) == {"k": "v"}

    def test_stats(self):
        s = Serializer()
        s.dumps({"a": 1})
        s.loads(b'{"b": 2}')
        st = s.stats
        assert st["total_serialized"] == 1
        assert st["total_deserialized"] == 1

    def test_loads_explicit_format(self):
        s = Serializer()
        raw = s.dumps({"key": "val"})
        result = s.loads(raw, fmt=SerialFormat.JSON)
        assert result == {"key": "val"}

    def test_unsupported_format_raises(self):
        s = Serializer()
        s._fmt = "bogus"
        with pytest.raises(ValueError, match="Unsupported"):
            s.dumps({})


# ============================================================================
# TTLCache
# ============================================================================

class TestTTLCacheBasic:
    def test_set_get(self):
        c = TTLCache[int]()
        c.set("a", 42)
        assert c.get("a") == 42

    def test_miss_returns_none(self):
        c = TTLCache[int]()
        assert c.get("no") is None

    def test_delete(self):
        c = TTLCache[int]()
        c.set("a", 1)
        assert c.delete("a") is True
        assert c.get("a") is None
        assert c.delete("a") is False

    def test_clear(self):
        c = TTLCache[int]()
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.size == 0

    def test_size(self):
        c = TTLCache[int]()
        assert c.size == 0
        c.set("x", 1)
        c.set("y", 2)
        assert c.size == 2

    def test_ttl_expiry(self):
        c = TTLCache[str](ttl=0.01)
        c.set("k", "v")
        time.sleep(0.02)
        assert c.get("k") is None

    def test_custom_ttl_override(self):
        c = TTLCache[str](ttl=60)
        c.set("k", "v", ttl=0.01)
        time.sleep(0.02)
        assert c.get("k") is None


class TestTTLCacheEviction:
    def test_lru_eviction(self):
        c = TTLCache[int](max_size=3, policy=EvictionPolicy.LRU)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.get("a")  # access a → moves to end
        c.set("d", 4)  # evicts b (LRU)
        assert c.get("a") == 1
        assert c.get("b") is None
        assert c.get("c") == 3

    def test_lfu_eviction(self):
        c = TTLCache[int](max_size=2, policy=EvictionPolicy.LFU)
        c.set("a", 1)
        c.set("b", 2)
        c.get("b")  # b: count=1
        c.get("b")  # b: count=2
        c.set("c", 3)  # evicts a (count=0)
        assert c.get("a") is None
        assert c.get("b") == 2

    def test_ttl_only_eviction(self):
        c = TTLCache[int](max_size=2, policy=EvictionPolicy.TTL_ONLY)
        c.set("a", 1)
        c.set("b", 2)
        c.get("b")  # access b — doesn't matter for TTL_ONLY
        c.set("c", 3)  # evicts a (first inserted)
        assert c.get("a") is None

    def test_cleanup_expired(self):
        c = TTLCache[str](ttl=0.01)
        c.set("a", "1")
        c.set("b", "2")
        time.sleep(0.02)
        removed = c.cleanup()
        assert removed >= 2
        assert c.size == 0


class TestTTLCacheStats:
    def test_hit_miss(self):
        c = TTLCache[int]()
        c.set("k", 1)
        c.get("k")
        c.get("missing")
        st = c.stats
        assert st["hits"] == 1
        assert st["misses"] == 1

    def test_hit_rate(self):
        c = TTLCache[int]()
        c.set("k", 1)
        c.get("k")
        c.get("k")
        c.get("missing")
        st = c.stats
        assert st["hit_rate"] == round(2 / 3, 3)

    def test_stats_zero_interactions(self):
        c = TTLCache[int]()
        st = c.stats
        assert st["hit_rate"] == 0.0


# ============================================================================
# SmartCache
# ============================================================================

class TestSmartCache:
    def test_get_or_compute_miss(self):
        c = SmartCache[int]()
        calls = [0]

        def factory():
            calls[0] += 1
            return 99

        result = c.get_or_compute("k", factory)
        assert result == 99
        assert calls[0] == 1

    def test_get_or_compute_hit(self):
        c = SmartCache[int]()
        c.set("k", 42)
        calls = [0]
        result = c.get_or_compute("k", lambda: calls.__setitem__(0, calls[0] + 1) or 0)
        assert result == 42
        assert calls[0] == 0  # factory not called

    def test_set_and_get(self):
        c = SmartCache[str]()
        c.set("hello", "world")
        assert c.get("hello") == "world"

    def test_delete(self):
        c = SmartCache[int]()
        c.set("x", 1)
        assert c.delete("x") is True
        assert c.get("x") is None

    def test_clear(self):
        c = SmartCache[int]()
        c.set("a", 1)
        c.set("b", 2)
        c.clear()
        assert c.size == 0

    def test_size(self):
        c = SmartCache[int]()
        c.set("a", 1)
        assert c.size == 1

    def test_stats(self):
        c = SmartCache[int]()
        c.get_or_compute("k", lambda: 100)
        st = c.stats
        assert "hits" in st
        assert "misses" in st

    def test_dump_load_roundtrip(self):
        c = SmartCache[str]()
        c.set("alice", "hello")
        c.set("bob", "world")
        data = c.dump()
        c2 = SmartCache[str]()
        loaded = c2.load(data)
        assert loaded == 2
        assert c2.get("alice") == "hello"
        assert c2.get("bob") == "world"

    def test_load_skips_expired(self):
        c = SmartCache[int]()
        c.set("a", 1, ttl=0.01)
        c.set("b", 2, ttl=999)
        data = c.dump()
        time.sleep(0.02)
        c2 = SmartCache[int]()
        loaded = c2.load(data)
        assert loaded == 1
        assert c2.get("b") == 2
        assert c2.get("a") is None
