"""Tests for agentos.cache — llm_cache, embedder, response_cache."""

import asyncio
import time

import pytest

from agentos.cache.embedder import (
    EmbeddingResult,
    cosine_similarity,
    get_embedder,
)
from agentos.cache.llm_cache import (
    CacheEntry as LLMCacheEntry,
)
from agentos.cache.llm_cache import (
    CacheStats,
    LLMCache,
    LRUCache,
    SemanticCache,
)
from agentos.cache.response_cache import (
    CacheEntry as ResponseCacheEntry,
)
from agentos.cache.response_cache import (
    CacheKeyStrategy,
    ResponseCache,
)
from agentos.cache.response_cache import (
    CacheStats as ResponseCacheStats,
)

# ═══════════════════════════════════════════════════════════════
# LLM Cache — CacheEntry
# ═══════════════════════════════════════════════════════════════

class TestLLMCacheEntry:
    def test_defaults(self):
        e = LLMCacheEntry(key="k", value="v")
        assert e.key == "k"
        assert e.value == "v"
        assert e.tokens_saved == 0
        assert e.cost_saved == 0.0
        assert e.ttl == 3600
        assert e.hit_count == 0
        assert e.tags == []

    def test_expired_true(self):
        e = LLMCacheEntry(key="k", value="v", created_at=time.time() - 100, ttl=10)
        assert e.expired is True

    def test_expired_false(self):
        e = LLMCacheEntry(key="k", value="v", ttl=9999)
        assert e.expired is False

    def test_not_expired(self):
        e = LLMCacheEntry(key="k", value="v", created_at=time.time(), ttl=3600)
        assert e.expired is False


# ═══════════════════════════════════════════════════════════════
# LLM Cache — LRUCache
# ═══════════════════════════════════════════════════════════════

class TestLRUCache:
    def test_put_get(self):
        c = LRUCache(max_size=10)
        e = LLMCacheEntry(key="k1", value="v1")
        c.put("k1", e)
        assert c.get("k1").value == "v1"

    def test_get_missing(self):
        c = LRUCache(max_size=10)
        assert c.get("nonexistent") is None

    def test_get_expired(self):
        c = LRUCache(max_size=10)
        e = LLMCacheEntry(key="k", value="v", created_at=time.time() - 100, ttl=1)
        c.put("k", e)
        assert c.get("k") is None

    def test_lru_eviction(self):
        c = LRUCache(max_size=2)
        c.put("k1", LLMCacheEntry(key="k1", value="v1"))
        c.put("k2", LLMCacheEntry(key="k2", value="v2"))
        c.put("k3", LLMCacheEntry(key="k3", value="v3"))
        assert c.get("k1") is None  # evicted
        assert c.get("k2") is not None
        assert c.get("k3") is not None

    def test_lru_reorder_on_get(self):
        c = LRUCache(max_size=2)
        c.put("k1", LLMCacheEntry(key="k1", value="v1"))
        c.put("k2", LLMCacheEntry(key="k2", value="v2"))
        c.get("k1")  # k1 becomes most recent
        c.put("k3", LLMCacheEntry(key="k3", value="v3"))
        assert c.get("k2") is None  # k2 evicted
        assert c.get("k1") is not None  # k1 kept

    def test_invalidate_key(self):
        c = LRUCache(max_size=10)
        c.put("k1", LLMCacheEntry(key="k1", value="v1"))
        c.invalidate(key="k1")
        assert c.get("k1") is None

    def test_invalidate_tag(self):
        c = LRUCache(max_size=10)
        c.put("k1", LLMCacheEntry(key="k1", value="v1", tags=["tag_a"]))
        c.put("k2", LLMCacheEntry(key="k2", value="v2", tags=["tag_b"]))
        c.invalidate(tag="tag_a")
        assert c.get("k1") is None
        assert c.get("k2") is not None

    def test_invalidate_missing(self):
        c = LRUCache(max_size=10)
        c.invalidate(key="missing")  # should not raise
        c.invalidate(tag="missing")  # should not raise

    def test_size(self):
        c = LRUCache(max_size=10)
        assert c.size() == 0
        c.put("k", LLMCacheEntry(key="k", value="v"))
        assert c.size() == 1

    def test_clear(self):
        c = LRUCache(max_size=10)
        c.put("k1", LLMCacheEntry(key="k1", value="v1"))
        c.put("k2", LLMCacheEntry(key="k2", value="v2"))
        c.clear()
        assert c.size() == 0

    def test_hit_count_incremented(self):
        c = LRUCache(max_size=10)
        e = LLMCacheEntry(key="k", value="v")
        c.put("k", e)
        c.get("k")
        assert c.get("k").hit_count == 2


# ═══════════════════════════════════════════════════════════════
# LLM Cache — SemanticCache
# ═══════════════════════════════════════════════════════════════

class TestSemanticCache:
    def test_search_miss_empty(self):
        sc = SemanticCache(similarity_threshold=0.9)
        assert sc.search("hello") is None

    def test_add_and_search_same(self):
        sc = SemanticCache(similarity_threshold=0.9)
        e = LLMCacheEntry(key="k", value="v")
        sc.add("hello world", e)
        result = sc.search("hello world")
        assert result is not None
        assert result.value == "v"

    def test_search_below_threshold(self):
        sc = SemanticCache(similarity_threshold=0.99)
        e = LLMCacheEntry(key="k", value="v")
        sc.add("the quick brown fox jumps over the lazy dog", e)
        no_training_neural_network_quantum_computing_cryptography_blockchain = " ".join([f"word{i}" for i in range(200)])
        result = sc.search(no_training_neural_network_quantum_computing_cryptography_blockchain)
        assert result is None

    def test_cosine_sim_identical(self):
        assert SemanticCache.cosine_sim([1, 0], [1, 0]) == 1.0

    def test_cosine_sim_orthogonal(self):
        assert SemanticCache.cosine_sim([1, 0], [0, 1]) == 0.0

    def test_cosine_sim_empty(self):
        assert SemanticCache.cosine_sim([], [1, 0]) == 0.0
        assert SemanticCache.cosine_sim([1, 0], []) == 0.0
        assert SemanticCache.cosine_sim([], []) == 0.0

    def test_cosine_sim_zero_norm(self):
        assert SemanticCache.cosine_sim([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_embed_empty_text(self):
        sc = SemanticCache()
        vec = sc._embed("")
        assert len(vec) == 64
        assert all(v == 0.0 for v in vec)

    def test_max_entries_enforced(self):
        sc = SemanticCache()
        sc.max_entries = 2
        sc.add("q1", LLMCacheEntry(key="k1", value="v1"))
        sc.add("q2", LLMCacheEntry(key="k2", value="v2"))
        sc.add("q3", LLMCacheEntry(key="k3", value="v3"))
        assert len(sc._entries) == 2

    def test_search_skips_expired(self):
        sc = SemanticCache(similarity_threshold=0.5)
        e = LLMCacheEntry(key="k", value="v", created_at=time.time() - 100, ttl=1)
        sc.add("hello", e)
        assert sc.search("hello") is None

    def test_clear(self):
        sc = SemanticCache()
        sc.add("hello", LLMCacheEntry(key="k", value="v"))
        sc.clear()
        assert sc.search("hello") is None

    def test_custom_embedder(self):
        def fake_embed(text: str):
            return [hash(c) % 1000 / 1000.0 for c in text[:8]] + [0.0] * (64 - 8)

        sc = SemanticCache(embedder=fake_embed)
        e = LLMCacheEntry(key="k", value="v")
        sc.add("hello", e)
        result = sc.search("hello")
        assert result is not None


# ═══════════════════════════════════════════════════════════════
# LLM Cache — CacheStats
# ═══════════════════════════════════════════════════════════════

class TestLLMCacheStats:
    def test_hit_rate_zero(self):
        s = CacheStats()
        assert s.hit_rate == 0.0

    def test_hit_rate_50(self):
        s = CacheStats(total_requests=2, hits=1, misses=1)
        assert s.hit_rate == 0.5

    def test_hit_rate_100(self):
        s = CacheStats(total_requests=3, hits=3)
        assert s.hit_rate == 1.0


# ═══════════════════════════════════════════════════════════════
# LLM Cache — LLMCache (integration)
# ═══════════════════════════════════════════════════════════════

class TestLLMCache:
    def test_get_miss(self):
        c = LLMCache()
        result = c.get("hello")
        assert result is None

    def test_set_and_get_exact(self):
        c = LLMCache()
        c.set("hello", "world")
        assert c.get("hello") == "world"

    def test_exact_hit_stats(self):
        c = LLMCache()
        c.set("hello", "world", tokens=10, cost=0.001)
        c.get("hello")
        assert c.stats.hits == 1
        assert c.stats.exact_hits == 1
        assert c.stats.misses == 0
        assert c.stats.tokens_saved == 10
        assert c.stats.cost_saved == 0.001

    def test_semantic_hit_stats(self):
        """Exact miss → semantic hit — covers semantic_hits counter."""
        c = LLMCache(lru_size=500, semantic_threshold=0.01, enable_semantic=True)
        c.set("the quick brown fox", "response")
        # Similar but not identical prompt
        result = c.get("a quick brown fox")
        assert result == "response"
        assert c.stats.semantic_hits == 1

    def test_miss_stats(self):
        c = LLMCache()
        c.get("never_set")
        assert c.stats.misses == 1
        assert c.stats.hits == 0

    def test_set_with_model_and_kwargs(self):
        c = LLMCache()
        c.set("hello", "world", model="gpt-4", tokens=50, cost=0.005, temp=0.7)
        # Must pass same kwargs to get
        result = c.get("hello", model="gpt-4", temp=0.7)
        assert result == "world"

    def test_different_kwargs_different_cache(self):
        c = LLMCache()
        c.set("hello", "v1", temp=0.7)
        c.set("hello", "v2", temp=0.9)
        assert c.get("hello", temp=0.7) == "v1"
        assert c.get("hello", temp=0.9) == "v2"

    def test_invalidate_lru_only(self):
        # invalidate() clears LRU; semantic may still serve
        c = LLMCache(enable_semantic=False)
        c.set("hello", "world")
        c.invalidate(key=LLMCache._hash_key("hello"))
        assert c.get("hello") is None

    def test_invalidate_tag(self):
        c = LLMCache()
        c.set("hello", "world", tag="deprecated")
        c.invalidate(tag="deprecated")
        h = LLMCache._hash_key("hello")
        assert c.lru.get(h) is None

    def test_clear(self):
        c = LLMCache()
        c.set("hello", "world")
        c.set("hi", "there")
        c.clear()
        assert c.get("hello") is None
        assert c.get("hi") is None

    def test_disable_semantic(self):
        c = LLMCache(enable_semantic=False)
        assert c.semantic is None
        c.set("hello", "world")
        assert c.get("hello") == "world"

    def test_snapshot(self):
        c = LLMCache()
        c.set("hello", "world", tokens=100, cost=0.01)
        c.get("hello")
        snap = c.snapshot()
        assert snap["lru_entries"] == 1
        assert snap["exact_hits"] == 1
        assert snap["total_requests"] == 1
        assert "hit_rate" in snap

    def test_hash_key_consistency(self):
        h1 = LLMCache._hash_key("hello", "gpt-4", temp=0.7)
        h2 = LLMCache._hash_key("hello", "gpt-4", temp=0.7)
        assert h1 == h2

    def test_hash_key_different(self):
        h1 = LLMCache._hash_key("hello", "gpt-4")
        h2 = LLMCache._hash_key("hello", "gpt-3.5")
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════
# Response Cache — CacheEntry
# ═══════════════════════════════════════════════════════════════

class TestResponseCacheEntry:
    def test_defaults(self):
        e = ResponseCacheEntry(key="k", value="v")
        assert e.key == "k"
        assert e.value == "v"
        assert e.ttl_seconds == 3600.0
        assert e.hit_count == 0
        assert e.last_accessed == 0.0
        assert e.metadata == {}

    def test_is_expired_true(self):
        e = ResponseCacheEntry(
            key="k", value="v", created_at=time.time() - 100, ttl_seconds=10
        )
        assert e.is_expired is True

    def test_is_expired_false(self):
        e = ResponseCacheEntry(key="k", value="v", ttl_seconds=9999)
        assert e.is_expired is False

    def test_is_expired_ttl_zero(self):
        e = ResponseCacheEntry(key="k", value="v", ttl_seconds=0)
        assert e.is_expired is False

    def test_age_seconds(self):
        e = ResponseCacheEntry(key="k", value="v")
        assert e.age_seconds >= 0


# ═══════════════════════════════════════════════════════════════
# Response Cache — CacheStats
# ═══════════════════════════════════════════════════════════════

class TestResponseCacheStats:
    def test_hit_rate_zero(self):
        s = ResponseCacheStats(hits=0, misses=0, size=0, max_size=100)
        assert s.hit_rate == 0.0

    def test_hit_rate_50(self):
        s = ResponseCacheStats(hits=5, misses=5, size=0, max_size=100)
        assert s.hit_rate == 0.5

    def test_utilization(self):
        s = ResponseCacheStats(size=30, max_size=100)
        assert s.utilization == 0.3

    def test_utilization_zero_max(self):
        s = ResponseCacheStats(size=10, max_size=0)
        assert s.utilization == 0.0


# ═══════════════════════════════════════════════════════════════
# Response Cache — ResponseCache
# ═══════════════════════════════════════════════════════════════

class TestResponseCache:
    def test_get_miss(self):
        rc = ResponseCache()
        assert rc.get("hello") is None

    def test_put_get(self):
        rc = ResponseCache()
        key = rc.put("hello", "world")
        assert isinstance(key, str)
        assert len(key) == 32
        assert rc.get("hello") == "world"

    def test_get_expired(self):
        rc = ResponseCache()
        rc.put("hello", "world", ttl=0.01)
        time.sleep(0.02)
        assert rc.get("hello") is None

    def test_lru_eviction(self):
        rc = ResponseCache(max_entries=2)
        rc.put("a", "1")
        rc.put("b", "2")
        rc.put("c", "3")
        assert rc.get("a") is None
        assert rc.get("b") is not None
        assert rc.get("c") is not None

    def test_lru_reorder(self):
        rc = ResponseCache(max_entries=2)
        rc.put("a", "1")
        rc.put("b", "2")
        rc.get("a")  # a becomes most recent
        rc.put("c", "3")
        assert rc.get("b") is None
        assert rc.get("a") == "1"
        assert rc.get("c") == "3"

    def test_invalidate(self):
        rc = ResponseCache()
        rc.put("hello", "world")
        assert rc.invalidate("hello") is True
        assert rc.get("hello") is None

    def test_invalidate_missing(self):
        rc = ResponseCache()
        assert rc.invalidate("missing") is False

    def test_clear(self):
        rc = ResponseCache()
        rc.put("a", "1")
        rc.put("b", "2")
        rc.clear()
        assert rc.get("a") is None
        assert rc.get("b") is None

    def test_clear_expired(self):
        rc = ResponseCache()
        rc.put("fresh", "data", ttl=9999)
        rc.put("stale", "old", ttl=0.01)
        time.sleep(0.02)
        removed = rc.clear_expired()
        assert removed >= 1
        assert rc.get("fresh") == "data"  # still there
        assert rc.get("stale") is None

    def test_get_stats(self):
        rc = ResponseCache()
        rc.put("hello", "world")
        rc.get("hello")
        stats = rc.get_stats()
        assert stats.hits == 1
        assert stats.misses == 0
        assert stats.size == 1

    def test_get_entry(self):
        rc = ResponseCache()
        rc.put("hello", "world")
        entry = rc.get_entry("hello")
        assert entry is not None
        assert entry.value == "world"

    def test_get_entry_missing(self):
        rc = ResponseCache()
        assert rc.get_entry("missing") is None

    def test_contains(self):
        rc = ResponseCache()
        rc.put("hello", "world")
        assert "hello" in rc
        assert "missing" not in rc

    def test_len(self):
        rc = ResponseCache()
        assert len(rc) == 0
        rc.put("a", "1")
        assert len(rc) == 1

    def test_size_property(self):
        rc = ResponseCache()
        assert rc.size == 0
        rc.put("a", "1")
        assert rc.size == 1

    def test_is_full(self):
        rc = ResponseCache(max_entries=1)
        assert rc.is_full is False
        rc.put("a", "1")
        assert rc.is_full is True

    def test_custom_ttl(self):
        rc = ResponseCache(default_ttl=7200)
        rc.put("hello", "world")
        entry = rc.get_entry("hello")
        assert entry.ttl_seconds == 7200.0

    def test_put_overwrite_updates(self):
        rc = ResponseCache()
        rc.put("hello", "v1")
        rc.put("hello", "v2")
        assert rc.get("hello") == "v2"


# ═══════════════════════════════════════════════════════════════
# Response Cache — CacheKeyStrategy
# ═══════════════════════════════════════════════════════════════

class TestCacheKeyStrategy:
    def test_normalized_key(self):
        rc = ResponseCache(key_strategy=CacheKeyStrategy.NORMALIZED)
        k1 = rc.put("  Hello   World  ", "data")
        k2 = rc.put("hello world", "data")
        # Same normalized key should match
        v1 = rc.get("  Hello   World  ")
        v2 = rc.get("hello world")
        assert v1 == "data"
        assert v2 == "data"

    def test_template_key(self):
        rc = ResponseCache(key_strategy=CacheKeyStrategy.TEMPLATE)
        k1 = rc.put("greeting", "Hi!", name="Alice")
        k2 = rc.put("greeting", "Hi!", name="Bob")
        assert k1 != k2
        v1 = rc.get("greeting", name="Alice")
        v2 = rc.get("greeting", name="Bob")
        assert v1 == "Hi!"
        assert v2 == "Hi!"

    def test_exact_strategy_default(self):
        rc = ResponseCache(key_strategy=CacheKeyStrategy.EXACT)
        rc.put("Hello", "v")
        assert rc.get("Hello") == "v"
        # Different casing should be different keys
        assert rc.get("hello") is None

    def test_exact_with_context(self):
        rc = ResponseCache(key_strategy=CacheKeyStrategy.EXACT)
        rc.put("tell joke", "why 6 afraid of 7", style="funny")
        assert rc.get("tell joke", style="funny") == "why 6 afraid of 7"
        assert rc.get("tell joke", style="dark") is None


# ═══════════════════════════════════════════════════════════════
# Embedder — EmbeddingResult
# ═══════════════════════════════════════════════════════════════

class TestEmbeddingResult:
    def test_defaults(self):
        r = EmbeddingResult(vector=[1.0, 2.0])
        assert r.vector == [1.0, 2.0]
        assert r.tokens == 0
        assert r.model == ""

    def test_len(self):
        r = EmbeddingResult(vector=[1.0, 2.0, 3.0])
        assert len(r) == 3

    def test_iter(self):
        r = EmbeddingResult(vector=[1.0, 2.0])
        assert list(r) == [1.0, 2.0]

    def test_getitem(self):
        r = EmbeddingResult(vector=[1.0, 2.0, 3.0])
        assert r[1] == 2.0


# ═══════════════════════════════════════════════════════════════
# Embedder — cosine_similarity
# ═══════════════════════════════════════════════════════════════

class TestEmbedderCosineSimilarity:
    def test_identical(self):
        result = asyncio.run(cosine_similarity([1.0, 0.0], [1.0, 0.0]))
        assert result == 1.0

    def test_orthogonal(self):
        result = asyncio.run(cosine_similarity([1.0, 0.0], [0.0, 1.0]))
        assert result == 0.0

    def test_empty(self):
        result = asyncio.run(cosine_similarity([], []))
        assert result == 0.0

    def test_zero_norm(self):
        result = asyncio.run(cosine_similarity([0.0, 0.0], [1.0, 0.0]))
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════
# Embedder — get_embedder factory
# ═══════════════════════════════════════════════════════════════

class TestGetEmbedder:
    def test_openai(self):
        e = asyncio.run(get_embedder("openai"))
        from agentos.cache.embedder import OpenAIEmbedder
        assert isinstance(e, OpenAIEmbedder)
        assert e.dimension() == 1536

    def test_local(self):
        e = asyncio.run(get_embedder("local"))
        from agentos.cache.embedder import LocalEmbedder
        assert isinstance(e, LocalEmbedder)
        assert e.dimension() == 384

    def test_cohere(self):
        e = asyncio.run(get_embedder("cohere"))
        from agentos.cache.embedder import CohereEmbedder
        assert isinstance(e, CohereEmbedder)
        assert e.dimension() == 1024

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown embedder provider"):
            asyncio.run(get_embedder("unknown_provider"))


# ═══════════════════════════════════════════════════════════════
# Embedder — LocalEmbedder (inference tests, light)
# ═══════════════════════════════════════════════════════════════

class TestLocalEmbedderDimension:
    """Test dimension() without loading actual model."""

    def test_default_dimension(self):
        from agentos.cache.embedder import LocalEmbedder
        e = LocalEmbedder()
        assert e.dimension() == 384  # all-MiniLM-L6-v2 default

    def test_large_dimension(self):
        from agentos.cache.embedder import LocalEmbedder
        e = LocalEmbedder(model_name="all-mpnet-base-v2")
        assert e.dimension() == 768  # other fallback

    def test_unknown_name_dimension(self):
        from agentos.cache.embedder import LocalEmbedder
        e = LocalEmbedder(model_name="some-unknown-model")
        assert e.dimension() == 768  # fallback
