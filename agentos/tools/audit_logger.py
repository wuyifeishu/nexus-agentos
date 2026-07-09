"""
AuditLogger — ring-buffer audit log with JSON export, level filtering, and callbacks.

Supports:
    - Structured audit events (actor, action, resource, outcome, details)
    - Severity levels (INFO, WARNING, ERROR, CRITICAL)
    - Ring buffer with configurable capacity
    - JSON export (to file or string)
    - Level-based filtering
    - Subscription callbacks for real-time forwarding
    - Thread-safe append
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# ============================================================================
# Severity
# ============================================================================


class Severity(Enum):
    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40

    @classmethod
    def from_str(cls, s: str) -> Severity:
        return getattr(cls, s.upper(), cls.INFO)


# ============================================================================
# AuditEvent
# ============================================================================


@dataclass
class AuditEvent:
    """Single audit log entry."""

    actor: str = ""  # who performed the action
    action: str = ""  # what was done (e.g., "user.delete", "config.update")
    resource: str = ""  # what was acted upon (e.g., "user:123", "/etc/config.yaml")
    outcome: str = ""  # "success", "failure", "denied"
    severity: Severity = Severity.INFO
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.name
        d["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.timestamp))
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditEvent:
        return cls(
            actor=d.get("actor", ""),
            action=d.get("action", ""),
            resource=d.get("resource", ""),
            outcome=d.get("outcome", ""),
            severity=Severity.from_str(d.get("severity", "INFO")),
            details=d.get("details", {}),
            timestamp=d.get("timestamp", time.time()),
        )


# ============================================================================
# AuditLogger
# ============================================================================


class AuditLogger:
    """Ring-buffer audit logger.

    Usage:
        audit = AuditLogger(capacity=2000)

        # Record an event
        audit.log(
            actor="admin",
            action="user.delete",
            resource="user:42",
            outcome="success",
            severity=Severity.WARNING,
            details={"reason": "GDPR request"},
        )

        # Export as JSON
        audit.export_json("audit_2026.json")

        # Subscribe to events in real-time
        audit.subscribe(lambda event: forward_to_siem(event))

        # Query with filter
        recent_failures = audit.query(
            min_severity=Severity.ERROR,
            limit=50,
        )
    """

    def __init__(self, capacity: int = 5000):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._buffer: list[AuditEvent] = []
        self._lock = threading.RLock()
        self._subscribers: list[Callable[[AuditEvent], None]] = []

    # ---------- log ----------

    def log(
        self,
        actor: str = "",
        action: str = "",
        resource: str = "",
        outcome: str = "",
        severity: Severity = Severity.INFO,
        details: dict[str, Any] | None = None,
        event: AuditEvent | None = None,
    ) -> AuditEvent:
        """Record an audit event. Accepts either field args or an AuditEvent object."""
        if event is None:
            event = AuditEvent(
                actor=actor,
                action=action,
                resource=resource,
                outcome=outcome,
                severity=severity,
                details=details or {},
            )
        with self._lock:
            self._buffer.append(event)
            # Ring buffer eviction
            excess = len(self._buffer) - self._capacity
            if excess > 0:
                self._buffer = self._buffer[excess:]

        # Notify subscribers outside lock
        self._notify(event)
        return event

    # ---------- query ----------

    def query(
        self,
        actor: str | None = None,
        action: str | None = None,
        resource: str | None = None,
        outcome: str | None = None,
        min_severity: Severity | None = None,
        max_severity: Severity | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        """Query audit events with optional filters."""
        with self._lock:
            results = list(self._buffer)

        if actor:
            results = [e for e in results if e.actor == actor]
        if action:
            results = [e for e in results if e.action == action]
        if resource:
            results = [e for e in results if e.resource == resource]
        if outcome:
            results = [e for e in results if e.outcome == outcome]
        if min_severity:
            results = [e for e in results if e.severity.value >= min_severity.value]
        if max_severity:
            results = [e for e in results if e.severity.value <= max_severity.value]
        if since is not None:
            results = [e for e in results if e.timestamp >= since]
        if until is not None:
            results = [e for e in results if e.timestamp <= until]

        if limit is not None and limit > 0:
            results = results[-limit:]

        return results

    def recent(self, count: int = 20) -> list[AuditEvent]:
        """Return the most recent N events."""
        with self._lock:
            return self._buffer[-count:] if count < len(self._buffer) else list(self._buffer)

    # ---------- export ----------

    def export_json(self, path: str | None = None) -> str:
        """Export all events as JSON. If path given, writes to file."""
        with self._lock:
            data = [e.to_dict() for e in self._buffer]

        json_str = json.dumps(data, indent=2, ensure_ascii=False)

        if path:
            Path(path).write_text(json_str, encoding="utf-8")

        return json_str

    # ---------- subscription ----------

    def subscribe(self, callback: Callable[[AuditEvent], None]) -> None:
        """Register a callback for real-time event forwarding."""
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[AuditEvent], None]) -> bool:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)
                return True
        return False

    def _notify(self, event: AuditEvent) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(event)
            except Exception:
                pass

    # ---------- info ----------

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def capacity(self) -> int:
        return self._capacity
