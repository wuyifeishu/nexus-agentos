"""
AgentOS v0.70 — 性能指标与可观测性增强。
基因来源: Prometheus metrics + OpenTelemetry

提供:
- 延迟分位数 (p50/p95/p99)
- 吞吐量统计 (RPS)
- 错误率追踪
- 缓存命中率
- TTL-based环形缓冲区
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricSnapshot:
    """指标快照 — 用于导出/序列化。"""
    timestamp: float = field(default_factory=time.time)
    histograms: dict[str, dict] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)
    derived_metrics: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> str:
        import json
        return json.dumps({
            "ts": self.timestamp,
            "h": self.histograms,
            "c": self.counters,
            "g": self.gauges,
            "d": self.derived_metrics,
        })

    @classmethod
    def from_collector(cls, collector: "MetricsCollector") -> "MetricSnapshot":
        s = collector.snapshot()
        return cls(
            histograms={"step": s["latency_step_ms"], "model": s["latency_model_ms"], "tool": s["latency_tool_ms"]},
            counters={"steps": collector.steps_total.value, "model_calls": collector.model_calls_total.value,
                       "tool_calls": collector.tool_calls_total.value, "errors": collector.errors_total.value,
                       "cache_hits": collector.cache_hits.value, "cache_misses": collector.cache_misses.value},
            gauges={"active_agents": collector.active_agents.value, "queue_depth": collector.queue_depth.value},
            derived_metrics={"rps": s["throughput"]["rps"], "error_rate": s["error_rate"], "cache_hit_rate": s["cache_hit_rate"]},
        )


@dataclass
class MetricPoint:
    """指标数据点。"""
    timestamp: float
    value: float
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Histogram:
    """滑动窗口直方图 — 计算分位数。"""
    name: str
    window_seconds: float = 300.0
    max_size: int = 10000
    _points: deque = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, value: float, **labels):
        with self._lock:
            self._points.append(MetricPoint(timestamp=time.time(), value=value, labels=labels))
            self._prune()
            if len(self._points) > self.max_size:
                self._points.popleft()

    def _prune(self):
        cutoff = time.time() - self.window_seconds
        while self._points and self._points[0].timestamp < cutoff:
            self._points.popleft()

    @property
    def count(self) -> int:
        with self._lock:
            self._prune()
            return len(self._points)

    def quantile(self, q: float) -> float:
        """计算分位数 0.5=p50, 0.95=p95, 0.99=p99。"""
        with self._lock:
            self._prune()
            if not self._points:
                return 0.0
            values = sorted(p.value for p in self._points)
            idx = int(len(values) * q)
            if idx >= len(values):
                idx = len(values) - 1
            return values[idx]

    @property
    def p50(self) -> float:
        return self.quantile(0.5)

    @property
    def p95(self) -> float:
        return self.quantile(0.95)

    @property
    def p99(self) -> float:
        return self.quantile(0.99)

    @property
    def avg(self) -> float:
        with self._lock:
            self._prune()
            if not self._points:
                return 0.0
            return sum(p.value for p in self._points) / len(self._points)

    @property
    def min_val(self) -> float:
        with self._lock:
            self._prune()
            if not self._points:
                return 0.0
            return min(p.value for p in self._points)

    @property
    def max_val(self) -> float:
        with self._lock:
            self._prune()
            if not self._points:
                return 0.0
            return max(p.value for p in self._points)

    def stats(self) -> dict:
        return {
            "name": self.name,
            "count": self.count,
            "avg": self.avg,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "min": self.min_val,
            "max": self.max_val,
            "window_seconds": self.window_seconds,
        }


@dataclass
class Counter:
    """单调递增计数器。"""
    name: str
    _value: int = 0
    _labels: dict[str, str] = field(default_factory=dict)

    def inc(self, amount: int = 1):
        self._value += amount

    @property
    def value(self) -> int:
        return self._value


@dataclass
class Gauge:
    """可增可减的仪表值。"""
    name: str
    _value: float = 0.0
    _labels: dict[str, str] = field(default_factory=dict)

    def set(self, value: float):
        self._value = value

    def inc(self, amount: float = 1.0):
        self._value += amount

    def dec(self, amount: float = 1.0):
        self._value -= amount

    @property
    def value(self) -> float:
        return self._value


class MetricsCollector:
    """
    统一指标收集器。
    内置: latency, throughput, error_rate, cache_hit_rate。
    """

    def __init__(self, window_seconds: float = 300.0):
        self.window_seconds = window_seconds

        # Histograms
        self.latency_step = Histogram("step_latency", window_seconds)
        self.latency_model = Histogram("model_latency", window_seconds)
        self.latency_tool = Histogram("tool_latency", window_seconds)

        # Counters
        self.steps_total = Counter("steps_total")
        self.model_calls_total = Counter("model_calls_total")
        self.tool_calls_total = Counter("tool_calls_total")
        self.errors_total = Counter("errors_total")
        self.cache_hits = Counter("cache_hits")
        self.cache_misses = Counter("cache_misses")

        # Gauges
        self.active_agents = Gauge("active_agents")
        self.queue_depth = Gauge("queue_depth")
        self.memory_used_mb = Gauge("memory_used_mb")

        self._start_time = time.time()

    # ── Recording ────────────────────────────────

    def record_step_latency(self, duration_ms: float):
        self.latency_step.observe(duration_ms)
        self.steps_total.inc()

    def record_model_latency(self, duration_ms: float, model: str = ""):
        self.latency_model.observe(duration_ms, model=model)
        self.model_calls_total.inc()

    def record_tool_latency(self, duration_ms: float, tool: str = ""):
        self.latency_tool.observe(duration_ms, tool=tool)
        self.tool_calls_total.inc()

    def record_error(self):
        self.errors_total.inc()

    def record_cache_hit(self):
        self.cache_hits.inc()

    def record_cache_miss(self):
        self.cache_misses.inc()

    # ── Derived Metrics ──────────────────────────

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time

    @property
    def rps(self) -> float:
        """请求速率 (steps/sec over window)。"""
        if self.uptime_seconds < 1:
            return self.steps_total.value
        return self.steps_total.value / self.uptime_seconds

    @property
    def error_rate(self) -> float:
        total = self.steps_total.value + self.errors_total.value
        if total == 0:
            return 0.0
        return self.errors_total.value / total

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits.value + self.cache_misses.value
        if total == 0:
            return 0.0
        return self.cache_hits.value / total

    # ── Snapshot ─────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "uptime_seconds": self.uptime_seconds,
            "throughput": {
                "rps": round(self.rps, 2),
                "steps_total": self.steps_total.value,
                "model_calls": self.model_calls_total.value,
                "tool_calls": self.tool_calls_total.value,
            },
            "latency_step_ms": self.latency_step.stats(),
            "latency_model_ms": self.latency_model.stats(),
            "latency_tool_ms": self.latency_tool.stats(),
            "error_rate": round(self.error_rate, 4),
            "errors_total": self.errors_total.value,
            "cache_hit_rate": round(self.cache_hit_rate, 2),
            "cache_hits": self.cache_hits.value,
            "cache_misses": self.cache_misses.value,
            "active_agents": self.active_agents.value,
            "queue_depth": self.queue_depth.value,
        }

    def summary(self) -> str:
        s = self.snapshot()
        lines = [
            f"运行时间: {s['uptime_seconds']:.0f}s",
            f"吞吐: {s['throughput']['rps']} rps ({s['throughput']['steps_total']} steps)",
            f"延迟: p50={s['latency_step_ms']['p50']:.0f}ms p95={s['latency_step_ms']['p95']:.0f}ms p99={s['latency_step_ms']['p99']:.0f}ms",
            f"错误率: {s['error_rate']:.2%} ({s['errors_total']} errors)",
            f"缓存命中率: {s['cache_hit_rate']:.1%} ({s['cache_hits']}/{s['cache_hits'] + s['cache_misses']})",
        ]
        return "\n".join(lines)
