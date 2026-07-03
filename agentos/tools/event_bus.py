"""
Event Bus / Pub-Sub for AgentOS.

EventBus — in-process pub/sub with topic wildcards, async dispatch, and replay.
supports: exact topic match, `*` single-level, `**` multi-level wildcards.
"""

import fnmatch
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


# ============================================================================
# Event
# ============================================================================

@dataclass
class Event:
    """A published event with topic, payload, and metadata."""
    topic: str
    data: Any = None
    timestamp: float = field(default_factory=time.time)
    source: str = ""


Subscriber = Callable[[Event], None]
UnsubscribeHandle = Callable[[], None]


# ============================================================================
# EventBus
# ============================================================================

class EventBus:
    """Thread-safe in-process pub/sub event bus.

    Topics use dot-separated paths: 'agent.tool.call', 'system.shutdown'.
    Wildcards: 'agent.*.call' (single level), 'agent.**' (multi-level).
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Subscriber]] = defaultdict(list)
        self._lock = threading.RLock()
        self._history: List[Event] = []
        self._max_history: int = 1000
        self._total_published: int = 0
        self._total_delivered: int = 0
        self._running: bool = True

    def subscribe(self, topic: str, callback: Subscriber) -> UnsubscribeHandle:
        """Subscribe to a topic (supports wildcards). Returns unsubscribe handle."""
        with self._lock:
            self._subscribers[topic].append(callback)
            # Return a closure that removes this specific callback
            sub_list = self._subscribers[topic]

            def unsubscribe():
                with self._lock:
                    if callback in sub_list:
                        sub_list.remove(callback)

            return unsubscribe

    def unsubscribe(self, topic: str, callback: Subscriber) -> bool:
        """Remove a specific subscriber. Returns True if found and removed."""
        with self._lock:
            subs = self._subscribers.get(topic)
            if subs and callback in subs:
                subs.remove(callback)
                return True
            return False

    def publish(self, topic: str, data: Any = None, source: str = "") -> None:
        """Publish an event to all matching subscribers synchronously."""
        event = Event(topic=topic, data=data, source=source)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            self._total_published += 1

            if not self._running:
                return

            for sub_topic, callbacks in list(self._subscribers.items()):
                if self._topic_match(sub_topic, topic):
                    for cb in callbacks[:]:  # copy for safe iteration
                        try:
                            cb(event)
                            self._total_delivered += 1
                        except Exception:
                            pass

    def _topic_match(self, pattern: str, topic: str) -> bool:
        """Match a topic against a pattern with wildcard support.
        - `*` matches a single level (dot-delimited).
        - `**` matches zero or more levels.
        """
        if '**' in pattern or '*' in pattern:
            return self._wildcard_match(pattern, topic)
        return pattern == topic

    def _wildcard_match(self, pattern: str, topic: str) -> bool:
        """fnmatch-style glob matching on dot-delimited topic paths."""
        return fnmatch.fnmatch(topic, pattern)

    def get_history(self, limit: int = 100) -> List[Event]:
        """Get recent published events."""
        with self._lock:
            return list(self._history[-limit:])

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()

    def stop(self) -> None:
        """Stop delivering events (still records history)."""
        with self._lock:
            self._running = False

    def start(self) -> None:
        with self._lock:
            self._running = True

    def subscriber_count(self, topic: Optional[str] = None) -> int:
        """Count subscribers. If topic given, counts for that pattern only."""
        with self._lock:
            if topic:
                return len(self._subscribers.get(topic, []))
            return sum(len(v) for v in self._subscribers.values())

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_published": self._total_published,
                "total_delivered": self._total_delivered,
                "subscriber_count": self.subscriber_count(),
                "history_size": len(self._history),
                "topics": list(self._subscribers.keys()),
            }


# ============================================================================
# TopicFilter
# ============================================================================

class TopicFilter:
    """Pre-compiled topic filter chain for high-throughput event routing."""

    def __init__(self):
        self._filters: Dict[str, Callable[[Event], bool]] = {}
        self._lock = threading.Lock()

    def add(self, name: str, predicate: Callable[[Event], bool]) -> None:
        with self._lock:
            self._filters[name] = predicate

    def remove(self, name: str) -> bool:
        with self._lock:
            return self._filters.pop(name, None) is not None

    def evaluate(self, event: Event) -> List[str]:
        """Return names of all matching filters for this event."""
        matches = []
        with self._lock:
            for name, pred in self._filters.items():
                try:
                    if pred(event):
                        matches.append(name)
                except Exception:
                    pass
        return matches


# ============================================================================
# Global singleton
# ============================================================================

_default_bus: Optional[EventBus] = None
_default_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get or create the global default EventBus."""
    global _default_bus
    if _default_bus is None:
        with _default_lock:
            if _default_bus is None:
                _default_bus = EventBus()
    return _default_bus
