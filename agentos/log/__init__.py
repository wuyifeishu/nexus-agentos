"""Structured logging with JSON formatter and trace context."""

from .formatter import (
    JSONFormatter,
    TraceContext,
    _ExtraAdapter,
    audit_log,
    get_logger,
    setup_structured_logging,
)

__all__ = [
    "JSONFormatter",
    "TraceContext",
    "_ExtraAdapter",
    "audit_log",
    "get_logger",
    "setup_structured_logging",
]
