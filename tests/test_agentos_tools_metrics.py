"""Tests for agentos.tools.metrics — Counter, Gauge, Histogram, Timer, MetricsCollector."""

import time

from agentos.tools.metrics import (
    DEFAULT_BUCKETS,
    Counter,
    Gauge,
    Histogram,
    MetricsCollector,
    Timer,
    get_metrics_collector,
)


class TestCounter:
    def test_initial_zero(self):
        c = Counter("test")
        assert c.get() == 0.0

    def test_inc(self):
        c = Counter("test")
        c.inc()
        assert c.get() == 1.0
        c.inc(4.5)
        assert c.get() == 5.5

    def test_name_help_labels(self):
        c = Counter("http_requests", "Total HTTP requests", {"method": "GET"})
        assert c.name == "http_requests"
        assert c.help == "Total HTTP requests"
        assert c.labels == {"method": "GET"}

    def test_format_labels(self):
        c = Counter("x", labels={"a": "1", "b": "2"})
        fmt = c._format_labels()
        assert "a=" in fmt
        assert "b=" in fmt
        assert fmt.startswith("{")
        assert fmt.endswith("}")

        c2 = Counter("y")
        assert c2._format_labels() == ""


class TestGauge:
    def test_set_get(self):
        g = Gauge("test")
        g.set(3.14)
        assert g.get() == 3.14

    def test_inc_dec(self):
        g = Gauge("test")
        g.inc(10)
        g.dec(3)
        assert g.get() == 7.0

    def test_default_zero(self):
        assert Gauge("test").get() == 0.0


class TestHistogram:
    def test_observe_updates_count(self):
        h = Histogram("latency")
        h.observe(0.5)
        h.observe(1.5)
        data = h.get()
        assert data["count"] == 2

    def test_bucketing(self):
        h = Histogram("latency", buckets=(1.0, 5.0, 10.0))
        h.observe(0.5)
        h.observe(7.0)
        h.observe(20.0)
        data = h.get()
        # Each observation goes to exactly one bucket (first matching, non-cumulative)
        assert data["buckets"][1.0] == 1  # 0.5 fits here
        assert data["buckets"][5.0] == 0  # nothing in (1.0, 5.0]
        assert data["buckets"][10.0] == 1  # 7.0 fits here
        assert data["buckets"]["+Inf"] == 1  # 20.0 overflows

    def test_p50(self):
        h = Histogram("latency", buckets=(0.1, 1.0, 10.0))
        for _ in range(5):
            h.observe(0.05)
        for _ in range(5):
            h.observe(5.0)
        assert h.p50() <= 1.0  # median falls in 0-1 bucket

    def test_p90(self):
        h = Histogram("latency", buckets=(0.1, 1.0, 10.0))
        for _ in range(9):
            h.observe(0.05)
        h.observe(5.0)
        assert h.p90() <= 10.0

    def test_p99(self):
        h = Histogram("latency", buckets=(0.1, 1.0, 10.0))
        for _ in range(99):
            h.observe(0.05)
        h.observe(5.0)
        assert h.p99() <= 10.0

    def test_percentile_empty(self):
        h = Histogram("empty")
        assert h.p50() == 0.0
        assert h.p90() == 0.0
        assert h.p99() == 0.0

    def test_default_buckets(self):
        h = Histogram("x")
        assert h.buckets == DEFAULT_BUCKETS


class TestTimer:
    def test_context_manager(self):
        t = Timer("op")
        with t:
            time.sleep(0.01)
        data = t.get()
        assert data["histogram"]["count"] == 1
        assert data["count"] > 0

    def test_time_method(self):
        t = Timer("op")
        result = t.time(lambda: 42)
        assert result == 42
        assert t.get()["histogram"]["count"] == 1

    def test_time_method_args(self):
        t = Timer("op")
        result = t.time(lambda x, y: x + y, 10, 20)
        assert result == 30


class TestMetricsCollector:
    def test_counter_singleton(self):
        mc = MetricsCollector()
        c1 = mc.counter("req")
        c2 = mc.counter("req")
        assert c1 is c2

    def test_get_counter_by_name(self):
        mc = MetricsCollector()
        mc.counter("hits", "Total hits")
        c = mc.get("hits")
        assert isinstance(c, Counter)
        assert c.get() == 0.0

    def test_gauge_singleton(self):
        mc = MetricsCollector()
        g1 = mc.gauge("temp")
        g2 = mc.gauge("temp")
        assert g1 is g2

    def test_histogram_singleton(self):
        mc = MetricsCollector()
        h1 = mc.histogram("latency", buckets=DEFAULT_BUCKETS)
        h2 = mc.histogram("latency")
        assert h1 is h2

    def test_timer_singleton(self):
        mc = MetricsCollector()
        t1 = mc.timer("req_time")
        t2 = mc.timer("req_time")
        assert t1 is t2

    def test_namespace(self):
        mc = MetricsCollector(namespace="app")
        mc.counter("hits")
        assert mc.get("hits") is not None
        assert mc.get("app_hits") is None  # get() applies namespace again

    def test_list_metrics(self):
        mc = MetricsCollector()
        mc.counter("a")
        mc.gauge("b")
        assert set(mc.list_metrics()) == {"a", "b"}

    def test_get_nonexistent(self):
        mc = MetricsCollector()
        assert mc.get("ghost") is None

    def test_get_all(self):
        mc = MetricsCollector()
        mc.counter("c", "help").inc(5)
        mc.gauge("g", "help").set(3.0)
        all_data = mc.get_all()
        assert all_data["c"] == 5.0
        assert all_data["g"] == 3.0

    def test_to_prometheus_counter(self):
        mc = MetricsCollector()
        mc.counter("hits", "hit count").inc(42)
        txt = mc.to_prometheus()
        assert "# HELP hits hit count" in txt
        assert "# TYPE hits counter" in txt
        assert "hits 42.0" in txt

    def test_to_prometheus_gauge(self):
        mc = MetricsCollector()
        mc.gauge("temp", "temperature").set(98.6)
        txt = mc.to_prometheus()
        assert "# TYPE temp gauge" in txt
        assert "temp 98.6" in txt

    def test_to_prometheus_histogram(self):
        mc = MetricsCollector()
        h = mc.histogram("latency", "request latency", buckets=(1.0, 5.0))
        h.observe(3.0)
        txt = mc.to_prometheus()
        assert "# TYPE latency histogram" in txt
        assert "latency_count" in txt
        assert "latency_sum" in txt
        assert "latency_bucket" in txt
        assert 'le="1.0"' in txt

    def test_to_prometheus_timer(self):
        mc = MetricsCollector()
        t = mc.timer("op_latency", "operation latency", buckets=(0.1, 1.0))
        with t:
            time.sleep(0.01)
        txt = mc.to_prometheus()
        assert "# TYPE op_latency histogram" in txt
        assert "op_latency_count" in txt
        assert "op_latency_bucket" in txt

    def test_to_prometheus_with_labels(self):
        mc = MetricsCollector()
        mc.counter("req", "requests", {"method": "POST"}).inc(7)
        txt = mc.to_prometheus()
        assert 'method="POST"' in txt

    def test_to_prometheus_empty(self):
        mc = MetricsCollector()
        assert mc.to_prometheus() == "\n"


class TestSingleton:
    def test_get_metrics_collector(self):
        mc = get_metrics_collector("test_ns")
        assert isinstance(mc, MetricsCollector)
        assert mc.namespace == "test_ns"
