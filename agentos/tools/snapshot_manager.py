"""
SnapshotManager — generic state snapshot + rollback.

Supports:
    - Register objects that implement get_state() / restore_state(state)
    - Take named snapshots of all registered objects
    - Restore to any snapshot
    - List / delete snapshots
    - Maximum snapshot count with automatic eviction
    - Thread-safe
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable


# ============================================================================
# Snapshottable protocol
# ============================================================================

@runtime_checkable
class Snapshottable(Protocol):
    """Objects that can be snapshotted must implement these two methods."""

    def get_state(self) -> Any:
        ...

    def restore_state(self, state: Any) -> None:
        ...


# ============================================================================
# Snapshot
# ============================================================================

class Snapshot:
    """A named point-in-time state capture."""

    __slots__ = ("name", "states", "timestamp")

    def __init__(self, name: str, states: Dict[str, Any]):
        self.name = name
        self.states = states  # {object_id: state}
        self.timestamp = time.time()


# ============================================================================
# SnapshotManager
# ============================================================================

class SnapshotManager:
    """Manages snapshots of Snapshottable objects.

    Usage:
        class ConfigStore:
            def get_state(self): return {"version": self.version}
            def restore_state(self, state): self.version = state["version"]

        manager = SnapshotManager(max_snapshots=10)
        manager.register("config", ConfigStore())

        # Take snapshot
        manager.snapshot("before_update")

        # ... make changes ...

        # Roll back
        manager.rollback("before_update")
    """

    def __init__(self, max_snapshots: int = 20):
        if max_snapshots < 1:
            raise ValueError("max_snapshots must be >= 1")
        self._max_snapshots = max_snapshots
        self._objects: Dict[str, Snapshottable] = {}
        self._snapshots: List[Snapshot] = []
        self._lock = threading.RLock()

    # ---------- Registration ----------

    def register(self, name: str, obj: Any) -> None:
        if not isinstance(obj, Snapshottable):
            raise TypeError(
                f"Object '{name}' does not implement Snapshottable "
                f"(needs get_state() / restore_state(state))"
            )
        with self._lock:
            self._objects[name] = obj

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._objects.pop(name, None) is not None

    @property
    def registered(self) -> List[str]:
        with self._lock:
            return sorted(self._objects.keys())

    # ---------- Snapshots ----------

    def snapshot(self, name: str) -> Snapshot:
        """Capture current state of all registered objects."""
        with self._lock:
            states = {}
            for obj_name, obj in self._objects.items():
                states[obj_name] = obj.get_state()

            snap = Snapshot(name=name, states=states)
            self._snapshots.append(snap)

            # Evict oldest if over limit
            excess = len(self._snapshots) - self._max_snapshots
            if excess > 0:
                self._snapshots = self._snapshots[excess:]

            return snap

    def rollback(self, name: str, raise_on_missing: bool = True) -> bool:
        """Restore all registered objects to a named snapshot."""
        snap = self._find_snapshot(name)
        if snap is None:
            if raise_on_missing:
                raise KeyError(f"Snapshot '{name}' not found")
            return False

        with self._lock:
            restored = 0
            for obj_name, state in snap.states.items():
                obj = self._objects.get(obj_name)
                if obj is not None:
                    obj.restore_state(state)
                    restored += 1
            return restored > 0

    def _find_snapshot(self, name: str) -> Optional[Snapshot]:
        with self._lock:
            for snap in reversed(self._snapshots):
                if snap.name == name:
                    return snap
        return None

    # ---------- Management ----------

    def list_snapshots(self) -> List[str]:
        with self._lock:
            return [s.name for s in self._snapshots]

    def delete_snapshot(self, name: str) -> bool:
        with self._lock:
            before = len(self._snapshots)
            self._snapshots = [s for s in self._snapshots if s.name != name]
            return len(self._snapshots) < before

    def clear(self) -> None:
        with self._lock:
            self._snapshots.clear()

    @property
    def snapshot_count(self) -> int:
        with self._lock:
            return len(self._snapshots)
