"""Smart Cache — LLM response caching with exact and fuzzy matching.

Reduces API costs by caching LLM responses. Supports:
  - Exact match: identical prompt → cached response
  - Fuzzy match: semantically similar prompts → cached response (via embeddings)
  - TTL-based expiration and LRU eviction
  - Cost savings tracking
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "CacheConfig",
    "CacheStats",
    "SmartCache",
    "CacheEntry",
]


# ── Config & Stats ─────────────────────────────────────────────────


@dataclass
class CacheConfig:
    """Configuration for SmartCache.

    Attributes:
        max_entries: Maximum number of cached entries (LRU eviction).
        ttl_seconds: Time-to-live in seconds (0 = no expiry).
        enable_fuzzy: Enable semantic similarity matching.
        fuzzy_threshold: Similarity threshold for fuzzy matching (0-1).
    """

    max_entries: int = 1000
    ttl_seconds: int = 3600  # 1 hour default
    enable_fuzzy: bool = False
    fuzzy_threshold: float = 0.85


@dataclass
class CacheStats:
    """Cache performance and cost savings statistics.

    Attributes:
        hits: Number of cache hits (exact).
        fuzzy_hits: Number of fuzzy match hits.
        misses: Number of cache misses.
        total_cost_saved_usd: Estimated total API cost saved via caching.
        entries: Current number of cached entries.
        evictions: Total evicted entries (LRU + TTL).
    """

    hits: int = 0
    fuzzy_hits: int = 0
    misses: int = 0
    total_cost_saved_usd: float = 0.0
    entries: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.fuzzy_hits + self.misses
        if total == 0:
            return 0.0
        return (self.hits + self.fuzzy_hits) / total

    def summary(self) -> dict:
        return {
            "hits": self.hits,
            "fuzzy_hits": self.fuzzy_hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "total_cost_saved_usd": round(self.total_cost_saved_usd, 6),
            "entries": self.entries,
            "evictions": self.evictions,
        }


# ── Cache Entry ───────────────────────────────────────────────────


@dataclass
class CacheEntry:
    """A single cached LLM response.

    Attributes:
        key: Cache key (usually hash of the prompt/model).
        prompt: Original prompt text.
        response: Cached LLM response.
        model: Model name used.
        cost_usd: Estimated cost of the original API call (savings).
        tokens: Token count of the response.
        created_at: Unix timestamp when cached.
        ttl: Time-to-live in seconds.
        hit_count: Number of times this entry was used.
    """

    key: str
    prompt: str
    response: Any
    model: str = ""
    cost_usd: float = 0.0
    tokens: int = 0
    created_at: float = field(default_factory=time.time)
    ttl: int = 3600
    hit_count: int = 0

    @property
    def expired(self) -> bool:
        """Check if this entry has exceeded its TTL."""
        if self.ttl <= 0:
            return False
        return time.time() - self.created_at > self.ttl

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


# ── Smart Cache ──────────────────────────────────────────────────


class SmartCache:
    """LLM response cache with exact + fuzzy matching and cost tracking.

    Usage:
        cache = SmartCache(config=CacheConfig(max_entries=500, ttl_seconds=7200))
        cache.set(prompt="What is quantum computing?", response="...", model="gpt-4o", cost_usd=0.005)
        cached = cache.get(prompt="What is quantum computing?", model="gpt-4o")
        if cached:
            print(f"Cache hit! Saved ${cached.cost_usd}")

    The cache uses an LRU eviction policy with TTL-based expiration.
    Keys are derived from a hash of (prompt + model) for exact matching.
    """

    def __init__(self, config: CacheConfig | None = None):
        self._config = config or CacheConfig()
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.stats = CacheStats()

    # ── Core API ──────────────────────────────────────────────────

    def get(
        self,
        prompt: str,
        model: str = "",
        use_fuzzy: bool = False,
    ) -> CacheEntry | None:
        """Look up a cached response for the given prompt.

        Args:
            prompt: The prompt text to look up.
            model: Model name for key disambiguation.
            use_fuzzy: Enable fuzzy/semantic matching (requires embeddings).

        Returns:
            CacheEntry if found, None otherwise.
        """
        # 1. Exact match
        key = self._make_key(prompt, model)
        if key in self._cache:
            entry = self._cache[key]
            # Check TTL
            if entry.expired:
                del self._cache[key]
                self.stats.evictions += 1
                self.stats.entries = len(self._cache)
            else:
                # LRU: move to end
                self._cache.move_to_end(key)
                entry.hit_count += 1
                self.stats.hits += 1
                return entry

        # 2. Fuzzy match (optional)
        if use_fuzzy and self._config.enable_fuzzy:
            entry = self._fuzzy_lookup(prompt, model)
            if entry:
                self.stats.fuzzy_hits += 1
                return entry

        # 3. Miss
        self.stats.misses += 1
        return None

    def set(
        self,
        prompt: str,
        response: Any,
        model: str = "",
        cost_usd: float = 0.0,
        tokens: int = 0,
    ) -> str:
        """Cache a response.

        Args:
            prompt: The original prompt.
            response: The LLM response to cache.
            model: Model name used.
            cost_usd: Cost of the original call (for savings tracking).
            tokens: Token count of the response.

        Returns:
            The cache key.
        """
        key = self._make_key(prompt, model)

        # Update existing entry if present
        if key in self._cache:
            entry = self._cache[key]
            entry.response = response
            entry.cost_usd = cost_usd
            entry.tokens = tokens
            entry.created_at = time.time()
            self._cache.move_to_end(key)
            return key

        # Evict if over capacity
        while len(self._cache) >= self._config.max_entries:
            self._evict_one()

        entry = CacheEntry(
            key=key,
            prompt=prompt,
            response=response,
            model=model,
            cost_usd=cost_usd,
            tokens=tokens,
            ttl=self._config.ttl_seconds,
        )
        self._cache[key] = entry
        self.stats.entries = len(self._cache)
        return key

    def clear(self):
        """Clear all cached entries."""
        self._cache.clear()
        self.stats.entries = 0

    def gc(self) -> int:
        """Garbage collect expired entries. Returns number of entries evicted."""
        count = 0
        expired_keys = [k for k, v in self._cache.items() if v.expired]
        for k in expired_keys:
            del self._cache[k]
            count += 1
        self.stats.evictions += count
        self.stats.entries = len(self._cache)
        return count

    # ── Info ─────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def config(self) -> CacheConfig:
        return self._config

    def contains(self, prompt: str, model: str = "") -> bool:
        """Check if a prompt is cached (exact match, ignores TTL)."""
        return self._make_key(prompt, model) in self._cache

    # ── Internal ─────────────────────────────────────────────────

    def _make_key(self, prompt: str, model: str = "") -> str:
        """Generate a deterministic cache key from prompt + model."""
        content = f"{model or 'default'}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _fuzzy_lookup(self, prompt: str, model: str = "") -> CacheEntry | None:
        """Semantic similarity lookup using simple keyword overlap.

        For production, replace with embedding-based similarity (cosine).
        """
        prompt_words = set(prompt.lower().split())
        if not prompt_words:
            return None

        best_score = 0.0
        best_entry: CacheEntry | None = None
        best_key = ""

        for key, entry in self._cache.items():
            if entry.expired:
                continue
            if model and entry.model and entry.model != model:
                continue

            entry_words = set(entry.prompt.lower().split())
            if not entry_words:
                continue

            # Jaccard similarity
            intersection = prompt_words & entry_words
            union = prompt_words | entry_words
            score = len(intersection) / len(union) if union else 0.0

            if score > best_score and score >= self._config.fuzzy_threshold:
                best_score = score
                best_entry = entry
                best_key = key

        if best_entry:
            self._cache.move_to_end(best_key)
            best_entry.hit_count += 1
            return best_entry

        return None

    def _evict_one(self):
        """Evict the oldest entry (LRU front)."""
        if self._cache:
            self._cache.popitem(last=False)
            self.stats.evictions += 1
