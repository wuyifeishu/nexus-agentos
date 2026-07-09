"""
Response Cache with TTL — Cached LLM responses with configurable expiry.

Supports in-memory LRU cache with TTL, disk persistence, and cache key
strategies (exact match, semantic similarity, template-based).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CacheKeyStrategy(Enum):
    """Strategy for generating cache lookup keys."""

    EXACT = "exact"
    """Hash of the full prompt/message."""

    NORMALIZED = "normalized"
    """Hash after whitespace/lowercase normalization."""

    TEMPLATE = "template"
    """Hash of template name + variables (ignores phrasing variations)."""


@dataclass
class CacheEntry:
    """A single cache entry."""

    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 3600.0
    """Time-to-live in seconds. None means no expiry."""

    hit_count: int = 0
    last_accessed: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return (time.time() - self.created_at) > self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


@dataclass
class CacheStats:
    """Cache performance statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    size: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def utilization(self) -> float:
        return self.size / self.max_size if self.max_size > 0 else 0.0


class ResponseCache:
    """
    Response cache with TTL and LRU eviction.

    Supports:
    - In-memory LRU cache with configurable TTL
    - Multiple cache key strategies (exact, normalized, template)
    - Statistics tracking (hit rate, evictions, expirations)
    - Optional disk persistence (planned)

    Example::

        cache = ResponseCache(max_entries=1000, default_ttl=3600)
        cache.put("What is 2+2?", "4")
        result = cache.get("What is 2+2?")  # "4" (cache hit)
    """

    def __init__(
        self,
        max_entries: int = 1000,
        default_ttl: float = 3600.0,
        key_strategy: CacheKeyStrategy = CacheKeyStrategy.EXACT,
    ):
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        self._key_strategy = key_strategy
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = CacheStats(max_size=max_entries)

    def get(self, prompt: str, **context: Any) -> Any | None:
        """
        Retrieve cached response for a prompt.

        Args:
            prompt: The prompt/message text.
            **context: Additional context for template-based keys.

        Returns:
            Cached value if found and not expired, else None.
        """
        key = self._make_key(prompt, context)
        entry = self._store.get(key)

        if entry is None:
            self._stats.misses += 1
            return None

        if entry.is_expired:
            self._evict(key)
            self._stats.expirations += 1
            self._stats.misses += 1
            return None

        # Move to end for LRU
        self._store.move_to_end(key)
        entry.hit_count += 1
        entry.last_accessed = time.time()
        self._stats.hits += 1
        return entry.value

    def put(
        self,
        prompt: str,
        value: Any,
        ttl: float | None = None,
        **context: Any,
    ) -> str:
        """
        Cache a response.

        Args:
            prompt: The prompt/message text.
            value: The response to cache.
            ttl: Custom TTL in seconds (default: self._default_ttl).
            **context: Additional context for template-based keys.

        Returns:
            The cache key string.
        """
        key = self._make_key(prompt, context)
        effective_ttl = ttl if ttl is not None else self._default_ttl

        if key in self._store:
            self._store.move_to_end(key)

        self._store[key] = CacheEntry(
            key=key,
            value=value,
            ttl_seconds=effective_ttl,
            last_accessed=time.time(),
        )

        self._stats.size = len(self._store)

        # Evict oldest if over capacity
        while len(self._store) > self._max_entries:
            oldest_key, _ = self._store.popitem(last=False)
            self._stats.evictions += 1

        return key

    def invalidate(self, prompt: str, **context: Any) -> bool:
        """Remove a specific cache entry. Returns True if found and removed."""
        key = self._make_key(prompt, context)
        if key in self._store:
            del self._store[key]
            self._stats.size = len(self._store)
            return True
        return False

    def clear(self) -> None:
        """Clear all cached entries."""
        self._store.clear()
        self._stats.size = 0

    def clear_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        expired = [k for k, e in self._store.items() if e.is_expired]
        for k in expired:
            del self._store[k]
        self._stats.expirations += len(expired)
        self._stats.size = len(self._store)
        return len(expired)

    def get_stats(self) -> CacheStats:
        """Return current cache statistics snapshot."""
        self._stats.size = len(self._store)
        return self._stats

    def get_entry(self, prompt: str, **context: Any) -> CacheEntry | None:
        """Get the full cache entry (including metadata) without updating LRU."""
        key = self._make_key(prompt, context)
        return self._store.get(key)

    def _evict(self, key: str) -> None:
        """Evict a specific entry."""
        if key in self._store:
            del self._store[key]
            self._stats.evictions += 1
            self._stats.size = len(self._store)

    def _make_key(self, prompt: str, context: dict[str, Any]) -> str:
        """Generate a cache key based on the configured strategy."""
        if self._key_strategy == CacheKeyStrategy.NORMALIZED:
            prompt = " ".join(prompt.lower().split())

        if self._key_strategy == CacheKeyStrategy.TEMPLATE:
            key_data = json.dumps({"template": prompt, "vars": context}, sort_keys=True)
            return hashlib.sha256(key_data.encode()).hexdigest()[:32]

        if context:
            prompt = prompt + json.dumps(context, sort_keys=True)

        return hashlib.sha256(prompt.encode()).hexdigest()[:32]

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def is_full(self) -> bool:
        return len(self._store) >= self._max_entries

    def __contains__(self, prompt: str) -> bool:
        key = self._make_key(prompt, {})
        entry = self._store.get(key)
        return entry is not None and not entry.is_expired

    def __len__(self) -> int:
        return len(self._store)
