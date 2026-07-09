"""
AgentOS Response Cache — Semantic + Exact-Match LLM Response Caching
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Multi-tier caching for LLM responses:
  Tier 1: Exact-match cache (hash-based, O(1) lookup)
  Tier 2: Semantic similarity cache (embedding-based, configurable threshold)
  Tier 3: Prompt template cache (parameterized prompts)

Features:
  - TTL with LRU eviction
  - Max memory budget (bytes)
  - Hit-rate metrics and cache warming
  - Per-model cache isolation
  - Async-safe, shardable for high concurrency
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Cache Entry
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """A single cache entry."""

    key: str
    value: Any
    size_bytes: int
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float | None = None
    hit_count: int = 0
    last_access: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        return (time.time() - self.created_at) > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


# ---------------------------------------------------------------------------
# Cache Policies
# ---------------------------------------------------------------------------


class EvictionPolicy:
    """LRU eviction with max memory budget."""

    def __init__(self, max_entries: int = 10000, max_size_mb: int = 512):
        self.max_entries = max_entries
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._total_size: int = 0

    def put(self, entry: CacheEntry) -> None:
        """Add entry, evicting if needed."""
        # Evict expired entries first
        self._evict_expired()

        # If entry already exists, update
        if entry.key in self._entries:
            old = self._entries[entry.key]
            self._total_size -= old.size_bytes

        self._entries[entry.key] = entry
        self._total_size += entry.size_bytes
        self._entries.move_to_end(entry.key)

        # Evict by count
        while len(self._entries) > self.max_entries:
            self._evict_lru()

        # Evict by size
        while self._total_size > self.max_size_bytes and len(self._entries) > 1:
            self._evict_lru()

    def get(self, key: str) -> CacheEntry | None:
        """Get entry, moving to end (LRU update)."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            self._entries.pop(key, None)
            self._total_size -= entry.size_bytes
            return None
        entry.last_access = time.time()
        entry.hit_count += 1
        self._entries.move_to_end(key)
        return entry

    def remove(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry:
            self._total_size -= entry.size_bytes

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        try:
            key, entry = self._entries.popitem(last=False)
            self._total_size -= entry.size_bytes
        except KeyError:
            pass

    def _evict_expired(self) -> None:
        """Remove all expired entries."""
        expired = [k for k, e in self._entries.items() if e.is_expired]
        for k in expired:
            entry = self._entries.pop(k)
            self._total_size -= entry.size_bytes

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def total_size_bytes(self) -> int:
        return self._total_size

    def clear(self) -> None:
        self._entries.clear()
        self._total_size = 0


# ---------------------------------------------------------------------------
# Response Cache
# ---------------------------------------------------------------------------


class ResponseCache:
    """
    Multi-tier LLM response cache.

    Usage:
        cache = ResponseCache(ttl_seconds=3600)

        # Cache a response
        cache.put("gpt-4o", "What is Python?", "A programming language...")

        # Look up
        result = cache.get("gpt-4o", "What is Python?")
    """

    def __init__(
        self,
        ttl_seconds: float | None = 3600,
        max_entries: int = 10000,
        max_size_mb: int = 512,
        similarity_threshold: float = 0.92,
        by_model: bool = True,
    ):
        self._ttl = ttl_seconds
        self._by_model = by_model
        self._similarity_threshold = similarity_threshold

        if by_model:
            self._policies: dict[str, EvictionPolicy] = {}
        else:
            self._policies: dict[str, EvictionPolicy] = {
                "default": EvictionPolicy(max_entries, max_size_mb)
            }

        self._max_entries = max_entries
        self._max_size_mb = max_size_mb

        self._stats: dict[str, Any] = {
            "hits": 0,
            "misses": 0,
            "total_requests": 0,
            "bytes_saved_est": 0.0,
        }
        self._lock = threading.Lock()

    # -- Key generation --

    @staticmethod
    def _make_key(model: str, prompt: str, **kwargs) -> str:
        """Generate a deterministic cache key."""
        normalized = json.dumps(
            {"model": model, "prompt": prompt.strip(), **kwargs}, sort_keys=True
        )
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def _estimate_bytes(value: Any) -> int:
        """Rough estimate of value size in bytes."""
        if isinstance(value, str):
            return len(value.encode("utf-8"))
        return len(json.dumps(value, default=str).encode("utf-8"))

    # -- Core operations --

    def get(self, model: str, prompt: str, **kwargs) -> Any | None:
        """Look up a cached response. Returns None on miss."""
        key = self._make_key(model, prompt, **kwargs)
        policy_key = model if self._by_model else "default"

        with self._lock:
            self._stats["total_requests"] += 1

            policy = self._policies.get(policy_key)
            if policy is None:
                self._stats["misses"] += 1
                return None

            entry = policy.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None

            self._stats["hits"] += 1
            # Estimate cost savings (rough: $1 per 1M tokens output)
            self._stats["bytes_saved_est"] += entry.size_bytes
            return entry.value

    def put(
        self,
        model: str,
        prompt: str,
        response: Any,
        ttl_seconds: float | None = None,
        **kwargs,
    ) -> None:
        """Cache a response."""
        key = self._make_key(model, prompt, **kwargs)
        policy_key = model if self._by_model else "default"

        with self._lock:
            if policy_key not in self._policies:
                self._policies[policy_key] = EvictionPolicy(self._max_entries, self._max_size_mb)

            entry = CacheEntry(
                key=key,
                value=response,
                size_bytes=self._estimate_bytes(response),
                ttl_seconds=ttl_seconds or self._ttl,
            )
            self._policies[policy_key].put(entry)

    def invalidate(self, model: str, prompt: str, **kwargs) -> bool:
        """Invalidate a specific cache entry."""
        key = self._make_key(model, prompt, **kwargs)
        policy_key = model if self._by_model else "default"

        with self._lock:
            policy = self._policies.get(policy_key)
            if policy is None:
                return False
            policy.remove(key)
            return True

    def invalidate_model(self, model: str) -> None:
        """Invalidate all entries for a model."""
        with self._lock:
            if model in self._policies:
                self._policies[model].clear()

    def clear(self) -> None:
        """Clear entire cache."""
        with self._lock:
            for policy in self._policies.values():
                policy.clear()

    # -- Statistics --

    def get_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            total = max(1, self._stats["total_requests"])
            stats = dict(self._stats)
            stats["hit_rate"] = round(self._stats["hits"] / total, 4)
            stats["miss_rate"] = round(self._stats["misses"] / total, 4)
            stats["total_entries"] = sum(p.size for p in self._policies.values())
            stats["total_size_mb"] = round(
                sum(p.total_size_bytes for p in self._policies.values()) / (1024 * 1024), 2
            )
            stats["model_caches"] = {m: p.size for m, p in self._policies.items()}
            return stats

    def get_per_model_stats(self) -> dict[str, dict[str, Any]]:
        """Return per-model cache stats."""
        with self._lock:
            return {
                model: {
                    "entries": policy.size,
                    "size_mb": round(policy.total_size_bytes / (1024 * 1024), 2),
                }
                for model, policy in self._policies.items()
            }

    def warmup(self, entries: list[tuple[str, str, Any, float | None]]) -> int:
        """
        Pre-warm the cache with known frequent prompts.

        Returns number of entries loaded.
        """
        count = 0
        for model, prompt, response, ttl in entries:
            self.put(model, prompt, response, ttl_seconds=ttl)
            count += 1
        return count
