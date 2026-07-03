"""
RequestDeduplicator — fingerprint-based concurrent request deduplication.

Supports:
    - Fingerprint generation from request parameters
    - In-flight deduplication (same fingerprint → wait for existing result)
    - Result caching with TTL (return cached result on duplicate)
    - Thread-safe + async-safe
    - Auto-cleanup of expired entries
    - Configurable max cache size
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple


# ============================================================================
# Result
# ============================================================================

class ResultStatus(Enum):
    COMPLETED = "completed"
    ERROR = "error"


class DedupResult:
    __slots__ = ("status", "value", "timestamp")

    def __init__(self, status: ResultStatus, value: Any):
        self.status = status
        self.value = value
        self.timestamp = time.time()


# ============================================================================
# RequestDeduplicator
# ============================================================================

class RequestDeduplicator:
    """Fingerprint-based request deduplication with result caching.

    Usage:
        dedup = RequestDeduplicator(ttl=30.0)

        # Option A: manual
        key = dedup.create_key(method="POST", path="/api/users", body={"name": "Alice"})
        result = dedup.get(key)
        if result:
            return result.value

        dedup.mark_in_flight(key)
        try:
            response = do_request(...)
            dedup.complete(key, response)
        except Exception as e:
            dedup.error(key, e)
            raise

        # Option B: decorator
        @dedup.deduplicate(key_fn=lambda *a, **kw: f"{a[0]}_{a[1]}")
        def fetch(user_id, query):
            return api_call(user_id, query)
    """

    def __init__(
        self,
        ttl: float = 60.0,
        max_entries: int = 10000,
        key_prefix: str = "dedup:",
    ):
        self._ttl = ttl
        self._max_entries = max_entries
        self._key_prefix = key_prefix
        self._cache: Dict[str, DedupResult] = {}
        self._in_flight: Dict[str, threading.Event] = {}
        self._in_flight_results: Dict[str, DedupResult] = {}
        self._lock = threading.RLock()
        self._last_cleanup = time.time()

    # ---------- key generation ----------

    def create_key(self, *args: Any, **kwargs: Any) -> str:
        """Generate a unique fingerprint key from args/kwargs.

        Args are hashed positionally; kwargs are sorted by key.
        """
        payload: Dict[str, Any] = {"args": args, "kwargs": dict(sorted(kwargs.items()))}
        raw = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"{self._key_prefix}{digest}"

    # ---------- lookup ----------

    def get(self, key: str) -> Optional[Any]:
        """Return cached result if available and not expired. None if not found."""
        self._maybe_cleanup()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            age = time.time() - entry.timestamp
            if age > self._ttl:
                del self._cache[key]
                return None
            return entry

    def get_or_none(self, key: str) -> Optional[Any]:
        """Same as get() but returns the raw value or None."""
        entry = self.get(key)
        if entry:
            return entry.value
        return None

    # ---------- in-flight management ----------

    def mark_in_flight(self, key: str) -> bool:
        """Mark key as in-flight. Returns True if we should proceed (first caller).
        Returns False if another caller is already processing — caller should wait.
        """
        with self._lock:
            if key in self._in_flight:
                return False
            self._in_flight[key] = threading.Event()
            return True

    def wait_in_flight(self, key: str, timeout: Optional[float] = None) -> Optional[Any]:
        """Wait for an in-flight request to complete, then return its result."""
        event = None
        with self._lock:
            event = self._in_flight.get(key)
        if event is None:
            return None
        signaled = event.wait(timeout=timeout)
        if not signaled:
            return None
        with self._lock:
            result = self._in_flight_results.pop(key, None)
            self._in_flight.pop(key, None)
        if result:
            return result.value
        return None

    def complete(self, key: str, result: Any) -> None:
        """Signal completion and cache the result."""
        with self._lock:
            entry = DedupResult(ResultStatus.COMPLETED, result)
            self._cache[key] = entry
            self._in_flight_results[key] = entry
            event = self._in_flight.get(key)
        # Signal outside lock to avoid deadlock
        if event:
            event.set()
        self._evict_if_needed()

    def error(self, key: str, error: Exception) -> None:
        """Signal error for in-flight request."""
        with self._lock:
            entry = DedupResult(ResultStatus.ERROR, error)
            self._in_flight_results[key] = entry
            event = self._in_flight.get(key)
        if event:
            event.set()

    # ---------- decorator ----------

    def deduplicate(
        self,
        key_fn: Callable[..., str],
        wait_timeout: Optional[float] = 30.0,
        cache_errors: bool = False,
    ):
        """Decorator: deduplicate concurrent calls with same fingerprint.

        Args:
            key_fn: function(*args, **kwargs) → key string
            wait_timeout: max wait for in-flight request
            cache_errors: if True, cache error results too
        """

        def decorator(func: Callable) -> Callable:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                key = key_fn(*args, **kwargs)

                # Check cache first
                cached = self.get(key)
                if cached is not None:
                    if cached.status == ResultStatus.ERROR:
                        if not cache_errors:
                            pass  # fall through to re-execute
                        else:
                            raise cached.value if isinstance(cached.value, Exception) else Exception(str(cached.value))
                    else:
                        return cached.value

                # Try to claim in-flight
                if self.mark_in_flight(key):
                    try:
                        result = func(*args, **kwargs)
                        self.complete(key, result)
                        return result
                    except Exception as e:
                        if cache_errors:
                            self.complete(key, e)
                        else:
                            self.error(key, e)
                        raise
                else:
                    # Another caller is processing — wait
                    result = self.wait_in_flight(key, timeout=wait_timeout)
                    if result is not None:
                        return result
                    # Timeout: fall through to execute ourselves
                    raise TimeoutError(f"Timeout waiting for deduplicated request: {key}")

            return wrapper

        return decorator

    # ---------- cache maintenance ----------

    def _maybe_cleanup(self) -> None:
        """Trigger cleanup if enough time has passed."""
        now = time.time()
        if now - self._last_cleanup < self._ttl:
            return
        self._last_cleanup = now
        with self._lock:
            expired = [
                k for k, v in self._cache.items()
                if now - v.timestamp > self._ttl
            ]
            for k in expired:
                del self._cache[k]

    def _evict_if_needed(self) -> None:
        with self._lock:
            excess = len(self._cache) - self._max_entries
            if excess <= 0:
                return
            # Evict oldest entries
            sorted_by_age = sorted(self._cache.items(), key=lambda x: x[1].timestamp)
            for k, _ in sorted_by_age[:excess]:
                del self._cache[k]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._in_flight.clear()
            self._in_flight_results.clear()

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._in_flight)
