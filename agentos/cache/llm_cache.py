"""
AgentOS v0.40 LLM Cache — 语义缓存减少API调用成本。
支持：精确匹配缓存、语义相似度缓存、LRU淘汰、TTL过期。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class CacheEntry:
    """A cached LLM response with metadata.

    Attributes:
        key: Cache lookup key (typically hash of prompt + model).
        value: Cached response content.
        tokens_saved: Tokens saved by serving from cache.
        cost_saved: Estimated cost saved.
        created_at: Unix timestamp of cache insertion.
        ttl: Time-to-live in seconds.
        hit_count: Number of cache hits.
        tags: Optional tags for cache invalidation.
    """
    key: str
    value: Any
    tokens_saved: int = 0
    cost_saved: float = 0.0
    created_at: float = field(default_factory=time.time)
    ttl: float = 3600  # 默认1小时
    hit_count: int = 0
    tags: list[str] = field(default_factory=list)

    @property
    def expired(self) -> bool:
        return time.time() > self.created_at + self.ttl


class LRUCache:
    """LRU淘汰的内存缓存。"""

    def __init__(self, max_size: int = 500):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_size = max_size

    def get(self, key: str) -> Optional[CacheEntry]:
        entry = self._cache.get(key)
        if entry:
            if entry.expired:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            entry.hit_count += 1
            return entry
        return None

    def put(self, key: str, entry: CacheEntry):
        if len(self._cache) >= self.max_size and key not in self._cache:
            self._cache.popitem(last=False)  # 淘汰最久未用
        self._cache[key] = entry
        self._cache.move_to_end(key)

    def invalidate(self, key: str | None = None, tag: str | None = None):
        if key:
            self._cache.pop(key, None)
        elif tag:
            to_delete = [k for k, v in self._cache.items() if tag in v.tags]
            for k in to_delete:
                del self._cache[k]

    def size(self) -> int:
        return len(self._cache)

    def clear(self):
        self._cache.clear()


class SemanticCache:
    """语义缓存 — 基于embedding相似度的缓存匹配。"""

    def __init__(self, similarity_threshold: float = 0.92, embedder: Any = None):
        self.threshold = similarity_threshold
        self._entries: list[tuple[list[float], CacheEntry]] = []
        self._embedder = embedder  # 外部注入的embedding函数
        self.max_entries = 200

    def _embed(self, text: str) -> list[float]:
        if self._embedder:
            return self._embedder(text)
        # 默认回退：简易TF-IDF风格hash
        tokens = text.lower().split()
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        vec = [hash(w) % 100 / 100.0 * tf.get(w, 0) for w in sorted(set(tokens))[:128]]
        return vec[:64] if len(vec) > 64 else vec + [0.0] * (64 - len(vec))

    @staticmethod
    def cosine_sim(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x**2 for x in a) ** 0.5
        norm_b = sum(x**2 for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(self, query: str) -> Optional[CacheEntry]:
        query_vec = self._embed(query)
        best_sim = 0.0
        best_entry = None
        for cached_vec, entry in self._entries:
            if entry.expired:
                continue
            sim = self.cosine_sim(query_vec, cached_vec)
            if sim > best_sim:
                best_sim = sim
                best_entry = entry
        if best_sim >= self.threshold and best_entry:
            best_entry.hit_count += 1
            return best_entry
        return None

    def add(self, query: str, entry: CacheEntry):
        vec = self._embed(query)
        self._entries.append((vec, entry))
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

    def clear(self):
        self._entries.clear()


@dataclass
class CacheStats:
    """缓存统计。"""
    total_requests: int = 0
    hits: int = 0
    misses: int = 0
    tokens_saved: int = 0
    cost_saved: float = 0.0
    exact_hits: int = 0
    semantic_hits: int = 0

    @property
    def hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests


class LLMCache:
    """
    LLM响应缓存 — 减少API调用成本。

    三层策略:
    1. 精确匹配缓存 (LRU + TTL)
    2. 语义相似度缓存
    3. 透传 (无缓存命中)
    """

    def __init__(self, lru_size: int = 500, semantic_threshold: float = 0.92, enable_semantic: bool = True):
        self.lru = LRUCache(max_size=lru_size)
        self.semantic = SemanticCache(similarity_threshold=semantic_threshold) if enable_semantic else None
        self.stats = CacheStats()

    @staticmethod
    def _hash_key(prompt: str, model: str = "", **kwargs) -> str:
        payload = prompt + model + json.dumps(kwargs, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def get(self, prompt: str, model: str = "", **kwargs) -> Optional[Any]:
        self.stats.total_requests += 1

        # 1. 精确匹配
        exact_key = self._hash_key(prompt, model, **kwargs)
        entry = self.lru.get(exact_key)
        if entry:
            self.stats.hits += 1
            self.stats.exact_hits += 1
            self.stats.tokens_saved += entry.tokens_saved
            self.stats.cost_saved += entry.cost_saved
            return entry.value

        # 2. 语义匹配
        if self.semantic:
            entry = self.semantic.search(prompt)
            if entry:
                self.stats.hits += 1
                self.stats.semantic_hits += 1
                self.stats.tokens_saved += entry.tokens_saved
                self.stats.cost_saved += entry.cost_saved
                return entry.value

        self.stats.misses += 1
        return None

    def set(self, prompt: str, value: Any, model: str = "", tokens: int = 0, cost: float = 0.0, ttl: float = 3600, **kwargs):
        exact_key = self._hash_key(prompt, model, **kwargs)
        entry = CacheEntry(key=exact_key, value=value, tokens_saved=tokens, cost_saved=cost, ttl=ttl)
        self.lru.put(exact_key, entry)

        if self.semantic:
            self.semantic.add(prompt, entry)

    def invalidate(self, key: str = "", tag: str = ""):
        self.lru.invalidate(key=key or None, tag=tag or None)

    def clear(self):
        self.lru.clear()
        if self.semantic:
            self.semantic.clear()

    def snapshot(self) -> dict:
        return {
            "lru_entries": self.lru.size(),
            "semantic_entries": len(self.semantic._entries) if self.semantic else 0,
            "hit_rate": f"{self.stats.hit_rate:.1%}",
            "tokens_saved": self.stats.tokens_saved,
            "cost_saved": f"${self.stats.cost_saved:.4f}",
            "total_requests": self.stats.total_requests,
            "exact_hits": self.stats.exact_hits,
            "semantic_hits": self.stats.semantic_hits,
        }
