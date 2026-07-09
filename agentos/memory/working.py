"""
工作记忆 — 当前会话上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryItem:
    """工作记忆项。"""

    key: str
    content: str
    ttl: str = "session"  # session | days | permanent
    metadata: dict = field(default_factory=dict)


class WorkingMemory:
    """工作记忆 — 当前会话内有效，会话结束即销毁。"""

    def __init__(self, max_items: int = 100):
        self.max_items = max_items
        self._items: dict[str, MemoryItem] = {}

    def add(self, item: MemoryItem):
        self._items[item.key] = item
        if len(self._items) > self.max_items:
            oldest = next(iter(self._items))
            del self._items[oldest]

    def get(self, key: str) -> MemoryItem | None:
        return self._items.get(key)

    def search(self, query: str, limit: int = 5) -> list[MemoryItem]:
        """简单关键词匹配。"""
        results = []
        for item in self._items.values():
            if query.lower() in item.content.lower():
                results.append(item)
        return results[:limit]

    def clear(self):
        self._items.clear()

    # ── Persistence (v1.14.9) ────────────────

    def get_state(self) -> dict[str, Any]:
        """Export working memory state for persistence."""
        return {
            "max_items": self.max_items,
            "items": {
                key: {
                    "key": item.key,
                    "content": item.content,
                    "ttl": item.ttl,
                    "metadata": item.metadata,
                }
                for key, item in self._items.items()
            },
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore working memory from a persisted snapshot."""
        self.max_items = state.get("max_items", self.max_items)
        self._items.clear()
        for key, item_data in state.get("items", {}).items():
            self._items[key] = MemoryItem(
                key=item_data.get("key", key),
                content=item_data.get("content", ""),
                ttl=item_data.get("ttl", "session"),
                metadata=item_data.get("metadata", {}),
            )
