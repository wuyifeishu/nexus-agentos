"""
AgentOS v1.14.3 — Observability Platform (OpenTelemetry Integration).

Production-grade observability for AgentOS agent pipelines:
- Distributed tracing (OpenTelemetry spans)
- Metrics collection (Prometheus-compatible counters, histograms, gauges)
- Structured logging with correlation IDs
- Agent lifecycle events instrumentation
- Cost tracking dashboard
- Latency breakdown by pipeline stage

Architecture:
    AgentOS Pipeline
        ├── OTel Tracer (auto-instrumented)
        │   ├── Agent invocation span
        │   │   ├── LLM call span
        │   │   ├── Tool call span
        │   │   └── Memory retrieval span
        ├── MetricsExporter (Prometheus)
        └── StructuredLogger (JSON)

Inspired by: LangSmith, Weave, Arize Phoenix
"""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union,
)


# ── Span & Trace Types ──────────────────────


class SpanKind(str, Enum):
    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    MEMORY = "memory"
    RETRIEVAL = "retrieval"
    CHAIN = "chain"
    EMBEDDING = "embedding"


class SpanStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class SpanEvent:
    """Span 中的事件。"""
    name: str
    timestamp: float = field(default_factory=time.time)
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """OpenTelemetry 风格的 Span。"""

    span_id: str = field(default_factory=lambda: f"span-{uuid.uuid4().hex[:12]}")
    parent_id: Optional[str] = None
    trace_id: str = field(default_factory=lambda: f"trace-{uuid.uuid4().hex[:16]}")
    name: str = ""
    kind: SpanKind = SpanKind.AGENT

    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: SpanStatus = SpanStatus.OK

    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)
    children: List["Span"] = field(default_factory=list)

    # Agent-specific
    model_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> SpanEvent:
        event = SpanEvent(name=name, attributes=attributes or {})
        self.events.append(event)
        return event

    def set_error(self, error: str) -> None:
        self.status = SpanStatus.ERROR
        self.attributes["error"] = error

    def finish(self) -> None:
        self.end_time = time.time()

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "trace_id": self.trace_id,
            "name": self.name,
            "kind": self.kind.value,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
            "attributes": self.attributes,
            "model_name": self.model_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


@dataclass
class Trace:
    """一次完整的 Agent 调用链路。"""

    trace_id: str = field(default_factory=lambda: f"trace-{uuid.uuid4().hex[:16]}")
    root_span: Optional[Span] = None
    spans: List[Span] = field(default_factory=list)

    @property
    def total_duration_ms(self) -> float:
        if not self.root_span:
            return 0.0
        return self.root_span.duration_ms

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.spans)

    @property
    def total_tokens(self) -> int:
        return sum(s.input_tokens + s.output_tokens for s in self.spans)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "total_duration_ms": self.total_duration_ms,
            "total_cost_usd": self.total_cost_usd,
            "total_tokens": self.total_tokens,
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
        }


# ── Tracer ──────────────────────────────────


class Tracer:
    """AgentOS 追踪器。

    自动检测 Agent/LMM/Tool/Memory 调用并创建 Span。

    Usage:
        tracer = Tracer()
        with tracer.start_span("my_agent", SpanKind.AGENT) as span:
            span.set_attribute("user_id", "123")
            # ... agent logic ...
    """

    def __init__(self, service_name: str = "agentos"):
        self._service_name = service_name
        self._active_trace: Optional[Trace] = None
        self._span_stack: List[Span] = []
        self._exporters: List[Callable] = []
        self._trace_count: int = 0

    def add_exporter(self, exporter: Callable[[Trace], None]) -> None:
        """添加导出器。"""
        self._exporters.append(exporter)

    @contextmanager
    def start_trace(self, name: str = "") -> Iterator[Trace]:
        """创建新 Trace。"""
        trace = Trace()
        trace.trace_id = f"trace-{uuid.uuid4().hex[:16]}"

        old_trace = self._active_trace
        self._active_trace = trace

        try:
            yield trace
        finally:
            trace.root_span = trace.spans[0] if trace.spans else None
            self._active_trace = old_trace
            self._trace_count += 1

            # Export
            for exporter in self._exporters:
                try:
                    exporter(trace)
                except Exception:
                    pass

    @contextmanager
    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.AGENT,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Span]:
        """在当前 Trace 中创建 Span。"""
        span = Span(
            name=name,
            kind=kind,
            trace_id=self._active_trace.trace_id if self._active_trace else "",
        )

        if self._span_stack:
            span.parent_id = self._span_stack[-1].span_id
            self._span_stack[-1].children.append(span)

        if attributes:
            span.attributes.update(attributes)

        self._span_stack.append(span)

        if self._active_trace:
            self._active_trace.spans.append(span)

        try:
            yield span
        except Exception as e:
            span.set_error(str(e))
            raise
        finally:
            span.finish()
            self._span_stack.pop()

    def record_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        duration_ms: float,
    ) -> None:
        """记录 LLM 调用指标。"""
        if self._span_stack:
            span = self._span_stack[-1]
            span.model_name = model
            span.input_tokens = input_tokens
            span.output_tokens = output_tokens
            span.cost_usd = cost_usd

    def record_tool_call(self, tool_name: str, success: bool, duration_ms: float) -> None:
        """记录工具调用。"""
        if self._span_stack:
            span = self._span_stack[-1]
            span.add_event("tool_call", {
                "tool_name": tool_name,
                "success": success,
                "duration_ms": duration_ms,
            })


# ── Metrics ─────────────────────────────────


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """单个指标。"""
    name: str
    type: MetricType
    description: str = ""
    labels: Dict[str, str] = field(default_factory=dict)
    value: float = 0.0
    timestamp: float = field(default_factory=time.time)


class MetricsRegistry:
    """Prometheus 风格的指标注册表。

    Usage:
        registry = MetricsRegistry()
        counter = registry.counter("agent_invocations_total", "Total agent calls")
        counter.inc()

        histogram = registry.histogram("llm_latency_ms", "LLM call latency")
        histogram.observe(1234.5)
    """

    def __init__(self):
        self._metrics: Dict[str, Metric] = {}
        self._counters: Dict[str, "Counter"] = {}
        self._histograms: Dict[str, "Histogram"] = {}
        self._gauges: Dict[str, "Gauge"] = {}

    def counter(self, name: str, description: str = "") -> "Counter":
        if name not in self._counters:
            c = Counter(name, description)
            self._counters[name] = c
            self._metrics[name] = Metric(
                name=name, type=MetricType.COUNTER, description=description
            )
        return self._counters[name]

    def histogram(self, name: str, description: str = "",
                  buckets: Optional[List[float]] = None) -> "Histogram":
        if name not in self._histograms:
            h = Histogram(name, description, buckets)
            self._histograms[name] = h
            self._metrics[name] = Metric(
                name=name, type=MetricType.HISTOGRAM, description=description
            )
        return self._histograms[name]

    def gauge(self, name: str, description: str = "") -> "Gauge":
        if name not in self._gauges:
            g = Gauge(name, description)
            self._gauges[name] = g
            self._metrics[name] = Metric(
                name=name, type=MetricType.GAUGE, description=description
            )
        return self._gauges[name]

    def collect(self) -> List[dict]:
        """收集所有指标的当前值（Prometheus scrape 格式）。"""
        results = []
        now = time.time()

        for name, counter in self._counters.items():
            results.append({
                "name": name,
                "type": "counter",
                "value": counter.value,
                "timestamp": now,
            })

        for name, histogram in self._histograms.items():
            results.append({
                "name": name,
                "type": "histogram",
                "count": histogram.count,
                "sum": histogram.sum,
                "buckets": dict(histogram.buckets),
                "timestamp": now,
            })

        for name, gauge in self._gauges.items():
            results.append({
                "name": name,
                "type": "gauge",
                "value": gauge.value,
                "timestamp": now,
            })

        return results

    def to_prometheus_text(self) -> str:
        """导出为 Prometheus 文本格式。"""
        lines = []
        for metric in self.collect():
            lines.append(f"# HELP {metric['name']} AgentOS metric")
            lines.append(f"# TYPE {metric['name']} {metric['type']}")

            if metric["type"] == "histogram":
                lines.append(f"{metric['name']}_count {metric['count']}")
                lines.append(f"{metric['name']}_sum {metric['sum']}")
                for bucket, count in metric.get("buckets", {}).items():
                    lines.append(f"{metric['name']}_bucket{{le=\"{bucket}\"}} {count}")
            else:
                lines.append(f"{metric['name']} {metric['value']}")

        return "\n".join(lines)


class Counter:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value: float = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self._value += amount

    @property
    def value(self) -> float:
        return self._value


class Gauge:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value: float = 0.0

    def set(self, value: float) -> None:
        self._value = value

    @property
    def value(self) -> float:
        return self._value


class Histogram:
    DEFAULT_BUCKETS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000, 10000]

    def __init__(self, name: str, description: str = "",
                 buckets: Optional[List[float]] = None):
        self.name = name
        self.description = description
        self.buckets: Dict[float, int] = {}
        for b in (buckets or self.DEFAULT_BUCKETS):
            self.buckets[b] = 0
        self._count: int = 0
        self._sum: float = 0.0

    def observe(self, value: float) -> None:
        self._count += 1
        self._sum += value
        for boundary in sorted(self.buckets.keys()):
            if value <= boundary:
                self.buckets[boundary] += 1
                break

    @property
    def count(self) -> int:
        return self._count

    @property
    def sum(self) -> float:
        return self._sum


# ── Structured Logger ───────────────────────


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class StructuredLogger:
    """结构化 JSON 日志记录器，自动注入 trace_id 和 span_id。

    Usage:
        logger = StructuredLogger(tracer)
        logger.info("Agent started", agent_name="ToolAgent", user_id="123")
    """

    def __init__(self, tracer: Optional[Tracer] = None):
        self._tracer = tracer
        self._handlers: List[Callable] = []
        self._level = LogLevel.INFO

    def add_handler(self, handler: Callable[[dict], None]) -> None:
        self._handlers.append(handler)

    def set_level(self, level: LogLevel) -> None:
        self._level = level

    def log(self, level: LogLevel, message: str, **kwargs) -> None:
        entry = {
            "timestamp": time.time(),
            "level": level.value,
            "message": message,
            **kwargs,
        }

        # Inject trace context
        if self._tracer:
            trace = self._tracer._active_trace
            if trace:
                entry["trace_id"] = trace.trace_id
            if self._tracer._span_stack:
                entry["span_id"] = self._tracer._span_stack[-1].span_id

        for handler in self._handlers:
            try:
                handler(entry)
            except Exception:
                pass

    def debug(self, message: str, **kwargs) -> None:
        self.log(LogLevel.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        self.log(LogLevel.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        self.log(LogLevel.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        self.log(LogLevel.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        self.log(LogLevel.CRITICAL, message, **kwargs)


# ── Dashboard Data ──────────────────────────


class ObservabilityDashboard:
    """可观测性数据聚合器 — 为 Grafana/自定义仪表盘提供数据。

    Usage:
        dashboard = ObservabilityDashboard(tracer, metrics)
        summary = dashboard.get_summary()
    """

    def __init__(self, tracer: Tracer, metrics: MetricsRegistry):
        self._tracer = tracer
        self._metrics = metrics
        self._trace_buffer: List[Trace] = []
        self._max_buffer = 1000

    def record_trace(self, trace: Trace) -> None:
        self._trace_buffer.append(trace)
        if len(self._trace_buffer) > self._max_buffer:
            self._trace_buffer = self._trace_buffer[-self._max_buffer:]

    def get_summary(self) -> dict:
        """获取综合摘要。"""
        traces = self._trace_buffer[-100:]  # Last 100 traces

        if not traces:
            return {"message": "No traces recorded"}

        durations = [t.total_duration_ms for t in traces]
        costs = [t.total_cost_usd for t in traces]

        durations.sort()

        # Span kind distribution
        kind_counts: Dict[str, int] = defaultdict(int)
        error_count = 0
        for t in traces:
            for s in t.spans:
                kind_counts[s.kind.value] += 1
                if s.status == SpanStatus.ERROR:
                    error_count += 1

        return {
            "trace_count": len(traces),
            "total_traces": self._tracer._trace_count,
            "error_rate": error_count / max(sum(kind_counts.values()), 1),
            "duration": {
                "p50_ms": durations[len(durations) // 2] if durations else 0,
                "p95_ms": durations[int(len(durations) * 0.95)] if len(durations) > 1 else 0,
                "p99_ms": durations[int(len(durations) * 0.99)] if len(durations) > 1 else 0,
                "avg_ms": sum(durations) / len(durations) if durations else 0,
            },
            "cost": {
                "total_usd": sum(costs),
                "avg_per_trace_usd": sum(costs) / len(costs) if costs else 0,
            },
            "span_distribution": dict(kind_counts),
            "metrics": self._metrics.collect(),
        }

    def get_latency_breakdown(self) -> List[dict]:
        """按 pipeline 阶段拆分延迟。"""
        breakdown: Dict[str, List[float]] = defaultdict(list)

        for trace in self._trace_buffer[-100:]:
            for span in trace.spans:
                breakdown[span.kind.value].append(span.duration_ms)

        result = []
        for kind, values in breakdown.items():
            values.sort()
            n = len(values)
            result.append({
                "stage": kind,
                "count": n,
                "avg_ms": sum(values) / n if n else 0,
                "p50_ms": values[n // 2] if n else 0,
                "p95_ms": values[int(n * 0.95)] if n > 1 else (values[0] if values else 0),
            })

        return result


# ── Quick Start ─────────────────────────────


def create_observability_stack(service_name: str = "agentos"):
    """一键创建可观测性栈。"""
    tracer = Tracer(service_name=service_name)
    metrics = MetricsRegistry()
    logger = StructuredLogger(tracer)
    dashboard = ObservabilityDashboard(tracer, metrics)

    # Register auto-export
    tracer.add_exporter(dashboard.record_trace)

    # Register default metrics
    metrics.counter("agent_invocations_total", "Total agent invocations")
    metrics.histogram("agent_latency_ms", "Agent end-to-end latency")
    metrics.histogram("llm_latency_ms", "LLM call latency")
    metrics.counter("tool_calls_total", "Total tool calls")
    metrics.counter("tool_errors_total", "Total tool errors")
    metrics.gauge("active_agents", "Currently active agents")

    return tracer, metrics, logger, dashboard
