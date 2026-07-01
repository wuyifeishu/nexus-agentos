"""AgentOS logging — structured JSON formatter with trace context."""

from __future__ import annotations

import importlib
import json

_stdlib_logging = importlib.import_module("logging")
import os
import sys
import time
import uuid
from typing import IO, Optional


# ── Trace context ─────────────────────────────────────────────────────────────


class TraceContext:
    """Carries trace_id and span_id through a request lifecycle."""

    def __init__(self, trace_id: Optional[str] = None, span_id: Optional[str] = None):
        self.trace_id = trace_id or uuid.uuid4().hex[:16]
        self.span_id = span_id or uuid.uuid4().hex[:8]


# ── JSON Formatter ────────────────────────────────────────────────────────────


class JSONFormatter(_stdlib_logging.Formatter):
    """Emits log records as JSON with trace context fields."""

    def __init__(self, fmt=None, datefmt=None, style="%", trace_ctx: Optional[TraceContext] = None):
        super().__init__(fmt, datefmt, style)
        self.trace_ctx = trace_ctx or TraceContext()

    def format(self, record: _stdlib_logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt or "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "pid": os.getpid(),
            "trace_id": self.trace_ctx.trace_id,
            "span_id": self.trace_ctx.span_id,
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exc_info"] = self.formatException(record.exc_info)
        extras = getattr(record, "_structured_extra", None)
        if extras and isinstance(extras, dict):
            log_entry.update(extras)
        return json.dumps(log_entry, default=str, ensure_ascii=False)


class _ExtraAdapter(_stdlib_logging.LoggerAdapter):
    """Logging adapter that merges extra dict into the JSON output."""

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        extra["_structured_extra"] = kwargs.pop("structured_extra", {})
        kwargs["extra"] = extra
        return msg, kwargs


# ── Audit log ─────────────────────────────────────────────────────────────────


def audit_log(logger: _stdlib_logging.Logger, action: str, user_id: str, result: str, details: Optional[dict] = None):
    """Emit a structured audit log entry."""
    extra = {
        "category": "AUDIT",
        "action": action,
        "user_id": user_id,
        "result": result,
        "details": details or {},
    }
    logger.info(f"AUDIT {action} by {user_id}: {result}", extra={"structured_extra": extra})


# ── Convenience helpers ──────────────────────────────────────────────────────


def setup_structured_logging(
    name: str,
    level: int = _stdlib_logging.INFO,
    stream: Optional[IO] = None,
    trace_ctx: Optional[TraceContext] = None,
) -> _stdlib_logging.Logger:
    """Create a logger with JSONFormatter attached.

    Args:
        name: Logger name.
        level: Logging level (default INFO).
        stream: Output stream (default stderr).
        trace_ctx: Optional TraceContext for correlation.

    Returns:
        Configured logger instance.
    """
    logger = _stdlib_logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if not any(isinstance(h, _stdlib_logging.StreamHandler) and isinstance(h.formatter, JSONFormatter) for h in logger.handlers):
        handler = _stdlib_logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(JSONFormatter(trace_ctx=trace_ctx or TraceContext()))
        logger.addHandler(handler)
    return logger


def get_logger(name: str) -> _stdlib_logging.Logger:
    """Get or create a logger."""
    return _stdlib_logging.getLogger(name)
