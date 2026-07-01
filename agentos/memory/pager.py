"""
Virtual Memory Pager — Letta-style context memory swapping.

Inspired by OS virtual memory: when the agent's working context fills up,
pages out old/low-importance episodic memories to a persistent swap store,
and intelligently pages them back in when relevant to the current task.

Architecture:
  L1 (in-memory) ──page_out──→ SwapStore (disk/DB)
  SwapStore       ──page_in───→ L1 (promoted back)

Key features:
- Importance-weighted eviction: least important + oldest first
- Smart recall: semantic search in swap for context-relevant pages
- Page compaction: batch-compress multiple items into summary pages
- Statistics: track page hits/misses for tuning
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agentos.memory.pyramid import MemoryItem, MemoryPyramid, MemoryType, MemoryLayer


# ── Data Structures ──────────────────────────────────────────────

@dataclass
class MemoryPage:
    """A compressed page of evicted memories, like a virtual memory page."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    items: list[dict[str, Any]] = field(default_factory=list)  # serialized MemoryItem dicts
    summary: str = ""            # LLM-generated summary of page contents
    keywords: list[str] = field(default_factory=list)
    importance_avg: float = 0.0
    item_count: int = 0
    evicted_at: float = field(default_factory=time.time)
    evicted_from: str = "l1"     # which layer it was evicted from

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "items": self.items, "summary": self.summary,
            "keywords": self.keywords, "importance_avg": self.importance_avg,
            "item_count": self.item_count, "evicted_at": self.evicted_at,
            "evicted_from": self.evicted_from,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryPage":
        return cls(
            id=d.get("id", uuid.uuid4().hex[:12]),
            items=d.get("items", []), summary=d.get("summary", ""),
            keywords=d.get("keywords", []), importance_avg=d.get("importance_avg", 0.0),
            item_count=d.get("item_count", 0), evicted_at=d.get("evicted_at", time.time()),
            evicted_from=d.get("evicted_from", "l1"),
        )


@dataclass
class PagerStats:
    """Pager performance statistics."""
    total_page_outs: int = 0
    total_page_ins: int = 0
    total_items_evicted: int = 0
    total_items_recalled: int = 0
    page_hits: int = 0         # page-in found relevant data
    page_misses: int = 0       # page-in found nothing relevant
    last_page_out_at: float = 0.0
    last_page_in_at: float = 0.0

    @property
    def hit_rate(self) -> float:
        total = self.page_hits + self.page_misses
        return self.page_hits / total if total > 0 else 0.0


# ── Swap Store Backend ────────────────────────────────────────────

class SwapStore:
    """
    Persistent storage for paged-out memories.

    Default: file-based JSON store. Can be swapped for SQLite/Postgres.
    """

    def __init__(self, path: str = ""):
        self.path = path or self._default_path()
        self._pages: dict[str, MemoryPage] = {}
        self._keyword_index: dict[str, set[str]] = {}  # keyword → page_ids
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._load()

    @staticmethod
    def _default_path() -> str:
        return os.path.join(os.path.expanduser("~"), ".agentos", "memory_swap.json")

    def store(self, page: MemoryPage) -> None:
        self._pages[page.id] = page
        for kw in page.keywords:
            self._keyword_index.setdefault(kw.lower(), set()).add(page.id)
        self._flush()

    def search(self, query_keywords: list[str], limit: int = 5) -> list[MemoryPage]:
        """Keyword-based search for relevant pages."""
        scored: dict[str, float] = {}
        for kw in query_keywords:
            kw_lower = kw.lower()
            for page_id in self._keyword_index.get(kw_lower, set()):
                scored[page_id] = scored.get(page_id, 0) + 1.0

        # Sort by score desc, then by importance_avg desc
        ranked = sorted(
            scored.items(),
            key=lambda x: (x[1], self._pages.get(x[0], MemoryPage()).importance_avg),
            reverse=True,
        )
        return [self._pages[pid] for pid, _ in ranked[:limit]]

    def get(self, page_id: str) -> Optional[MemoryPage]:
        return self._pages.get(page_id)

    def remove(self, page_id: str) -> bool:
        page = self._pages.pop(page_id, None)
        if page:
            for kw in page.keywords:
                idx = self._keyword_index.get(kw.lower(), set())
                idx.discard(page_id)
                if not idx:
                    del self._keyword_index[kw.lower()]
            self._flush()
            return True
        return False

    def list_all(self) -> list[MemoryPage]:
        return list(self._pages.values())

    def clear(self) -> None:
        self._pages.clear()
        self._keyword_index.clear()
        self._flush()

    def _flush(self) -> None:
        try:
            with open(self.path, "w") as f:
                json.dump({
                    "pages": {k: v.to_dict() for k, v in self._pages.items()},
                    "keyword_index": {k: list(v) for k, v in self._keyword_index.items()},
                }, f, indent=2)
        except Exception:
            pass

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                data = json.load(f)
            self._pages = {k: MemoryPage.from_dict(v) for k, v in data.get("pages", {}).items()}
            self._keyword_index = {k: set(v) for k, v in data.get("keyword_index", {}).items()}
        except Exception:
            self._pages = {}
            self._keyword_index = {}


# ── Memory Pager ──────────────────────────────────────────────────

class MemoryPager:
    """
    Virtual memory pager for Agent context.

    Pages out old/less-important memories to swap when context is full,
    and intelligently pages them back in when needed.

    Usage:
        pager = MemoryPager(pyramid, summarizer_fn=my_summarizer)
        paged = await pager.page_out(ratio=0.8)  # evict when 80% full
        recalled = await pager.page_in(["python", "error", "debug"])
    """

    def __init__(
        self,
        pyramid: MemoryPyramid,
        summarizer_fn: Optional[Callable] = None,
        swap_store: Optional[SwapStore] = None,
        max_pages: int = 500,
        page_size: int = 10,       # items per page
        eviction_ratio: float = 0.3,  # evict this % of working+episodic when full
    ):
        self.pyramid = pyramid
        self.summarizer = summarizer_fn
        self.swap = swap_store or SwapStore()
        self.max_pages = max_pages
        self.page_size = page_size
        self.eviction_ratio = eviction_ratio
        self.stats = PagerStats()

    async def page_out(self, fill_ratio: float = 0.85) -> int:
        """
        Evict low-importance episodic+working memories to swap.

        Called when context is approaching the token limit.

        Args:
            fill_ratio: Current context fill ratio (0-1)

        Returns:
            Number of items evicted
        """
        if fill_ratio < 0.7:
            return 0  # Not full enough yet

        # Determine scale: the fuller it is, the more aggressive
        scale = min(1.0, (fill_ratio - 0.7) / 0.3)
        to_evict_count = max(1, int(len(self.pyramid._memories[MemoryType.EPISODIC]) * self.eviction_ratio * scale))

        # Collect candidates: episodic + old working memories
        candidates: list[tuple[str, MemoryItem]] = []
        for key, item in self.pyramid._memories[MemoryType.EPISODIC].items():
            candidates.append((key, item))
        for key, item in self.pyramid._memories[MemoryType.WORKING].items():
            if item.access_count < 3:  # Only evict rarely-accessed working memories
                candidates.append((key, item))

        if not candidates:
            return 0

        # Sort by (importance asc, age desc) — evict least important, oldest first
        now = time.time()
        candidates.sort(key=lambda x: (x[1].importance, -(now - x[1].created_at)))
        to_evict = candidates[:to_evict_count]

        # Batch into pages
        pages_created = 0
        for i in range(0, len(to_evict), self.page_size):
            batch = to_evict[i:i + self.page_size]
            page = await self._create_page(batch)
            self.swap.store(page)
            pages_created += 1

        self.stats.total_page_outs += pages_created
        self.stats.total_items_evicted += len(to_evict)
        self.stats.last_page_out_at = time.time()

        return len(to_evict)

    async def page_in(self, query_keywords: list[str], limit: int = 3) -> list[MemoryItem]:
        """
        Search swap for relevant memories and promote them back to L1.

        Args:
            query_keywords: Keywords to search for (e.g., current task description)
            limit: Max pages to recall

        Returns:
            List of MemoryItem that were restored
        """
        pages = self.swap.search(query_keywords, limit=limit)

        if not pages:
            self.stats.page_misses += 1
            return []

        self.stats.page_hits += 1
        self.stats.last_page_in_at = time.time()

        restored_items: list[MemoryItem] = []
        for page in pages:
            for item_dict in page.items:
                try:
                    item = MemoryItem.from_dict(item_dict)
                    # Promote back to L1 episodic memory
                    item.layer = MemoryLayer.L1
                    key = item_dict.get("metadata", {}).get("key", item.id)
                    self.pyramid._memories[MemoryType.EPISODIC][key] = item
                    self.pyramid._index[key] = item
                    restored_items.append(item)
                except Exception:
                    continue
            # Remove the page from swap (it's back in memory now)
            self.swap.remove(page.id)

        self.stats.total_page_ins += len(pages)
        self.stats.total_items_recalled += len(restored_items)

        return restored_items

    async def _create_page(self, items: list[tuple[str, MemoryItem]]) -> MemoryPage:
        """Create a compressed memory page from a batch of items."""
        page = MemoryPage()
        keywords_set: set[str] = set()
        total_imp = 0.0

        for key, item in items:
            item_dict = {
                **item.to_dict(),
                "metadata": {**item.metadata, "key": key},
            }
            page.items.append(item_dict)

            # Extract keywords from content and metadata
            if isinstance(item.content, str):
                for word in item.content.lower().split()[:20]:
                    if len(word) > 3 and word.isalpha():
                        keywords_set.add(word)
            for v in item.metadata.values():
                if isinstance(v, str) and len(v) < 50:
                    keywords_set.add(v.lower())

            total_imp += item.importance

            # Remove from pyramid
            self.pyramid._memories[item.type].pop(key, None)
            self.pyramid._index.pop(key, None)

        page.item_count = len(items)
        page.importance_avg = total_imp / len(items) if items else 0.0
        page.keywords = list(keywords_set)

        # Generate summary via LLM if available
        if self.summarizer and page.items:
            try:
                contents = "\n".join(
                    i.get("content", "") for i in page.items if isinstance(i.get("content"), str)
                )[:2000]
                page.summary = await self.summarizer(contents)
            except Exception:
                page.summary = f"{len(items)} memories, avg importance {page.importance_avg:.2f}"

        return page

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive pager statistics."""
        return {
            "total_page_outs": self.stats.total_page_outs,
            "total_page_ins": self.stats.total_page_ins,
            "total_items_evicted": self.stats.total_items_evicted,
            "total_items_recalled": self.stats.total_items_recalled,
            "page_hits": self.stats.page_hits,
            "page_misses": self.stats.page_misses,
            "hit_rate": f"{self.stats.hit_rate:.1%}",
            "swap_pages_stored": len(self.swap.list_all()),
            "last_page_out": self.stats.last_page_out_at,
            "last_page_in": self.stats.last_page_in_at,
        }


# ── Loop Integration Helper ────────────────────────────────────────

def create_paging_callback(pager: MemoryPager) -> Callable:
    """
    Create a callback for the agent loop's auto-paging hook.

    Usage:
        pager = MemoryPager(pyramid)
        loop.set_auto_paging(create_paging_callback(pager))
    """
    async def auto_paging(usage_ratio: float) -> int:
        evicted = await pager.page_out(usage_ratio)
        return evicted
    return auto_paging


async def recall_relevant_memories(
    pager: MemoryPager,
    task_description: str,
    limit: int = 3,
) -> list[MemoryItem]:
    """
    Recall memories relevant to a task from swap.

    Extracts keywords from task description and pages in relevant memories.

    Usage:
        items = await recall_relevant_memories(pager, "debug the database connection error")
    """
    keywords = [w.lower() for w in task_description.split() if len(w) > 3 and w.isalpha()]
    return await pager.page_in(keywords, limit=limit)
