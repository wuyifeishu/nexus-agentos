"""Tests for agentos.tools.metrics."""

import time

from agentos.tools.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsCollector,
    Timer,
    get_metrics_collector,
)


class TestCounter:
    def test_inc(self):
        c = Counter("test_total")
        c.inc()
        assert c.get() == 1.0
        c.inc(4)
        assert c.get() == 5.0

    def test_start_zero(self):
        c = Counter("zero")
        assert c.get() == 0.0

    def test_labels_format(self):
        c = Counter("http_requests", labels={"method": "GET", "status": "200"})
        lb = c._format_labels()
        assert 'method="GET"' in lb
        assert 'status="200"' in lb


class TestGauge:
    def test_set_get(self):
        g = Gauge("temperature")
        g.set(42.5)
        assert g.get() == 42.5

    def test_inc_dec(self):
        g = Gauge("queue_size")
        g.inc(3)
        g.dec(1)
        assert g.get() == 2.0


class TestHistogram:
    def test_observe(self):
        h = Histogram("latency", buckets=(0.1, 0.5, 1.0))
        h.observe(0.3)
        h.observe(2.0)
        data = h.get()
        assert data["count"] == 2
        assert data["buckets"][0.1] == 0
        assert data["buckets"][0.5] == 1
        assert data["buckets"][1.0] == 0
        assert data["buckets"]["+Inf"] == 1

    def test_percentiles(self):
        h = Histogram("lat", buckets=(1, 2, 5, 10))
        for v in [1, 2, 3, 4, 5, 100]:
            h.observe(v)
        # p50: int(6*0.5)=3rd item falls in bucket 5
        assert h.p50() == 5.0
        # p99: int(6*0.99)=5th item falls in bucket 5
        assert h.p99() == 5.0

    def test_empty_percentile(self):
        h = Histogram("empty")
        assert h.p50() == 0.0


class TestTimer:
    def test_context_manager(self):
        t = Timer("operation")
        with t:
            pass
        data = t.get()
        assert data["count"] == 1.0
        assert data["histogram"]["count"] == 1

    def test_time_function(self):
        t = Timer("func")
        result = t.time(lambda: 42)
        assert result == 42
        assert t._call_count.get() == 1.0


class TestMetricsCollector:
    def test_counter_creation(self):
        mc = MetricsCollector()
        c = mc.counter("requests", "Total requests")
        assert c.name == "requests"
        c.inc()
        assert c.get() == 1.0

    def test_counter_reuse(self):
        mc = MetricsCollector()
        a = mc.counter("x")
        b = mc.counter("x")
        assert a is b
        a.inc()
        assert b.get() == 1.0

    def test_gauge(self):
        mc = MetricsCollector()
        g = mc.gauge("mem_bytes")
        g.set(1024)
        assert g.get() == 1024

    def test_histogram(self):
        mc = MetricsCollector()
        h = mc.histogram("latency", buckets=(1, 10))
        h.observe(5)
        assert h.get()["count"] == 1

    def test_timer(self):
        mc = MetricsCollector()
        t = mc.timer("api_latency")
        with t:
            time.sleep(0.01)
        assert t._call_count.get() == 1.0

    def test_namespace(self):
        mc = MetricsCollector(namespace="app")
        c = mc.counter("hits")
        assert c.name == "app_hits"

    def test_get(self):
        mc = MetricsCollector()
        mc.counter("total")
        assert mc.get("total") is not None
        assert mc.get("nonexistent") is None

    def test_list_metrics(self):
        mc = MetricsCollector()
        mc.counter("a")
        mc.gauge("b")
        assert set(mc.list_metrics()) == {"a", "b"}

    def test_get_all(self):
        mc = MetricsCollector()
        mc.counter("calls").inc(5)
        mc.gauge("mem").set(100)
        all_m = mc.get_all()
        assert all_m["calls"] == 5.0
        assert all_m["mem"] == 100.0

    def test_to_prometheus(self):
        mc = MetricsCollector()
        mc.counter("requests_total", "Total requests").inc(10)
        mc.gauge("active", "Active connections").set(3)
        text = mc.to_prometheus()
        assert "# HELP requests_total Total requests" in text
        assert "# TYPE requests_total counter" in text
        assert "requests_total 10.0" in text
        assert "# HELP active Active connections" in text
        assert "active 3" in text

    def test_prometheus_histogram(self):
        mc = MetricsCollector()
        h = mc.histogram("latency", "Latency histogram", buckets=(0.5, 1.0))
        h.observe(0.3)
        h.observe(2.0)
        text = mc.to_prometheus()
        assert "# HELP latency Latency histogram" in text
        assert 'latency_count 2' in text
        assert 'le="0.5"}' in text
        assert 'le="1.0"}' in text
        assert 'le="+Inf"}' in text

    def test_prometheus_timer(self):
        mc = MetricsCollector()
        t = mc.timer("requests", "Request duration")
        with t:
            pass
        text = mc.to_prometheus()
        assert "# HELP requests Request duration" in text
        assert "requests_count" in text
        assert "requests_sum" in text


class TestGlobalCollector:
    def test_singleton(self):
        c1 = get_metrics_collector()
        c2 = get_metrics_collector()
        assert c1 is c2
