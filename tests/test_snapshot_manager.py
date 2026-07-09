"""Tests for agentos.tools.snapshot_manager."""

import pytest

from agentos.tools.snapshot_manager import SnapshotManager, Snapshottable


class CounterStore:
    def __init__(self, value=0):
        self.value = value

    def get_state(self):
        return {"value": self.value}

    def restore_state(self, state):
        self.value = state["value"]


class MultiFieldStore:
    def __init__(self, a=0, b=""):
        self.a = a
        self.b = b

    def get_state(self):
        return {"a": self.a, "b": self.b}

    def restore_state(self, state):
        self.a = state["a"]
        self.b = state["b"]


class NonSnapshottable:
    pass


class TestSnapshotManager:
    def test_register_and_snapshot(self):
        sm = SnapshotManager()
        c = CounterStore(0)
        sm.register("counter", c)
        c.value = 42
        sm.snapshot("s1")
        c.value = 99
        sm.rollback("s1")
        assert c.value == 42

    def test_register_non_snapshottable_raises(self):
        sm = SnapshotManager()
        with pytest.raises(TypeError, match="Snapshottable"):
            sm.register("bad", NonSnapshottable())

    def test_unregister(self):
        sm = SnapshotManager()
        sm.register("c", CounterStore())
        assert sm.unregister("c")
        assert not sm.unregister("c")
        assert "c" not in sm.registered

    def test_rollback_missing_snapshot_raises(self):
        sm = SnapshotManager()
        sm.register("c", CounterStore())
        with pytest.raises(KeyError):
            sm.rollback("ghost")

    def test_rollback_missing_no_raise(self):
        sm = SnapshotManager()
        sm.register("c", CounterStore())
        assert sm.rollback("ghost", raise_on_missing=False) is False

    def test_multiple_objects(self):
        sm = SnapshotManager()
        c = CounterStore(10)
        m = MultiFieldStore(1, "hello")
        sm.register("counter", c)
        sm.register("multi", m)

        sm.snapshot("base")
        c.value = 99
        m.a = 2
        m.b = "world"

        sm.rollback("base")
        assert c.value == 10
        assert m.a == 1
        assert m.b == "hello"

    def test_multiple_snapshots(self):
        sm = SnapshotManager()
        c = CounterStore(0)

        sm.register("c", c)
        c.value = 1
        sm.snapshot("s1")
        c.value = 2
        sm.snapshot("s2")
        c.value = 3

        sm.rollback("s1")
        assert c.value == 1
        sm.rollback("s2")
        assert c.value == 2

    def test_list_snapshots(self):
        sm = SnapshotManager()
        sm.register("c", CounterStore())
        sm.snapshot("a")
        sm.snapshot("b")
        assert sm.list_snapshots() == ["a", "b"]

    def test_delete_snapshot(self):
        sm = SnapshotManager()
        sm.register("c", CounterStore())
        sm.snapshot("keep")
        sm.snapshot("drop")
        assert sm.delete_snapshot("drop")
        assert sm.list_snapshots() == ["keep"]

    def test_clear(self):
        sm = SnapshotManager()
        sm.register("c", CounterStore())
        sm.snapshot("s1")
        sm.clear()
        assert sm.snapshot_count == 0

    def test_max_snapshots_eviction(self):
        sm = SnapshotManager(max_snapshots=3)
        sm.register("c", CounterStore())
        for i in range(5):
            sm.snapshot(f"s{i}")
        assert sm.snapshot_count == 3
        # oldest evicted
        assert "s0" not in sm.list_snapshots()
        assert "s1" not in sm.list_snapshots()

    def test_invalid_max_snapshots(self):
        with pytest.raises(ValueError):
            SnapshotManager(max_snapshots=0)

    def test_rollback_only_restores_registered(self):
        sm = SnapshotManager()
        c = CounterStore(10)
        sm.register("c", c)
        c.value = 20
        sm.snapshot("s")
        sm.unregister("c")

        # Object removed after snapshot — rollback finds no target
        # Snapshottable protocol check at register time only
        assert sm.rollback("s") is False

    def test_snapshottable_protocol(self):
        assert isinstance(CounterStore(), Snapshottable)
        assert not isinstance(NonSnapshottable(), Snapshottable)
