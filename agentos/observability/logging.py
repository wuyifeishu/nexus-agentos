"""
AgentOS Structured Logging — JSON-formatted production logging with context propagation.

Provides:
- JsonFormatter: Emits JSON lines with standard fields (timestamp, level, logger, etc.)
- ContextLogger: Logger wrapper that injects request_id, tenant_id, session_id into every log.
- configure_logging(): One-call setup for production logging.

Usage:
    from agentos.observability.logging import configure_logging, get_logger

    configure_logging(level="INFO", log_file="/app/logs/agentos.log")
    logger = get_logger(__name__)
    logger.info("Agent started", extra={"agent_id": "abc123"})
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# ── Context propagation ──────────────────────────────────────────────────

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")
_session_id: ContextVar[str] = ContextVar("session_id", default="")

STANDARD_FIELDS = {
    "timestamp",
    "level",
    "logger",
    "module",
    "function",
    "line",
    "message",
    "request_id",
    "tenant_id",
    "session_id",
    "pid",
}

_INTERNAL_RECORD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "funcName",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "extra",
}


class JsonFormatter(logging.Formatter):
    """JSON Lines formatter for structured logging.

    Output fields:
        timestamp, level, logger, module, function, line, message,
        request_id, tenant_id, session_id, pid, + any extra fields.
    """

    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
            "request_id": _request_id.get(""),
            "tenant_id": _tenant_id.get(""),
            "session_id": _session_id.get(""),
            "pid": os.getpid(),
        }

        # Exception info (only if it's a real sys.exc_info() tuple, not a bool)
        if record.exc_info and record.exc_info is not True and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        # Stack trace
        if record.stack_info:
            log_entry["stack"] = record.stack_info

        # Extra fields from record.__dict__ (filter out internal log record fields)
        if self.include_extra:
            for key, value in record.__dict__.items():
                if key not in _INTERNAL_RECORD_FIELDS and not key.startswith("_"):
                    try:
                        json.dumps({key: value})  # ensure serializable
                        log_entry[key] = value
                    except (TypeError, ValueError):
                        log_entry[key] = str(value)

        return json.dumps(log_entry, default=str, ensure_ascii=False)


class ContextLogger:
    """Logger wrapper that automatically injects context into extra fields.

    Usage:
        logger = ContextLogger(logging.getLogger(__name__))
        logger.info("Processing task", task_id="t-42")
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _make_extra(self, extra: dict | None = None) -> dict:
        base = {
            "request_id": _request_id.get(""),
            "tenant_id": _tenant_id.get(""),
            "session_id": _session_id.get(""),
        }
        if extra:
            base.update(extra)
        return base

    def debug(self, msg: str, **extra):
        self._logger.debug(msg, extra=self._make_extra(extra))

    def info(self, msg: str, **extra):
        self._logger.info(msg, extra=self._make_extra(extra))

    def warning(self, msg: str, **extra):
        self._logger.warning(msg, extra=self._make_extra(extra))

    def error(self, msg: str, **extra):
        self._logger.error(msg, extra=self._make_extra(extra))

    def critical(self, msg: str, **extra):
        self._logger.critical(msg, extra=self._make_extra(extra))

    def exception(self, msg: str, **extra):
        self._logger.exception(msg, extra=self._make_extra(extra))

    @property
    def raw(self) -> logging.Logger:
        return self._logger


# ── Context management ────────────────────────────────────────────────────


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


def set_tenant_id(tid: str) -> None:
    _tenant_id.set(tid)


def set_session_id(sid: str) -> None:
    _session_id.set(sid)


def get_request_id() -> str:
    return _request_id.get("")


def get_tenant_id() -> str:
    return _tenant_id.get("")


def get_session_id() -> str:
    return _session_id.get("")


# ── Configuration ─────────────────────────────────────────────────────────


def configure_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_format: bool = True,
    include_extra: bool = True,
    root_logger_name: str = "agentos",
) -> None:
    """Configure structured logging for the entire application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Optional file path for log output. stdout if None.
        json_format: Use JSON formatter. If False, use standard format.
        include_extra: Include extra fields in JSON output.
        root_logger_name: Root logger to configure.
    """
    root = logging.getLogger(root_logger_name)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    root.handlers.clear()

    # Create handler
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stdout)

    # Set formatter
    if json_format:
        handler.setFormatter(JsonFormatter(include_extra=include_extra))
    else:
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(levelname)s %(name)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root.addHandler(handler)

    # Also configure uvicorn access log
    uvicorn_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger.handlers.clear()
    uvicorn_logger.addHandler(handler)
    uvicorn_logger.propagate = False


def get_logger(name: str) -> ContextLogger:
    """Get a structured context logger."""
    return ContextLogger(logging.getLogger(name))


__all__ = [
    "JsonFormatter",
    "ContextLogger",
    "configure_logging",
    "get_logger",
    "set_request_id",
    "set_tenant_id",
    "set_session_id",
    "get_request_id",
    "get_tenant_id",
    "get_session_id",
]
