"""
OpenTelemetry distributed tracing for AgentOS.

Minimal setup — wraps standard OpenTelemetry SDK to trace:
- HTTP requests (inbound via FastAPI middleware, outbound via httpx instrumentor)
- Agent pipeline phases (PRE_LLM, POST_LLM, PRE_TOOL, POST_TOOL, PRE_EXEC, POST_EXEC)
- Database queries (SQLAlchemy instrumentor)

Usage:
    from agentos.observability.tracing import setup_tracing, get_tracer

    setup_tracing(service_name="agentos", otlp_endpoint="http://localhost:4317")
    tracer = get_tracer(__name__)

    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("agent.id", "agent-1")
        # ... do work ...

With env vars:
    AGENTOS_OTLP_ENDPOINT=http://jaeger:4317
    AGENTOS_TRACE_ENABLED=true
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

_tracer_provider: Any = None
_TRACE_ENABLED: bool = os.environ.get("AGENTOS_TRACE_ENABLED", "").lower() == "true"

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    logger.debug("opentelemetry not installed — tracing disabled")


def setup_tracing(
    service_name: str = "agentos",
    otlp_endpoint: str | None = None,
    sample_rate: float = 1.0,
) -> None:
    """Initialize OpenTelemetry tracing.

    Args:
        service_name: Logical service name for spans.
        otlp_endpoint: OTLP gRPC collector endpoint (default: AGENTOS_OTLP_ENDPOINT env).
        sample_rate: Trace sampling rate (1.0 = all).
    """
    global _tracer_provider, _TRACE_ENABLED

    if not _OTEL_AVAILABLE:
        logger.warning("OpenTelemetry SDK not available — tracing disabled")
        return

    endpoint = otlp_endpoint or os.environ.get("AGENTOS_OTLP_ENDPOINT", "")
    if not endpoint:
        logger.debug("No OTLP endpoint configured — tracing disabled")
        return

    resource = Resource(
        attributes={
            SERVICE_NAME: service_name,
            "deployment.environment": os.environ.get("AGENTOS_ENV", "production"),
        }
    )

    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    processor = BatchSpanProcessor(exporter)

    _tracer_provider = TracerProvider(resource=resource)
    _tracer_provider.add_span_processor(processor)
    trace.set_tracer_provider(_tracer_provider)

    _TRACE_ENABLED = True
    logger.info(f"Tracing enabled → {endpoint}")


def shutdown_tracing() -> None:
    """Flush and shutdown the tracer provider."""
    if _tracer_provider:
        _tracer_provider.shutdown()


def get_tracer(name: str = "agentos") -> Any:
    """Get a tracer instance (falls back to no-op if OTel not configured)."""
    if _OTEL_AVAILABLE and _TRACE_ENABLED:
        return trace.get_tracer(name)
    # No-op fallback
    return _NoOpTracer()


class _NoOpTracer:
    """Drop-in replacement when tracing is disabled."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        yield _NoOpSpan()

    def start_span(self, name: str, **kwargs):
        return _NoOpSpan()


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict = None) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def trace_function(name: str | None = None, attributes: dict = None):
    """Decorator to trace a function as a span."""

    def decorator(fn: Callable):
        span_name = name or f"{fn.__module__}.{fn.__qualname__}"

        @wraps(fn)
        def wrapper(*args, **kwargs):
            tracer = get_tracer(fn.__module__)
            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def get_current_span() -> Any:
    """Get the current active span (no-op safe)."""
    if _OTEL_AVAILABLE and _TRACE_ENABLED:
        return trace.get_current_span()
    return _NoOpSpan()


__all__ = [
    "setup_tracing",
    "shutdown_tracing",
    "get_tracer",
    "trace_function",
    "get_current_span",
]
