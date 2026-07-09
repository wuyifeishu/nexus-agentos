"""Tests for agentos.core.session — Session and SessionStore."""

from agentos.core.session import Session, SessionStore


class TestSession:
    def test_default_creation(self):
        s = Session()
        assert len(s.id) == 12
        assert s.state == "active"
        assert s.task == ""
        assert s.metadata == {}

    def test_custom_task(self):
        s = Session(task="analyze data")
        assert s.task == "analyze data"

    def test_custom_metadata(self):
        s = Session(metadata={"user": "alice"})
        assert s.metadata["user"] == "alice"

    def test_unique_ids(self):
        s1 = Session()
        s2 = Session()
        assert s1.id != s2.id


class TestSessionStore:
    def test_create(self):
        store = SessionStore()
        s = store.create("test task")
        assert s.task == "test task"
        assert s.state == "active"
        assert store.get(s.id) is s

    def test_create_with_metadata(self):
        store = SessionStore()
        s = store.create("task", {"priority": "high"})
        assert s.metadata["priority"] == "high"

    def test_get_missing(self):
        store = SessionStore()
        assert store.get("nonexistent") is None

    def test_update_state(self):
        store = SessionStore()
        s = store.create("task")
        store.update_state(s.id, "completed")
        assert s.state == "completed"

    def test_update_state_missing(self):
        store = SessionStore()
        store.update_state("nope", "completed")  # no error

    def test_list_active(self):
        store = SessionStore()
        s1 = store.create("t1")
        s2 = store.create("t2")
        store.update_state(s1.id, "completed")

        active = store.list_active()
        assert len(active) == 1
        assert active[0].id == s2.id

    def test_list_active_empty(self):
        store = SessionStore()
        assert store.list_active() == []

    def test_delete(self):
        store = SessionStore()
        s = store.create("task")
        store.delete(s.id)
        assert store.get(s.id) is None

    def test_delete_missing(self):
        store = SessionStore()
        store.delete("nope")  # no error
