"""Tests for agentos.tools.audit_logger — AuditEvent, AuditLogger, Severity."""

import json
import tempfile
from pathlib import Path

import pytest

from agentos.tools.audit_logger import AuditEvent, AuditLogger, Severity


class TestSeverity:
    def test_values(self):
        assert Severity.INFO.value == 10
        assert Severity.WARNING.value == 20
        assert Severity.ERROR.value == 30
        assert Severity.CRITICAL.value == 40

    def test_from_str(self):
        assert Severity.from_str("ERROR") == Severity.ERROR
        assert Severity.from_str("warning") == Severity.WARNING

    def test_from_str_default(self):
        assert Severity.from_str("garbage") == Severity.INFO


class TestAuditEvent:
    def test_defaults(self):
        e = AuditEvent()
        assert e.actor == ""
        assert e.action == ""
        assert e.outcome == ""
        assert e.severity == Severity.INFO

    def test_full_construction(self):
        e = AuditEvent(
            actor="admin",
            action="user.create",
            resource="user:1",
            outcome="success",
            severity=Severity.WARNING,
            details={"ip": "1.2.3.4"},
        )
        assert e.actor == "admin"
        assert e.action == "user.create"
        assert e.resource == "user:1"
        assert e.outcome == "success"
        assert e.severity == Severity.WARNING
        assert e.details == {"ip": "1.2.3.4"}

    def test_to_dict(self):
        e = AuditEvent(actor="admin", action="login")
        d = e.to_dict()
        assert d["actor"] == "admin"
        assert d["action"] == "login"
        assert d["severity"] == "INFO"
        assert "timestamp" in d

    def test_from_dict(self):
        d = {
            "actor": "user42",
            "action": "file.delete",
            "resource": "doc.pdf",
            "outcome": "denied",
            "severity": "ERROR",
            "details": {"reason": "perm"},
            "timestamp": 1234567890.0,
        }
        e = AuditEvent.from_dict(d)
        assert e.actor == "user42"
        assert e.action == "file.delete"
        assert e.severity == Severity.ERROR

    def test_roundtrip(self):
        e = AuditEvent(actor="alice", action="write", resource="/tmp/x", outcome="success")
        e2 = AuditEvent.from_dict(e.to_dict())
        assert e2.actor == "alice"
        assert e2.action == "write"


class TestAuditLogger:
    def test_init(self):
        al = AuditLogger(capacity=100)
        assert al.capacity == 100
        assert al.count == 0

    def test_init_negative(self):
        with pytest.raises(ValueError):
            AuditLogger(capacity=0)

    def test_log_event(self):
        al = AuditLogger()
        event = al.log(actor="admin", action="login")
        assert isinstance(event, AuditEvent)
        assert event.actor == "admin"
        assert al.count == 1

    def test_log_event_object(self):
        al = AuditLogger()
        e = AuditEvent(actor="bot", action="scrape", resource="page1", outcome="success")
        al.log(event=e)
        assert al.count == 1

    def test_ring_buffer_eviction(self):
        al = AuditLogger(capacity=3)
        for i in range(5):
            al.log(actor=f"user{i}", action="ping")
        assert al.count == 3
        events = al.recent(10)
        actors = [e.actor for e in events]
        assert "user0" not in actors
        assert "user4" in actors

    def test_query_actor(self):
        al = AuditLogger()
        al.log(actor="alice", action="read")
        al.log(actor="bob", action="write")
        results = al.query(actor="alice")
        assert len(results) == 1
        assert results[0].actor == "alice"

    def test_query_action(self):
        al = AuditLogger()
        al.log(actor="x", action="delete")
        al.log(actor="y", action="read")
        results = al.query(action="delete")
        assert len(results) == 1

    def test_query_resource(self):
        al = AuditLogger()
        al.log(actor="x", action="t", resource="db:prod")
        al.log(actor="y", action="t", resource="db:dev")
        results = al.query(resource="db:prod")
        assert len(results) == 1

    def test_query_outcome(self):
        al = AuditLogger()
        al.log(actor="a", outcome="success")
        al.log(actor="b", outcome="failure")
        results = al.query(outcome="failure")
        assert len(results) == 1

    def test_query_min_severity(self):
        al = AuditLogger()
        al.log(actor="a", severity=Severity.INFO, action="x")
        al.log(actor="a", severity=Severity.ERROR, action="y")
        results = al.query(min_severity=Severity.WARNING)
        assert len(results) == 1
        assert results[0].action == "y"

    def test_query_max_severity(self):
        al = AuditLogger()
        al.log(actor="a", severity=Severity.INFO, action="x")
        al.log(actor="a", severity=Severity.ERROR, action="y")
        results = al.query(max_severity=Severity.WARNING)
        assert len(results) == 1
        assert results[0].action == "x"

    def test_query_since_until(self):
        al = AuditLogger()
        al.log(event=AuditEvent(actor="a", action="x", timestamp=100.0))
        al.log(event=AuditEvent(actor="b", action="y", timestamp=200.0))

        results = al.query(since=150.0)
        assert len(results) == 1
        assert results[0].actor == "b"

        results2 = al.query(until=150.0)
        assert len(results2) == 1
        assert results2[0].actor == "a"

    def test_query_limit(self):
        al = AuditLogger()
        for i in range(10):
            al.log(actor=f"u{i}", action="t")
        results = al.query(limit=3)
        assert len(results) == 3

    def test_recent(self):
        al = AuditLogger()
        al.log(actor="a", action="1")
        al.log(actor="b", action="2")
        al.log(actor="c", action="3")
        recent = al.recent(2)
        assert len(recent) == 2
        assert recent[0].actor == "b"

    def test_export_json_string(self):
        al = AuditLogger()
        al.log(actor="admin")
        json_str = al.export_json()
        data = json.loads(json_str)
        assert len(data) == 1
        assert data[0]["actor"] == "admin"

    def test_export_json_file(self):
        al = AuditLogger()
        al.log(actor="admin", action="test")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            json_str = al.export_json(path=path)
            written = Path(path).read_text(encoding="utf-8")
            assert written == json_str
            data = json.loads(written)
            assert data[0]["actor"] == "admin"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_subscribe(self):
        collected = []

        def cb(event):
            collected.append(event.actor)

        al = AuditLogger()
        al.subscribe(cb)
        al.log(actor="alice", action="x")
        al.log(actor="bob", action="y")
        assert collected == ["alice", "bob"]

    def test_unsubscribe(self):
        collected = []

        def cb(event):
            collected.append(event.actor)

        al = AuditLogger()
        al.subscribe(cb)
        al.log(actor="first", action="x")
        assert al.unsubscribe(cb) is True
        al.log(actor="second", action="y")
        assert collected == ["first"]

    def test_unsubscribe_missing(self):
        al = AuditLogger()
        assert al.unsubscribe(lambda e: None) is False

    def test_subscriber_exception_handled(self):
        def cb(event):
            raise RuntimeError("boom")

        al = AuditLogger()
        al.subscribe(cb)
        al.log(actor="x")  # should not raise

    def test_count_property(self):
        al = AuditLogger()
        al.log(actor="a")
        al.log(actor="b")
        assert al.count == 2

    def test_log_with_details(self):
        al = AuditLogger()
        event = al.log(actor="admin", action="config.change", details={"key": "val"})
        assert event.details == {"key": "val"}
