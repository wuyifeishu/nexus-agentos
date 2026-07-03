"""
Metrics Collector for AgentOS.

Lightweight in-process metrics with Counter, Gauge, Histogram, and Timer.
Thread-safe, zero external dependencies, Prometheus-style text exposition.
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Union


# ============================================================================
# Histogram buckets (pre-defined for common latency ranges)
# ============================================================================

DEFAULT_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)
LARGE_BUCKETS = (
    0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0, 3600.0,
)


# ============================================================================
# Metric types
# ============================================================================

class Counter:
    """Monotonically increasing counter. Thread-safe."""

    def __init__(self, name: str, help_text: str = "", labels: Optional[Dict[str, str]] = None):
        self.name = name
        self.help = help_text
        self.labels = labels or {}
        self._value: float = 0.0
        self._lock = threading.Lock()

    def inc(self, delta: float = 1.0) -> None:
        with self._lock:
            self._value += delta

    def get(self) -> float:
        with self._lock:
            return self._value

    def _format_labels(self) -> str:
        if not self.labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in self.labels.items()) + "}"


class Gauge:
    """Value that can go up and down. Thread-safe."""

    def __init__(self, name: str, help_text: str = "", labels: Optional[Dict[str, str]] = None):
        self.name = name
        self.help = help_text
        self.labels = labels or {}
        self._value: float = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, delta: float = 1.0) -> None:
        with self._lock:
            self._value += delta

    def dec(self, delta: float = 1.0) -> None:
        with self._lock:
            self._value -= delta

    def get(self) -> float:
        with self._lock:
            return self._value

    def _format_labels(self) -> str:
        if not self.labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in self.labels.items()) + "}"


class Histogram:
    """Bucketed histogram with sum and count. Thread-safe."""

    def __init__(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[Dict[str, str]] = None,
        buckets: tuple = DEFAULT_BUCKETS,
    ):
        self.name = name
        self.help = help_text
        self.labels = labels or {}
        self.buckets = tuple(sorted(buckets))
        self._lock = threading.Lock()
        self._bucket_counts: List[int] = [0] * (len(self.buckets) + 1)  # +1 for +Inf
        self._sum: float = 0.0
        self._count: int = 0

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    self._bucket_counts[i] += 1
                    return
            self._bucket_counts[-1] += 1  # +Inf bucket

    def get(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "sum": self._sum,
                "count": self._count,
                "buckets": dict(zip(self.buckets + ("+Inf",), self._bucket_counts)),
            }

    def p50(self) -> float:
        return self._percentile(0.50)

    def p90(self) -> float:
        return self._percentile(0.90)

    def p99(self) -> float:
        return self._percentile(0.99)

    def _percentile(self, p: float) -> float:
        with self._lock:
            if self._count == 0:
                return 0.0
            target = int(self._count * p)
            accumulated = 0
            for i, bc in enumerate(self._bucket_counts):
                accumulated += bc
                if accumulated >= target:
                    if i < len(self.buckets):
                        return self.buckets[i]
                    return self.buckets[-1] if self.buckets else 0.0
            return self.buckets[-1] if self.buckets else 0.0

    def _format_labels(self) -> str:
        if not self.labels:
            return ""
        return "{" + ",".join(f'{k}="{v}"' for k, v in self.labels.items()) + "}"


class Timer:
    """Convenience wrapper: Histogram for timing. Also tracks rate via internal counter."""

    def __init__(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[Dict[str, str]] = None,
        buckets: tuple = DEFAULT_BUCKETS,
    ):
        self.name = name
        self.help = help_text
        self.histogram = Histogram(name, help_text, labels, buckets)
        self._call_count = Counter(name + "_total", help_text, labels)

    def time(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - start
            self.histogram.observe(elapsed)
            self._call_count.inc()

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed = time.perf_counter() - self._start
        self.histogram.observe(elapsed)
        self._call_count.inc()

    def get(self) -> Dict[str, Any]:
        return {
            "histogram": self.histogram.get(),
            "count": self._call_count.get(),
        }


# ============================================================================
# MetricsCollector (Registry)
# ============================================================================

class MetricsCollector:
    """Global registry for metrics. Provides Prometheus text format exposition."""

    def __init__(self, namespace: str = ""):
        self.namespace = namespace
        self._metrics: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def _full_name(self, name: str) -> str:
        if self.namespace:
            return f"{self.namespace}_{name}"
        return name

    def counter(self, name: str, help_text: str = "", labels: Optional[Dict[str, str]] = None) -> Counter:
        full = self._full_name(name)
        with self._lock:
            if full not in self._metrics:
                self._metrics[full] = Counter(full, help_text, labels)
            return self._metrics[full]

    def gauge(self, name: str, help_text: str = "", labels: Optional[Dict[str, str]] = None) -> Gauge:
        full = self._full_name(name)
        with self._lock:
            if full not in self._metrics:
                self._metrics[full] = Gauge(full, help_text, labels)
            return self._metrics[full]

    def histogram(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[Dict[str, str]] = None,
        buckets: tuple = DEFAULT_BUCKETS,
    ) -> Histogram:
        full = self._full_name(name)
        with self._lock:
            if full not in self._metrics:
                self._metrics[full] = Histogram(full, help_text, labels, buckets)
            return self._metrics[full]

    def timer(
        self,
        name: str,
        help_text: str = "",
        labels: Optional[Dict[str, str]] = None,
        buckets: tuple = DEFAULT_BUCKETS,
    ) -> Timer:
        full = self._full_name(name)
        with self._lock:
            if full not in self._metrics:
                self._metrics[full] = Timer(full, help_text, labels, buckets)
            return self._metrics[full]

    def get(self, name: str) -> Optional[Any]:
        return self._metrics.get(self._full_name(name))

    def list_metrics(self) -> List[str]:
        with self._lock:
            return list(self._metrics.keys())

    def get_all(self) -> Dict[str, Any]:
        """Return raw values for all metrics (for programmatic use)."""
        result = {}
        with self._lock:
            for name, metric in self._metrics.items():
                if hasattr(metric, "get"):
                    result[name] = metric.get()
        return result

    def to_prometheus(self) -> str:
        """Export all metrics in Prometheus text format."""
        lines = []
        with self._lock:
            for name, metric in self._metrics.items():
                if metric.help:
                    lines.append(f"# HELP {name} {metric.help}")
                lines.append(f"# TYPE {name} histogram" if isinstance(metric, (Histogram, Timer)) else
                             f"# TYPE {name} gauge" if isinstance(metric, Gauge) else
                             f"# TYPE {name} counter")

                if isinstance(metric, Counter):
                    lbl = metric._format_labels()
                    lines.append(f"{name}{lbl} {metric.get()}")
                elif isinstance(metric, Gauge):
                    lbl = metric._format_labels()
                    lines.append(f"{name}{lbl} {metric.get()}")
                elif isinstance(metric, Histogram):
                    lbl = metric._format_labels()
                    data = metric.get()
                    lines.append(f"{name}_count{lbl} {data['count']}")
                    lines.append(f"{name}_sum{lbl} {data['sum']}")
                    for bucket_name in metric.buckets + ("+Inf",):
                        bval = data["buckets"].get(bucket_name, 0)
                        # Prometheus: bucket labels use 'le' key
                        le_label = '{le="' + str(bucket_name) + '"}'
                        lines.append(f"{name}_bucket{lbl}{le_label} {bval}")
                elif isinstance(metric, Timer):
                    lbl = metric.histogram._format_labels()
                    hdata = metric.histogram.get()
                    lines.append(f"{name}_count{lbl} {hdata['count']}")
                    lines.append(f"{name}_sum{lbl} {hdata['sum']}")
                    for bucket_name in metric.histogram.buckets + ("+Inf",):
                        bval = hdata["buckets"].get(bucket_name, 0)
                        le_label = '{le="' + str(bucket_name) + '"}'
                        lines.append(f"{name}_bucket{lbl}{le_label} {bval}")

        return "\n".join(lines) + "\n"


# ============================================================================
# Global singleton
# ============================================================================

_default_collector: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics_collector(namespace: str = "") -> MetricsCollector:
    global _default_collector
    if _default_collector is None:
        with _collector_lock:
            if _default_collector is None:
                _default_collector = MetricsCollector(namespace=namespace or "agentos")
    return _default_collector
