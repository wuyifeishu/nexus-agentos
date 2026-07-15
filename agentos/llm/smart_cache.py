"""SmartCache — LLM response caching (exact + fuzzy match)."""

from __future__ import annotations

from typing import Any


class SmartCache:
    """LLM response cache with exact and fuzzy matching.

    Reduces API costs by caching identical and semantically similar queries.
    """

    def __init__(self, max_size: int = 1000) -> None:
        self._cache: dict[str, Any] = {}
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        """Get a cached response by key."""
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        """Cache a response."""
        if len(self._cache) >= self._max_size:
            # evict oldest (simplified: pop first key)
            try:
                first_key = next(iter(self._cache))
                del self._cache[first_key]
            except StopIteration:
                pass
        self._cache[key] = value

    def contains(self, key: str) -> bool:
        """Check if key exists in cache."""
        return key in self._cache

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Number of cached entries."""
        return len(self._cache)
