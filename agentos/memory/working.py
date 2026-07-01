"""
工作记忆 — 当前会话上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
