"""
Serialization & Caching for AgentOS.

Serializer — adaptive serializer with JSON/msgpack/pickle auto-detection.
TTLCache — thread-safe time-to-live cache with LRU/LFU eviction.
SmartCache — compute-on-miss cache wrapping TTL cache with serializer.
"""

import json
import pickle
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, TypeVar

T = TypeVar("T")


# ============================================================================
# Serializer
# ============================================================================

class SerialFormat(Enum):
    JSON = "json"
    PICKLE = "pickle"
    MSGPACK = "msgpack"
    AUTO = "auto"

    def detect(self, data: bytes) -> "SerialFormat":
        if self != SerialFormat.AUTO:
            return self
        if data[:2] in (b'\x80\x03', b'\x80\x04', b'\x80\x05'):
            return SerialFormat.PICKLE
        if data[:1] == b'{' or data[:1] == b'[':
            return SerialFormat.JSON
        # Try msgpack header (0x80-0x8f for fixmap, 0x90-0x9f for fixarray, 0xdc/0xdd/0xde/0xdf, etc.)
        if len(data) > 0 and data[0] in range(0x80, 0x100):
            try:
                import msgpack
                msgpack.unpackb(data)
                return SerialFormat.MSGPACK
            except Exception:
                pass
        raise ValueError("Cannot auto-detect serialization format")


class Serializer:
    """Adaptive serializer with format auto-detection and compression support."""

    def __init__(self, fmt: SerialFormat = SerialFormat.JSON):
        self._fmt = fmt
        self._total_serialized: int = 0
        self._total_deserialized: int = 0

    def dumps(self, obj: Any, use_msgpack: bool = False) -> bytes:
        fmt = SerialFormat.MSGPACK if use_msgpack else self._fmt
        if fmt == SerialFormat.AUTO:
            fmt = SerialFormat.JSON

        if fmt == SerialFormat.JSON:
            data = json.dumps(obj, ensure_ascii=False, default=str)
            self._total_serialized += 1
            return data.encode('utf-8')

        elif fmt == SerialFormat.PICKLE:
            data = pickle.dumps(obj)
            self._total_serialized += 1
            return data

        elif fmt == SerialFormat.MSGPACK:
            import msgpack
            data = msgpack.packb(obj, default=str)
            self._total_serialized += 1
            return data

        raise ValueError(f"Unsupported format: {fmt}")

    def loads(self, data: bytes, fmt: Optional[SerialFormat] = None) -> Any:
        if fmt is None:
            fmt = SerialFormat.AUTO

        fmt = fmt.detect(data)

        if fmt == SerialFormat.JSON:
            result = json.loads(data.decode('utf-8'))
            self._total_deserialized += 1
            return result

        elif fmt == SerialFormat.PICKLE:
            result = pickle.loads(data)
            self._total_deserialized += 1
            return result

        elif fmt == SerialFormat.MSGPACK:
            import msgpack
            result = msgpack.unpackb(data)
            self._total_deserialized += 1
            return result

        raise ValueError(f"Unsupported format: {fmt}")

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "format": self._fmt.value if isinstance(self._fmt, SerialFormat) else self._fmt,
            "total_serialized": self._total_serialized,
            "total_deserialized": self._total_deserialized,
        }


# ============================================================================
# EvictionPolicy
# ============================================================================

class EvictionPolicy(Enum):
    LRU = "lru"
    LFU = "lfu"
    TTL_ONLY = "ttl_only"


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    expires_at: float
    access_count: int = 0
    last_access: float = field(default_factory=time.monotonic)


# ============================================================================
# TTLCache
# ============================================================================

class TTLCache(Generic[T]):
    """Thread-safe TTL cache with configurable eviction policy (LRU/LFU).

    Entries expire after ttl_seconds. On maxsize overflow, evicts based on policy.
    """

    def __init__(
        self,
        max_size: int = 1000,
        ttl: float = 300.0,
        policy: EvictionPolicy = EvictionPolicy.LRU,
    ):
        self._max_size = max_size
        self._ttl = ttl
        self._policy = policy
        self._data: OrderedDict[str, _CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    def get(self, key: str) -> Optional[T]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None

            if time.monotonic() > entry.expires_at:
                del self._data[key]
                self._misses += 1
                self._evictions += 1
                return None

            entry.access_count += 1
            entry.last_access = time.monotonic()
            # Move to end for LRU ordering
            self._data.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        with self._lock:
            if key in self._data:
                self._data.pop(key)

            if len(self._data) >= self._max_size:
                self._evict_one()

            self._data[key] = _CacheEntry(
                value=value,
                expires_at=time.monotonic() + (ttl if ttl is not None else self._ttl),
            )
            self._data.move_to_end(key)

    def _evict_one(self) -> None:
        if not self._data:
            return

        if self._policy == EvictionPolicy.TTL_ONLY:
            # Remove oldest (first inserted)
            self._data.popitem(last=False)
            self._evictions += 1
            return

        if self._policy == EvictionPolicy.LRU:
            # First item is least recently used (get moves items to end)
            self._data.popitem(last=False)
            self._evictions += 1
            return

        if self._policy == EvictionPolicy.LFU:
            # Find item with lowest access count
            victim_key = min(self._data, key=lambda k: self._data[k].access_count)
            del self._data[victim_key]
            self._evictions += 1

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                del self._data[key]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def cleanup(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = time.monotonic()
        count = 0
        with self._lock:
            expired = [k for k, v in self._data.items() if now > v.expires_at]
            for k in expired:
                del self._data[k]
                count += 1
            self._evictions += count
            return count

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._data)

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._data),
                "max_size": self._max_size,
                "ttl": self._ttl,
                "policy": self._policy.value,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(self._hits / max(1, self._hits + self._misses), 3),
            }


# ============================================================================
# SmartCache
# ============================================================================

class SmartCache(Generic[T]):
    """Compute-on-miss cache combining TTLCache with Serializer.

    Provides get_or_compute() — key misses trigger the factory function,
    result stored in cache automatically. Supports serialization for persistence.
    """

    def __init__(
        self,
        max_size: int = 1000,
        ttl: float = 300.0,
        policy: EvictionPolicy = EvictionPolicy.LRU,
    ):
        self._cache = TTLCache[T](max_size=max_size, ttl=ttl, policy=policy)
        self._serializer = Serializer()

    def get(self, key: str) -> Optional[T]:
        return self._cache.get(key)

    def get_or_compute(self, key: str, factory: Callable[[], T], ttl: Optional[float] = None) -> T:
        """Get from cache or compute via factory and cache the result."""
        value = self._cache.get(key)
        if value is not None:
            return value
        value = factory()
        self._cache.set(key, value, ttl=ttl)
        return value

    def set(self, key: str, value: T, ttl: Optional[float] = None) -> None:
        self._cache.set(key, value, ttl=ttl)

    def delete(self, key: str) -> bool:
        return self._cache.delete(key)

    def clear(self) -> None:
        self._cache.clear()

    def dump(self) -> bytes:
        """Serialize entire cache state."""
        with self._cache._lock:
            entries = {
                k: {
                    "value": v.value,
                    "expires_at": v.expires_at,
                    "access_count": v.access_count,
                    "last_access": v.last_access,
                }
                for k, v in self._cache._data.items()
            }
        return self._serializer.dumps(entries)

    def load(self, data: bytes) -> int:
        """Restore cache from serialized data. Returns number of entries loaded."""
        now = time.monotonic()
        entries = self._serializer.loads(data)
        count = 0
        for k, v in entries.items():
            if v["expires_at"] > now:
                self._cache._data[k] = _CacheEntry(
                    value=v["value"],
                    expires_at=v["expires_at"],
                    access_count=v["access_count"],
                    last_access=v["last_access"],
                )
                count += 1
        return count

    @property
    def size(self) -> int:
        return self._cache.size

    @property
    def stats(self) -> Dict[str, Any]:
        return self._cache.stats
