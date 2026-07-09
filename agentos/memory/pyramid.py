"""
Memory Pyramid for NexusAgent.

Multi-layer memory management system inspired by human memory:
- Working Memory: Current task context (short-term)
- Episodic Memory: Past experiences and events
- Semantic Memory: Facts and knowledge (long-term)
- Procedural Memory: Skills and procedures
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MemoryType(StrEnum):
    """Types of memory in the pyramid."""

    WORKING = "working"  # Current task context
    EPISODIC = "episodic"  # Past experiences
    SEMANTIC = "semantic"  # Facts and knowledge
    PROCEDURAL = "procedural"  # Skills and procedures


class MemoryLayer(StrEnum):
    """Memory layers (L1=fast, L2=persistent)."""

    L1 = "l1"  # Fast, in-memory
    L2 = "l2"  # Persistent, file-based


@dataclass
class MemoryItem:
    """
    Single memory item.

    Attributes:
        id: Unique identifier
        type: Memory type
        layer: Memory layer (L1/L2)
        content: Memory content
        metadata: Additional metadata
        created_at: Creation timestamp
        accessed_at: Last access timestamp
        access_count: Number of accesses
        importance: Importance score (0-1)
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: MemoryType = MemoryType.WORKING
    layer: MemoryLayer = MemoryLayer.L1
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    access_count: int = 0
    importance: float = 0.5

    def access(self) -> None:
        """Mark as accessed."""
        self.accessed_at = time.time()
        self.access_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "type": self.type.value,
            "layer": self.layer.value,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "accessed_at": self.accessed_at,
            "access_count": self.access_count,
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryItem:
        """Create from dict."""
        return cls(
            id=data.get("id", uuid.uuid4().hex[:12]),
            type=MemoryType(data.get("type", "working")),
            layer=MemoryLayer(data.get("layer", "l1")),
            content=data.get("content"),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            accessed_at=data.get("accessed_at", time.time()),
            access_count=data.get("access_count", 0),
            importance=data.get("importance", 0.5),
        )


class MemoryPyramid:
    """
    Multi-layer memory management system.

    Organizes memories into types (working/episodic/semantic/procedural)
    and layers (L1=fast/L2=persistent).

    Usage:
        pyramid = MemoryPyramid()
        pyramid.store("user_preference", {"theme": "dark"}, MemoryType.SEMANTIC)
        prefs = pyramid.recall("user_preference")
    """

    def __init__(self, max_working: int = 100, max_episodic: int = 1000):
        """
        Initialize memory pyramid.

        Args:
            max_working: Max items in working memory
            max_episodic: Max items in episodic memory
        """
        self.max_working = max_working
        self.max_episodic = max_episodic

        # Memory storage by type
        self._memories: dict[MemoryType, dict[str, MemoryItem]] = {
            MemoryType.WORKING: {},
            MemoryType.EPISODIC: {},
            MemoryType.SEMANTIC: {},
            MemoryType.PROCEDURAL: {},
        }

        # Index for fast lookup
        self._index: dict[str, MemoryItem] = {}

    def store(
        self,
        key: str,
        content: Any,
        memory_type: MemoryType = MemoryType.WORKING,
        layer: MemoryLayer = MemoryLayer.L1,
        importance: float = 0.5,
        **metadata,
    ) -> MemoryItem:
        """
        Store a memory item.

        Args:
            key: Memory key
            content: Memory content
            memory_type: Type of memory
            layer: Memory layer
            importance: Importance score (0-1)
            **metadata: Additional metadata

        Returns:
            Created MemoryItem
        """
        # Check capacity for working memory
        if memory_type == MemoryType.WORKING:
            if len(self._memories[MemoryType.WORKING]) >= self.max_working:
                self._evict_working()

        # Check capacity for episodic memory
        if memory_type == MemoryType.EPISODIC:
            if len(self._memories[MemoryType.EPISODIC]) >= self.max_episodic:
                self._evict_episodic()

        # Create memory item
        item = MemoryItem(
            type=memory_type,
            layer=layer,
            content=content,
            metadata=metadata,
            importance=importance,
        )

        # Store
        self._memories[memory_type][key] = item
        self._index[key] = item

        return item

    def recall(self, key: str) -> MemoryItem | None:
        """
        Recall a memory item.

        Args:
            key: Memory key

        Returns:
            MemoryItem if found, None otherwise
        """
        item = self._index.get(key)
        if item:
            item.access()
        return item

    def search(
        self,
        memory_type: MemoryType | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """
        Search memories.

        Args:
            memory_type: Filter by type (None = all)
            limit: Max results

        Returns:
            List of MemoryItem, sorted by importance
        """
        if memory_type:
            items = list(self._memories[memory_type].values())
        else:
            items = []
            for mems in self._memories.values():
                items.extend(mems.values())

        # Sort by importance (descending)
        items.sort(key=lambda x: x.importance, reverse=True)

        return items[:limit]

    def forget(self, key: str) -> bool:
        """
        Forget a memory item.

        Args:
            key: Memory key

        Returns:
            True if forgotten, False if not found
        """
        item = self._index.get(key)
        if not item:
            return False

        # Remove from storage
        del self._memories[item.type][key]
        del self._index[key]

        return True

    def _evict_working(self) -> None:
        """Evict least important working memories."""
        items = list(self._memories[MemoryType.WORKING].values())
        items.sort(key=lambda x: x.importance)

        # Remove bottom 20%
        to_remove = items[: len(items) // 5 + 1]
        for item in to_remove:
            self.forget(item.metadata.get("key", ""))

    def _evict_episodic(self) -> None:
        """Evict least important episodic memories."""
        items = list(self._memories[MemoryType.EPISODIC].values())
        items.sort(key=lambda x: x.importance)

        # Remove bottom 20%
        to_remove = items[: len(items) // 5 + 1]
        for item in to_remove:
            self.forget(item.metadata.get("key", ""))

    def get_stats(self) -> dict[str, Any]:
        """
        Get memory statistics.

        Returns:
            Dict with memory counts by type
        """
        return {
            "working": len(self._memories[MemoryType.WORKING]),
            "episodic": len(self._memories[MemoryType.EPISODIC]),
            "semantic": len(self._memories[MemoryType.SEMANTIC]),
            "procedural": len(self._memories[MemoryType.PROCEDURAL]),
            "total": sum(len(m) for m in self._memories.values()),
        }

    def clear(self, memory_type: MemoryType | None = None) -> None:
        """
        Clear memories.

        Args:
            memory_type: Type to clear (None = all)
        """
        if memory_type:
            self._memories[memory_type].clear()
            # Rebuild index
            self._index.clear()
            for mems in self._memories.values():
                for item in mems.values():
                    self._index[item.metadata.get("key", item.id)] = item
        else:
            for mems in self._memories.values():
                mems.clear()
            self._index.clear()

    # ── Persistence (v1.14.9) ────────────────

    def get_state(self) -> dict[str, Any]:
        """Export full memory state for persistence."""
        return {
            "max_working": self.max_working,
            "max_episodic": self.max_episodic,
            "memories": {
                mt.value: {key: item.to_dict() for key, item in mems.items()}
                for mt, mems in self._memories.items()
            },
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore memory state from a persisted snapshot."""
        self.max_working = state.get("max_working", self.max_working)
        self.max_episodic = state.get("max_episodic", self.max_episodic)
        self._memories = {mt: {} for mt in MemoryType}
        self._index.clear()

        memories_data = state.get("memories", {})
        for mt_str, items_dict in memories_data.items():
            try:
                mt = MemoryType(mt_str)
            except ValueError:
                continue
            for key, item_data in items_dict.items():
                item = MemoryItem.from_dict(item_data)
                self._memories[mt][key] = item
                self._index[key] = item
