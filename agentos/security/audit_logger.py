"""AuditLogger — immutable, SHA256-chained audit trail."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AuditSeverity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditActionCategory(str, Enum):
    TOOL_CALL = "tool_call"
    AGENT_INVOKE = "agent_invoke"
    CONFIG_CHANGE = "config_change"
    SYSTEM = "system"
    SECURITY = "security"


@dataclass
class AuditEntry:
    timestamp: float
    agent: str
    action: str
    target: str
    result: str
    severity: AuditSeverity
    category: AuditActionCategory
    session_id: str
    duration_ms: float = 0.0
    error_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    chain_hash: str = ""


class AuditLogger:
    """Immutable audit trail with SHA256 chaining.

    Every log entry is chained via SHA256, creating a tamper-evident trail.
    """

    def __init__(self, log_dir: str = "") -> None:
        self._log_dir = log_dir or os.getcwd()
        self._entries: list[AuditEntry] = []
        self._last_hash: str = ""

    def log(
        self,
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
    ) -> AuditEntry:
        """Log an audit entry and return it."""
        entry = AuditEntry(
            timestamp=time.time(),
            agent=agent,
            action=action,
            target=target,
            result=result,
            severity=severity,
            category=category,
            session_id=session_id,
            duration_ms=duration_ms,
            error_message=error_message,
            details=details or {},
        )

        # chain via SHA256
        raw = json.dumps(
            {
                "timestamp": entry.timestamp,
                "agent": entry.agent,
                "action": entry.action,
                "target": entry.target,
                "result": entry.result,
                "severity": entry.severity.value,
                "category": entry.category.value,
                "session_id": entry.session_id,
                "duration_ms": entry.duration_ms,
                "error_message": entry.error_message,
                "details": entry.details,
                "prev_hash": self._last_hash,
            },
            sort_keys=True,
            default=str,
        )
        entry.chain_hash = hashlib.sha256(raw.encode()).hexdigest()
        self._last_hash = entry.chain_hash
        self._entries.append(entry)

        # write to file
        log_path = os.path.join(self._log_dir, "audit.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(self._entry_to_dict(entry), default=str) + "\n")

        return entry

    def stats_summary(self) -> dict[str, Any]:
        """Return statistics about recorded events."""
        if not self._entries:
            return {"events": 0}
        return {
            "events": len(self._entries),
            "last_chain_hash": self._last_hash,
        }

    @staticmethod
    def _entry_to_dict(entry: AuditEntry) -> dict[str, Any]:
        return {
            "timestamp": entry.timestamp,
            "agent": entry.agent,
            "action": entry.action,
            "target": entry.target,
            "result": entry.result,
            "severity": entry.severity.value,
            "category": entry.category.value,
            "session_id": entry.session_id,
            "duration_ms": entry.duration_ms,
            "error_message": entry.error_message,
            "details": entry.details,
            "chain_hash": entry.chain_hash,
        }
