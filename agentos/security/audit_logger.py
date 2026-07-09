"""Audit Logger — immutable, append-only audit trail for agent operations.

Records every tool call, agent action, and routing decision as JSONL events.
Supports session grouping, severity filtering, and stats aggregation.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

__all__ = [
    "AuditSeverity",
    "AuditActionCategory",
    "AuditEvent",
    "AuditLogger",
]


# ── Enums ─────────────────────────────────────────────────────────


class AuditSeverity(Enum):
    """Severity level for audit events."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditActionCategory(Enum):
    """Category of the audited action."""

    TOOL_CALL = "tool_call"
    AGENT_INVOKE = "agent_invoke"
    MODEL_ROUTE = "model_route"
    CONFIG_CHANGE = "config_change"
    SECURITY = "security"
    SYSTEM = "system"
    USER_ACTION = "user_action"


# ── Audit Event ───────────────────────────────────────────────────


@dataclass
class AuditEvent:
    """A single immutable audit event.

    Attributes:
        agent: Agent name or identifier.
        action: Action description (e.g., "tool:search", "agent_start").
        target: Target of the action (e.g., tool args, task snippet).
        result: Outcome — "success", "failure", "pending", "timeout".
        severity: Event severity.
        category: Action category.
        session_id: Session identifier for grouping.
        timestamp: Unix timestamp when the event occurred.
        duration_ms: Elapsed time in milliseconds.
        error_message: Error message if result is "failure".
        details: Arbitrary structured metadata.
    """

    agent: str
    action: str
    target: str = ""
    result: str = "success"
    severity: AuditSeverity = AuditSeverity.INFO
    category: AuditActionCategory = AuditActionCategory.SYSTEM
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    error_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["category"] = self.category.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ── Audit Logger ──────────────────────────────────────────────────


class AuditLogger:
    """Immutable append-only audit logger.

    Writes audit events as JSONL (one JSON object per line) to a log file.
    Supports in-memory stat tracking and log rotation by date.

    Usage:
        audit = AuditLogger(log_dir="./audit_logs", auto_flush=True)
        audit.log(
            agent="production",
            action="tool:search",
            target="query='latest news'",
            result="success",
            severity=AuditSeverity.INFO,
            category=AuditActionCategory.TOOL_CALL,
            session_id="sess-001",
            duration_ms=45.2,
            details={"arguments": {"query": "latest news"}},
        )
        print(audit.stats_summary())
    """

    def __init__(
        self,
        log_dir: str = "",
        auto_flush: bool = True,
        max_events_in_memory: int = 10000,
    ):
        self._auto_flush = auto_flush
        self._max_memory = max_events_in_memory

        # Determine log path
        if log_dir:
            self._log_dir = Path(log_dir)
        else:
            self._log_dir = Path(os.getcwd()) / "audit_logs"

        self._log_dir.mkdir(parents=True, exist_ok=True)

        # Rotate daily
        date_str = time.strftime("%Y%m%d")
        self._log_file = self._log_dir / f"audit-{date_str}.jsonl"

        # In-memory event buffer
        self._events: list[AuditEvent] = []
        self._stats = _AuditStats()

        # Ensure log file exists
        if not self._log_file.exists():
            self._log_file.touch()

    # ── Log ────────────────────────────────────────────────────────

    def log(
        self,
        *,
        agent: str,
        action: str,
        target: str = "",
        result: str = "success",
        severity: AuditSeverity = AuditSeverity.INFO,
        category: AuditActionCategory = AuditActionCategory.SYSTEM,
        session_id: str = "",
        duration_ms: float = 0.0,
        error_message: str = "",
        details: dict[str, Any] | None = None,
    ):
        """Append an audit event to the log.

        All parameters are keyword-only for clarity at call sites.
        """
        event = AuditEvent(
            agent=agent,
            action=action,
            target=target,
            result=result,
            severity=severity,
            category=category,
            session_id=session_id,
            timestamp=time.time(),
            duration_ms=duration_ms,
            error_message=error_message,
            details=details or {},
        )

        # Write to file immediately
        self._write_event(event)

        # Track in memory (with eviction if needed)
        self._events.append(event)
        self._stats.record(event)

        # Evict oldest if over memory limit
        while len(self._events) > self._max_memory:
            self._events.pop(0)

    # ── Stats ─────────────────────────────────────────────────────

    def stats_summary(self) -> dict:
        """Return aggregate stats for all logged events."""
        return self._stats.summary()

    # ── Query ─────────────────────────────────────────────────────

    def query(
        self,
        session_id: str = "",
        category: AuditActionCategory | None = None,
        severity: AuditSeverity | None = None,
        agent: str = "",
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Query events by filters. Searches in-memory buffer first,
        then falls back to scanning the log file."""
        results = []
        seen_ids = set()

        # Search memory buffer
        for evt in reversed(self._events):
            if self._match(evt, session_id, category, severity, agent):
                eid = (evt.agent, evt.action, evt.timestamp)
                if eid not in seen_ids:
                    results.append(evt)
                    seen_ids.add(eid)
                if len(results) >= limit:
                    return results

        # If no file or already have enough, return
        if len(results) >= limit:
            return results

        # Scan log file (backwards)
        if self._log_file.exists():
            try:
                lines = self._log_file.read_text().strip().split("\n")
                for line in reversed(lines):
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                        evt = self._dict_to_event(d)
                        if self._match(evt, session_id, category, severity, agent):
                            eid = (evt.agent, evt.action, evt.timestamp)
                            if eid not in seen_ids:
                                results.append(evt)
                                seen_ids.add(eid)
                    except (json.JSONDecodeError, KeyError):
                        continue
                    if len(results) >= limit:
                        break
            except Exception:
                pass

        return results[:limit]

    # ── Export ────────────────────────────────────────────────────

    def export(self, session_id: str = "", fmt: str = "jsonl") -> str:
        """Export audit events for a session or all events."""
        events = (
            self.query(session_id=session_id, limit=999999) if session_id else list(self._events)
        )
        if fmt == "json":
            return json.dumps([e.to_dict() for e in events], indent=2, default=str)
        # jsonl
        return "\n".join(e.to_json() for e in events)

    # ── Internal ──────────────────────────────────────────────────

    def _write_event(self, event: AuditEvent):
        """Append a single JSONL line to the log file."""
        try:
            with open(self._log_file, "a") as f:
                f.write(event.to_json() + "\n")
                if self._auto_flush:
                    f.flush()
        except Exception:
            pass

    def _match(
        self,
        evt: AuditEvent,
        session_id: str,
        category: AuditActionCategory | None,
        severity: AuditSeverity | None,
        agent: str,
    ) -> bool:
        if session_id and evt.session_id != session_id:
            return False
        if category is not None and evt.category != category:
            return False
        if severity is not None and evt.severity != severity:
            return False
        if agent and evt.agent != agent:
            return False
        return True

    def _dict_to_event(self, d: dict) -> AuditEvent:
        return AuditEvent(
            agent=d.get("agent", ""),
            action=d.get("action", ""),
            target=d.get("target", ""),
            result=d.get("result", "success"),
            severity=AuditSeverity(d.get("severity", "info")),
            category=AuditActionCategory(d.get("category", "system")),
            session_id=d.get("session_id", ""),
            timestamp=d.get("timestamp", 0.0),
            duration_ms=d.get("duration_ms", 0.0),
            error_message=d.get("error_message", ""),
            details=d.get("details", {}),
        )


# ── Internal Stats Tracker ───────────────────────────────────────


class _AuditStats:
    """Tracks aggregate statistics for audit events."""

    def __init__(self):
        self.total_events = 0
        self.success_count = 0
        self.failure_count = 0
        self.total_duration_ms = 0.0
        self.by_severity: dict[str, int] = {}
        self.by_category: dict[str, int] = {}
        self.by_agent: dict[str, int] = {}
        self.first_event_ts: float = 0.0
        self.last_event_ts: float = 0.0

    def record(self, event: AuditEvent):
        self.total_events += 1
        if event.result == "success":
            self.success_count += 1
        else:
            self.failure_count += 1

        self.total_duration_ms += event.duration_ms

        sev = event.severity.value
        self.by_severity[sev] = self.by_severity.get(sev, 0) + 1

        cat = event.category.value
        self.by_category[cat] = self.by_category.get(cat, 0) + 1

        agt = event.agent
        self.by_agent[agt] = self.by_agent.get(agt, 0) + 1

        if self.first_event_ts == 0 or event.timestamp < self.first_event_ts:
            self.first_event_ts = event.timestamp
        if event.timestamp > self.last_event_ts:
            self.last_event_ts = event.timestamp

    def summary(self) -> dict:
        error_rate = self.failure_count / self.total_events if self.total_events > 0 else 0.0
        return {
            "total_events": self.total_events,
            "success": self.success_count,
            "failure": self.failure_count,
            "error_rate": round(error_rate, 4),
            "total_duration_ms": round(self.total_duration_ms, 2),
            "by_severity": dict(self.by_severity),
            "by_category": dict(self.by_category),
            "by_agent": dict(self.by_agent),
        }
