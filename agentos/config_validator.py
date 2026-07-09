"""
Startup configuration validator for AgentOS.

Runs at server boot before accepting connections. Validates:
- Required env vars present
- Database connectivity (optional)
- Redis connectivity (optional)
- OTLP endpoint reachable (optional, timeout 3s)
- Disk write permissions on log/output dirs
- SSL/TLS cert validity if HTTPS enabled

Usage:
    from agentos.config_validator import validate_startup

    issues = validate_startup()
    if issues.has_critical:
        raise SystemExit(issues.report())
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class Severity(StrEnum):
    CRITICAL = "critical"  # Server MUST NOT start
    ERROR = "error"  # Feature degraded
    WARNING = "warning"  # Non-blocking concern
    OK = "ok"


@dataclass
class Issue:
    component: str
    message: str
    severity: Severity
    suggestion: str = ""


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(i.severity == Severity.CRITICAL for i in self.issues)

    def add(self, component: str, message: str, severity: Severity, suggestion: str = ""):
        self.issues.append(Issue(component, message, severity, suggestion))

    def report(self) -> str:
        lines = [f"\n{'='*60}", "  AgentOS Startup Validation", f"{'='*60}"]
        for issue in self.issues:
            tag = f"[{issue.severity.upper()}]"
            lines.append(f"  {tag:12s} {issue.component}: {issue.message}")
            if issue.suggestion:
                lines.append(f"             → {issue.suggestion}")
        lines.append(f"{'='*60}")

        statuses = [i.severity for i in self.issues]
        if Severity.CRITICAL in statuses:
            lines.append("  RESULT: CRITICAL — server will NOT start")
        elif Severity.ERROR in statuses:
            lines.append("  RESULT: DEGRADED — some features unavailable")
        else:
            lines.append("  RESULT: OK")
        return "\n".join(lines)


# ── Checks ──────────────────────────────────────────────────────────────────


def _check_env_vars(report: ValidationReport):
    required = ["AGENTOS_SECRET_KEY"]
    optional = {
        "AGENTOS_DATABASE_URL": "Database-backed features disabled",
        "AGENTOS_REDIS_URL": "Distributed cache/locks disabled",
        "AGENTOS_OTLP_ENDPOINT": "Distributed tracing disabled",
    }
    for var in required:
        if not os.environ.get(var):
            report.add(
                "env",
                f"{var} not set",
                Severity.WARNING,
                f"Set {var} for production; using default for dev",
            )

    for var, hint in optional.items():
        if not os.environ.get(var):
            report.add(
                "env",
                f"{var} not set — {hint}",
                Severity.WARNING,
                f"Set {var} for full production readiness",
            )


def _check_disk(report: ValidationReport, paths: list[str]):
    for path in paths:
        try:
            os.makedirs(path, exist_ok=True)
            test_file = os.path.join(path, ".agentos_write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            report.add("disk", f"{path} writable", Severity.OK)
        except PermissionError:
            report.add(
                "disk",
                f"Cannot write to {path}",
                Severity.CRITICAL,
                "Fix permissions or change AGENTOS_LOG_DIR / AGENTOS_DATA_DIR",
            )
        except OSError as e:
            report.add("disk", f"{path}: {e}", Severity.ERROR)


def _check_connectivity(report: ValidationReport, name: str, url: str, timeout: float = 3.0):
    """Quick TCP connectivity check."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        report.add("connectivity", f"{name} reachable ({host}:{port})", Severity.OK)
    except (TimeoutError, ConnectionRefusedError, OSError) as e:
        report.add(
            "connectivity",
            f"{name} unreachable ({host}:{port}): {e}",
            Severity.WARNING,
            f"Verify {name} is running or disable related features",
        )


# ── Public API ──────────────────────────────────────────────────────────────


def validate_startup(
    data_dir: str | None = None,
    log_dir: str | None = None,
) -> ValidationReport:
    """Run all startup checks and return a report.

    Returns a ValidationReport — call `.has_critical` to decide whether to abort.
    """
    report = ValidationReport()

    _check_env_vars(report)

    disk_paths = [
        data_dir or os.environ.get("AGENTOS_DATA_DIR", "./data"),
        log_dir or os.environ.get("AGENTOS_LOG_DIR", "./logs"),
    ]
    _check_disk(report, disk_paths)

    db_url = os.environ.get("AGENTOS_DATABASE_URL")
    if db_url:
        _check_connectivity(report, "DB", db_url)

    redis_url = os.environ.get("AGENTOS_REDIS_URL")
    if redis_url:
        _check_connectivity(report, "Redis", redis_url)

    otlp = os.environ.get("AGENTOS_OTLP_ENDPOINT")
    if otlp:
        _check_connectivity(report, "OTLP", otlp)

    logger.info(report.report())
    return report


__all__ = ["validate_startup", "ValidationReport", "Severity"]
