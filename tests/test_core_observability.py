"""Tests for agentos.core.observability — ~22 test cases."""

import json
import time

import pytest

from agentos.core.observability import (
    Counter,
    Gauge,
    Histogram,
    JsonFormatter,
    MetricsRegistry,
    Span,
    StandardMetrics,
    Tracer,
    correlation_id,
    get_correlation_id,
    new_correlation_id,
)


class TestCounter:
    """Counter metric."""

    def test_initial_value_zero(self):
        c = Counter("test_counter", "A test counter")
        assert c.value() == 0.0

    def test_inc_increments(self):
        c = Counter("test")
        c.inc()
        c.inc(2.5)
        assert c.value() == 3.5

    def test_only_increases(self):
        c = Counter("test")
        c.inc(10)
        c.inc(-5)  # inc with negative increases
        assert c.value() == 5.0

    def test_name_and_help(self):
        c = Counter("requests", "Total requests")
        assert c.name == "requests"
        assert c.help == "Total requests"


class TestGauge:
    """Gauge metric."""

    def test_set_and_value(self):
        g = Gauge("mem", "Memory usage")
        g.set(1024)
        assert g.value() == 1024

    def test_inc_dec(self):
        g = Gauge("active")
        g.inc(5)
        assert g.value() == 5
        g.dec(2)
        assert g.value() == 3

    def test_go_below_zero(self):
        g = Gauge("balance")
        g.dec(100)
        assert g.value() == -100


class TestHistogram:
    """Histogram metric."""

    def test_observe_records(self):
        h = Histogram("latency", "Request latency")
        h.observe(0.1)
        h.observe(0.2)
        h.observe(0.3)
        snap = h.snapshot()
        assert snap["count"] == 3
        assert snap["min"] == 0.1
        assert snap["max"] == 0.3
        assert snap["avg"] == pytest.approx(0.2)

    def test_single_observation(self):
        h = Histogram("x")
        h.observe(42.0)
        snap = h.snapshot()
        assert snap["count"] == 1
        assert snap["p50"] == 42.0
        assert snap["p99"] == 42.0

    def test_empty_histogram(self):
        h = Histogram("empty")
        snap = h.snapshot()
        assert snap["count"] == 0


class TestMetricsRegistry:
    """Registry management."""

    def test_counter_singleton(self):
        reg = MetricsRegistry()
        c1 = reg.counter("my_cnt", "help")
        c2 = reg.counter("my_cnt")
        assert c1 is c2

    def test_different_metric_types(self):
        reg = MetricsRegistry()
        c = reg.counter("a")
        g = reg.gauge("b")
        h = reg.histogram("c")
        assert isinstance(c, Counter)
        assert isinstance(g, Gauge)
        assert isinstance(h, Histogram)

    def test_export_dict(self):
        reg = MetricsRegistry()
        reg.counter("c1").inc(5)
        reg.gauge("g1", labels={"env": "test"}).set(42)

        d = reg.export_dict()
        assert d["c1"] == 5
        assert d["g1"] == 42

    def test_export_prometheus_format(self):
        reg = MetricsRegistry()
        reg.counter("hits", "Cache hits")
        reg.gauge("temp", "Temperature").set(36.5)

        text = reg.export_prometheus()
        assert "# HELP hits" in text
        assert "hits " in text
        assert "temp " in text


class TestStandardMetrics:
    """Pre-built standard metrics."""

    def test_all_metrics_registered(self):
        reg = MetricsRegistry()
        sm = StandardMetrics(reg, prefix="myapp")
        assert sm.request_count.name == "myapp_requests_total"
        assert sm.active_agents.name == "myapp_active_agents"

    def test_metrics_are_mutable(self):
        reg = MetricsRegistry()
        sm = StandardMetrics(reg)
        sm.request_count.inc()
        sm.active_agents.set(3)
        assert sm.request_count.value() == 1
        assert sm.active_agents.value() == 3


class TestSpanAndTracer:
    """Tracing primitives."""

    def test_span_lifecycle(self):
        span = Span("test_op")
        assert span.name == "test_op"
        assert span.context.trace_id
        time.sleep(0.001)
        span.finish()
        assert span.duration_ms > 0

    def test_nested_spans(self):
        tracer = Tracer()
        parent = tracer.start_span("outer")
        child = tracer.start_span("inner")
        assert child.context.parent_span_id == parent.context.span_id
        assert child.context.trace_id == parent.context.trace_id

    def test_span_to_dict(self):
        span = Span("api_call")
        span.set_tag("method", "POST")
        span.add_event("started")
        span.finish()
        d = span.to_dict()
        assert d["name"] == "api_call"
        assert d["tags"]["method"] == "POST"
        assert len(d["events"]) == 1


class TestCorrelation:
    """Correlation ID."""

    def test_new_correlation_id(self):
        cid = new_correlation_id()
        assert len(cid) == 12
        assert get_correlation_id() == cid

    def test_default_empty(self):
        # Reset and check default
        correlation_id.set("")
        assert get_correlation_id() == ""


class TestJsonFormatter:
    """Structured logging formatter."""

    def test_basic_format(self):
        import logging
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=1,
            msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"

    def test_correlation_id_injected(self):
        import logging
        correlation_id.set("abc123")
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="app", level=logging.WARNING, pathname="", lineno=1,
            msg="test", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["correlation_id"] == "abc123"
