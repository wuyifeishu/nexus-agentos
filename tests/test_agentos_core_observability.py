"""Tests for agentos.core.observability — metrics, tracing, logging."""

import json
import logging
import time

from agentos.core.observability import (
    Counter,
    Gauge,
    Histogram,
    JsonFormatter,
    MetricsRegistry,
    MetricValue,
    Span,
    SpanContext,
    StandardMetrics,
    Summary,
    Tracer,
    _percentile,
    correlation_id,
    get_correlation_id,
    new_correlation_id,
    setup_structured_logging,
)

# ============================================================================
# _percentile
# ============================================================================

class TestPercentile:
    def test_empty(self):
        assert _percentile([], 50) == 0.0

    def test_single(self):
        assert _percentile([5.0], 50) == 5.0

    def test_p50(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _percentile(vals, 50) == 3.0

    def test_p90(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert _percentile(vals, 90) == 9.1

    def test_p99(self):
        vals = list(range(1, 101))
        result = _percentile(vals, 99)
        assert 98.0 < result < 100.0


# ============================================================================
# MetricValue
# ============================================================================

class TestMetricValue:
    def test_initial_zero(self):
        mv = MetricValue()
        assert mv.get() == 0.0

    def test_set(self):
        mv = MetricValue()
        mv.set(42.0)
        assert mv.get() == 42.0

    def test_add_positive(self):
        mv = MetricValue(10.0)
        mv.add(5.0)
        assert mv.get() == 15.0

    def test_add_negative(self):
        mv = MetricValue(10.0)
        mv.add(-3.0)
        assert mv.get() == 7.0

    def test_inc(self):
        mv = MetricValue()
        mv.inc()
        mv.inc()
        assert mv.get() == 2.0


# ============================================================================
# Counter
# ============================================================================

class TestCounter:
    def test_inc(self):
        c = Counter("requests", "total requests")
        c.inc()
        c.inc(4)
        assert c.value() == 5.0

    def test_name_help_labels(self):
        c = Counter("rpc_calls", "RPC call count", {"service": "auth"})
        assert c.name == "rpc_calls"
        assert c.help == "RPC call count"
        assert c.labels == {"service": "auth"}


# ============================================================================
# Gauge
# ============================================================================

class TestGauge:
    def test_set(self):
        g = Gauge("temp", "temperature")
        g.set(98.6)
        assert g.value() == 98.6

    def test_inc_dec(self):
        g = Gauge("queue_depth")
        g.inc(10)
        g.dec(3)
        assert g.value() == 7.0

    def test_negatives(self):
        g = Gauge("balance")
        g.set(-100.0)
        assert g.value() == -100.0


# ============================================================================
# Histogram
# ============================================================================

class TestHistogram:
    def test_observe_and_snapshot(self):
        h = Histogram("latency", "request latency")
        h.observe(0.1)
        h.observe(0.5)
        h.observe(1.0)
        snap = h.snapshot()
        assert snap["count"] == 3
        assert snap["min"] == 0.1
        assert snap["max"] == 1.0

    def test_custom_buckets(self):
        h = Histogram("size", buckets=[1.0, 10.0, 100.0])
        h.observe(5.0)
        assert h.snapshot()["count"] == 1


class TestSummary:
    def test_is_histogram(self):
        s = Summary("latency")
        assert isinstance(s, Histogram)
        s.observe(0.5)
        assert s.snapshot()["count"] == 1


# ============================================================================
# MetricsRegistry
# ============================================================================

class TestMetricsRegistry:
    def test_counter_reuse(self):
        mr = MetricsRegistry()
        c1 = mr.counter("hits")
        c2 = mr.counter("hits")
        assert c1 is c2

    def test_gauge_reuse(self):
        mr = MetricsRegistry()
        g1 = mr.gauge("cpu")
        g2 = mr.gauge("cpu")
        assert g1 is g2

    def test_get_missing(self):
        mr = MetricsRegistry()
        assert mr.get("nonexistent") is None

    def test_export_dict(self):
        mr = MetricsRegistry()
        mr.counter("req").inc(3)
        mr.gauge("mem").set(1024)
        d = mr.export_dict()
        assert d["req"] == 3.0
        assert d["mem"] == 1024.0

    def test_export_prometheus_counter(self):
        mr = MetricsRegistry()
        mr.counter("http_requests_total", "Total HTTP requests").inc(5)
        out = mr.export_prometheus()
        assert "# HELP http_requests_total Total HTTP requests" in out
        assert "http_requests_total 5.0" in out

    def test_export_prometheus_gauge(self):
        mr = MetricsRegistry()
        mr.gauge("memory_bytes", "Memory usage").set(2048)
        out = mr.export_prometheus()
        assert "# TYPE memory_bytes gauge" in out
        assert "memory_bytes" in out and "2048" in out

    def test_export_prometheus_histogram(self):
        mr = MetricsRegistry()
        h = mr.histogram("query_duration", "Query duration", buckets=[0.1, 0.5, 1.0])
        h.observe(0.3)
        out = mr.export_prometheus()
        assert "query_duration_count" in out
        assert "query_duration_sum" in out

    def test_labels_in_prometheus(self):
        mr = MetricsRegistry()
        mr.counter("errors", labels={"code": "500"}).inc(1)
        out = mr.export_prometheus()
        assert 'code="500"' in out


# ============================================================================
# Span / SpanContext
# ============================================================================

class TestSpanContext:
    def test_defaults(self):
        ctx = SpanContext()
        assert len(ctx.trace_id) == 16
        assert len(ctx.span_id) == 12
        assert ctx.parent_span_id is None


class TestSpan:
    def test_basic(self):
        s = Span("http_request")
        assert s.name == "http_request"
        assert s.context.trace_id
        assert s.duration_ms >= 0

    def test_finish(self):
        s = Span("task")
        s.finish()
        assert s.end_time is not None

    def test_tags_and_events(self):
        s = Span("query")
        s.set_tag("db", "postgres")
        s.add_event("cache_miss", key="user:123")
        d = s.to_dict()
        assert d["tags"] == {"db": "postgres"}
        assert len(d["events"]) == 1
        assert d["events"][0]["name"] == "cache_miss"

    def test_parent_child(self):
        parent = Span("parent")
        child = Span("child", parent=parent)
        assert child.context.parent_span_id == parent.context.span_id
        assert child.context.trace_id == parent.context.trace_id

    def test_duration(self):
        s = Span("timer")
        time.sleep(0.01)
        s.finish()
        assert s.duration_ms >= 10


# ============================================================================
# Tracer
# ============================================================================

class TestTracer:
    def test_start_end_span(self):
        t = Tracer()
        span = t.start_span("op")
        assert t.active_span is span
        t.end_span(span)
        assert span.end_time is not None

    def test_no_active_span(self):
        t = Tracer()
        assert t.active_span is None

    def test_span_context_no_span(self):
        t = Tracer()
        ctx = t.span_context()
        assert isinstance(ctx, SpanContext)

    def test_span_context_with_span(self):
        t = Tracer()
        span = t.start_span("work")
        ctx = t.span_context()
        assert ctx.span_id == span.context.span_id
        t.end_span(span)

    def test_noop(self):
        t = Tracer.noop()
        assert isinstance(t, Tracer)


# ============================================================================
# Correlation ID
# ============================================================================

class TestCorrelationID:
    def test_new_correlation_id(self):
        cid = new_correlation_id()
        assert len(cid) == 12
        assert get_correlation_id() == cid

    def test_default_empty(self):
        correlation_id.set("")
        assert get_correlation_id() == ""


# ============================================================================
# JsonFormatter
# ============================================================================

class TestJsonFormatter:
    def test_basic_format(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        record.created = 1000000.0
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert data["message"] == "hello world"

    def test_with_correlation_id(self):
        correlation_id.set("abc123")
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="app", level=logging.WARNING, pathname="", lineno=0,
            msg="warning!", args=(), exc_info=None,
        )
        record.created = 1000000.0
        data = json.loads(fmt.format(record))
        assert data["correlation_id"] == "abc123"

    def test_with_exception(self):
        fmt = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="err", level=logging.ERROR, pathname="", lineno=0,
                msg="fail", args=(), exc_info=sys.exc_info(),
            )
            record.created = 1000000.0
            data = json.loads(fmt.format(record))
            assert "exception" in data
            assert "ValueError" in data["exception"]


# ============================================================================
# StandardMetrics
# ============================================================================

class TestStandardMetrics:
    def test_creates_all_metrics(self):
        mr = MetricsRegistry()
        sm = StandardMetrics(mr, prefix="test")
        assert sm.request_count.name == "test_requests_total"
        assert sm.request_duration.name == "test_request_duration_seconds"
        assert sm.request_errors.name == "test_request_errors_total"
        assert sm.active_agents.name == "test_active_agents"
        assert sm.agent_invocations.name == "test_agent_invocations_total"
        assert sm.memory_bytes.name == "test_memory_bytes"

    def test_counter_usage(self):
        mr = MetricsRegistry()
        sm = StandardMetrics(mr)
        sm.request_count.inc()
        assert sm.request_count.value() == 1.0
        sm.agent_invocations.inc(5)
        assert sm.agent_invocations.value() == 5.0

    def test_gauge_usage(self):
        mr = MetricsRegistry()
        sm = StandardMetrics(mr)
        sm.active_agents.set(3)
        sm.memory_bytes.set(1024 * 1024)
        assert sm.active_agents.value() == 3.0


# ============================================================================
# setup_structured_logging
# ============================================================================

class TestSetupStructuredLogging:
    def test_sets_handler(self):
        root = logging.getLogger()
        initial_handlers = len(root.handlers)
        setup_structured_logging(logging.WARNING)
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
        # Restore
        root.handlers.clear()
