"""
Tests for AgentOS Response Cache (agentos/core/response_cache.py)
"""

import threading
import time

import pytest

from agentos.core.response_cache import (
    CacheEntry,
    EvictionPolicy,
    ResponseCache,
)


class TestCacheEntry:
    """CacheEntry data class tests."""

    def test_entry_creation(self):
        entry = CacheEntry(key="k1", value="v1", size_bytes=100)
        assert entry.key == "k1"
        assert entry.value == "v1"
        assert entry.size_bytes == 100
        assert entry.hit_count == 0
        assert not entry.is_expired

    def test_entry_expiry(self):
        entry = CacheEntry(key="k1", value="v1", size_bytes=100, ttl_seconds=0.01)
        time.sleep(0.02)
        assert entry.is_expired

    def test_entry_no_expiry_when_no_ttl(self):
        entry = CacheEntry(key="k1", value="v1", size_bytes=100, ttl_seconds=None)
        assert not entry.is_expired

    def test_entry_age(self):
        entry = CacheEntry(key="k1", value="v1", size_bytes=100)
        time.sleep(0.01)
        assert entry.age_seconds > 0


class TestEvictionPolicy:
    """Eviction policy (LRU with memory budget) tests."""

    def test_put_and_get(self):
        policy = EvictionPolicy(max_entries=3, max_size_mb=10)
        e1 = CacheEntry(key="a", value="A", size_bytes=10)
        policy.put(e1)
        assert policy.get("a") is not None
        assert policy.get("a").value == "A"

    def test_lru_eviction_by_count(self):
        policy = EvictionPolicy(max_entries=2, max_size_mb=10)
        policy.put(CacheEntry(key="a", value="A", size_bytes=10))
        policy.put(CacheEntry(key="b", value="B", size_bytes=10))
        policy.put(CacheEntry(key="c", value="C", size_bytes=10))
        # a should be evicted (LRU), b and c remain
        assert policy.get("a") is None
        assert policy.get("b") is not None
        assert policy.get("c") is not None

    def test_lru_access_bumps_position(self):
        policy = EvictionPolicy(max_entries=2, max_size_mb=10)
        policy.put(CacheEntry(key="a", value="A", size_bytes=10))
        policy.put(CacheEntry(key="b", value="B", size_bytes=10))
        # Access "a" to make it recently used
        policy.get("a")
        policy.put(CacheEntry(key="c", value="C", size_bytes=10))
        # b should be evicted, a and c remain
        assert policy.get("b") is None
        assert policy.get("a") is not None
        assert policy.get("c") is not None

    def test_expired_entry_not_returned(self):
        policy = EvictionPolicy(max_entries=3, max_size_mb=10)
        policy.put(CacheEntry(key="a", value="A", size_bytes=10, ttl_seconds=0.001))
        time.sleep(0.01)
        assert policy.get("a") is None

    def test_remove_entry(self):
        policy = EvictionPolicy(max_entries=3, max_size_mb=10)
        policy.put(CacheEntry(key="a", value="A", size_bytes=10))
        policy.remove("a")
        assert policy.get("a") is None

    def test_clear(self):
        policy = EvictionPolicy(max_entries=3, max_size_mb=10)
        policy.put(CacheEntry(key="a", value="A", size_bytes=10))
        policy.put(CacheEntry(key="b", value="B", size_bytes=10))
        policy.clear()
        assert policy.size == 0

    def test_size_stats(self):
        policy = EvictionPolicy(max_entries=10, max_size_mb=10)
        policy.put(CacheEntry(key="a", value="A", size_bytes=50))
        policy.put(CacheEntry(key="b", value="B", size_bytes=50))
        assert policy.size == 2
        assert policy.total_size_bytes == 100

    def test_hit_count_increment(self):
        policy = EvictionPolicy(max_entries=3, max_size_mb=10)
        policy.put(CacheEntry(key="a", value="A", size_bytes=10))
        policy.get("a")
        policy.get("a")
        entry = policy.get("a")
        assert entry.hit_count == 3


class TestResponseCache:
    """ResponseCache full integration tests."""

    def test_put_and_get(self):
        cache = ResponseCache(by_model=True)
        cache.put("gpt-4o", "What is Python?", "Python is a programming language.")
        result = cache.get("gpt-4o", "What is Python?")
        assert result == "Python is a programming language."

    def test_cache_miss(self):
        cache = ResponseCache(by_model=True)
        result = cache.get("gpt-4o", "Unknown question?")
        assert result is None

    def test_model_isolation(self):
        cache = ResponseCache(by_model=True)
        cache.put("gpt-4o", "Test prompt", "GPT response")
        cache.put("claude-3", "Test prompt", "Claude response")
        assert cache.get("gpt-4o", "Test prompt") == "GPT response"
        assert cache.get("claude-3", "Test prompt") == "Claude response"

    def test_different_prompt_keys(self):
        cache = ResponseCache(by_model=True)
        cache.put("gpt-4o", "Prompt A", "Response A")
        cache.put("gpt-4o", "Prompt B", "Response B")
        assert cache.get("gpt-4o", "Prompt A") == "Response A"
        assert cache.get("gpt-4o", "Prompt B") == "Response B"

    def test_invalidate_entry(self):
        cache = ResponseCache(by_model=True)
        cache.put("gpt-4o", "Test", "Response")
        assert cache.invalidate("gpt-4o", "Test")
        assert cache.get("gpt-4o", "Test") is None

    def test_invalidate_model(self):
        cache = ResponseCache(by_model=True)
        cache.put("gpt-4o", "Test 1", "R1")
        cache.put("gpt-4o", "Test 2", "R2")
        cache.invalidate_model("gpt-4o")
        assert cache.get("gpt-4o", "Test 1") is None
        assert cache.get("gpt-4o", "Test 2") is None

    def test_clear_all(self):
        cache = ResponseCache(by_model=True)
        cache.put("gpt-4o", "Test 1", "R1")
        cache.put("claude-3", "Test 2", "R2")
        cache.clear()
        assert cache.get("gpt-4o", "Test 1") is None
        assert cache.get("claude-3", "Test 2") is None

    def test_stats_accumulate(self):
        cache = ResponseCache(by_model=True)
        cache.get("gpt-4o", "Miss 1")   # miss
        cache.get("gpt-4o", "Miss 2")   # miss
        cache.put("gpt-4o", "Hit", "Yes")
        cache.get("gpt-4o", "Hit")      # hit

        stats = cache.get_stats()
        assert stats["total_requests"] == 3
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["hit_rate"] == pytest.approx(1 / 3, rel=0.1)

    def test_per_model_stats(self):
        cache = ResponseCache(by_model=True)
        cache.put("gpt-4o", "P1", "R1")
        cache.put("claude-3", "P2", "R2")
        model_stats = cache.get_per_model_stats()
        assert "gpt-4o" in model_stats
        assert "claude-3" in model_stats

    def test_ttl_expiry(self):
        cache = ResponseCache(ttl_seconds=0.01)
        cache.put("gpt-4o", "Test", "Value")
        time.sleep(0.02)
        assert cache.get("gpt-4o", "Test") is None

    def test_no_ttl_when_none(self):
        cache = ResponseCache(ttl_seconds=None)
        cache.put("gpt-4o", "Test", "Value")
        assert cache.get("gpt-4o", "Test") == "Value"

    def test_warmup(self):
        cache = ResponseCache(by_model=True)
        entries = [
            ("gpt-4o", "Q1", "R1", None),
            ("gpt-4o", "Q2", "R2", None),
        ]
        count = cache.warmup(entries)
        assert count == 2
        assert cache.get("gpt-4o", "Q1") == "R1"
        assert cache.get("gpt-4o", "Q2") == "R2"

    def test_non_model_mode(self):
        cache = ResponseCache(by_model=False)
        cache.put("gpt-4o", "Prompt", "Response")
        assert cache.get("gpt-4o", "Prompt") == "Response"

    def test_thread_safety(self):
        cache = ResponseCache(by_model=True)
        errors = []

        def worker(thread_id):
            try:
                for i in range(50):
                    cache.put("gpt-4o", f"P{thread_id}:{i}", f"R{thread_id}:{i}")
                    cache.get("gpt-4o", f"P{thread_id}:{i}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
