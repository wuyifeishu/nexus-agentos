"""AgentOS OpenTelemetry - OTLP/Jaeger/Zipkin trace/metric export (v1.3.14)."""

import os
import logging
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agentos.observability.metrics import MetricsCollector

logger = logging.getLogger("agentos.otel")


# ---- Enums ----

class OTelExporter(str, Enum):
    """OpenTelemetry exporter backend."""
    OTLP_HTTP = "otlp_http"
    OTLP_GRPC = "otlp_grpc"
    CONSOLE = "console"
    ZIPKIN = "zipkin"
    NONE = "none"


class OtelStatus(str, Enum):
    """Span status codes."""
    OK = "OK"
    ERROR = "ERROR"


class SpanKind(str, Enum):
    """Span kind for semantic conventions."""
    INTERNAL = "internal"
    CLIENT = "client"
    SERVER = "server"
    PRODUCER = "producer"
    CONSUMER = "consumer"


# ---- OtelConfig ----

@dataclass
class OtelConfig:
    """OpenTelemetry configuration."""

    service_name: str = "agentos"
    service_version: str = ""
    exporter: OTelExporter = OTelExporter.CONSOLE
    endpoint: str = "http://localhost:4318/v1/traces"
    metrics_endpoint: str = "http://localhost:4318/v1/metrics"
    resource_attrs: Dict[str, str] = field(default_factory=dict)
    sample_rate: float = 1.0
    batch_timeout_ms: int = 5000
    max_span_attributes: int = 128
    disabled: bool = False
    api_key: str = ""
    zipkin_endpoint: str = "http://localhost:9411/api/v2/spans"

    def with_env_overrides(self) -> "OtelConfig":
        if v := os.getenv("OTEL_SERVICE_NAME"):
            self.service_name = v
        if v := os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            self.endpoint = v
        if v := os.getenv("OTEL_EXPORTER_ZIPKIN_ENDPOINT"):
            self.zipkin_endpoint = v
        if os.getenv("OTEL_SDK_DISABLED"):
            self.disabled = True
        return self


# ---- SpanHandle ----

def _normalize_value(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)):
        return [_normalize_value(x) for x in v]
    return str(v)


class SpanHandle:
    """Wrapper around OTel span for attribute/event/exception API."""

    def __init__(self, span: Any):
        self._span = span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, _normalize_value(value))

    def set_attributes(self, attrs: Dict[str, Any]) -> None:
        for k, v in attrs.items():
            self.set_attribute(k, v)

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self._span.add_event(name, attributes={
            k: _normalize_value(v) for k, v in (attributes or {}).items()
        })

    def record_exception(self, exception: Exception) -> None:
        self._span.record_exception(exception)

    def set_status(self, status: OtelStatus, description: str = "") -> None:
        from opentelemetry import trace as otel_trace
        code = otel_trace.StatusCode.OK if status == OtelStatus.OK else otel_trace.StatusCode.ERROR
        self._span.set_status(otel_trace.Status(code, description))


# ---- OtelTracer ----

class OtelTracer:
    """OpenTelemetry tracer with span management and W3C context propagation.

    Usage:
        OtelTracer.init(OtelConfig(service_name="my-agent"))

        with OtelTracer.span("llm_call", kind=SpanKind.CLIENT) as span:
            span.set_attribute("model", "gpt-4")
            result = llm.generate(prompt)

        @OtelTracer.trace("process")
        async def process(input): ...
    """

    _config: Optional[OtelConfig] = None
    _tracer_provider: Any = None
    _initialized: bool = False

    @classmethod
    def init(cls, config: Optional[OtelConfig] = None) -> None:
        if config is None:
            config = OtelConfig().with_env_overrides()
        else:
            config = config.with_env_overrides()

        cls._config = config
        if config.disabled:
            cls._initialized = True
            return

        try:
            cls._init_sdk(config)
            cls._initialized = True
            logger.info(
                "OtelTracer initialized: service=%s exporter=%s",
                config.service_name, config.exporter.value,
            )
        except ImportError:
            logger.warning("opentelemetry packages not installed - noop tracer")
            cls._initialized = True
        except Exception as e:
            logger.error("OTel init failed: %s - noop", e)
            cls._initialized = True

    @classmethod
    def _init_sdk(cls, config: OtelConfig):
        from opentelemetry import trace as otel_trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
        from opentelemetry.trace import set_tracer_provider

        resource = Resource.create({
            SERVICE_NAME: config.service_name,
            SERVICE_VERSION: config.service_version,
            **config.resource_attrs,
        })

        provider = TracerProvider(resource=resource)
        exporter = cls._build_exporter(config)
        if exporter:
            provider.add_span_processor(
                BatchSpanProcessor(
                    exporter,
                    schedule_delay_millis=config.batch_timeout_ms,
                    max_export_batch_size=512,
                )
            )
        set_tracer_provider(provider)
        cls._tracer_provider = provider

    @classmethod
    def _build_exporter(cls, config: OtelConfig):
        if config.exporter == OTelExporter.OTLP_HTTP:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            return OTLPSpanExporter(endpoint=config.endpoint)
        elif config.exporter == OTelExporter.OTLP_GRPC:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            return OTLPSpanExporter(endpoint=config.endpoint, insecure=True)
        elif config.exporter == OTelExporter.CONSOLE:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            return ConsoleSpanExporter()
        elif config.exporter == OTelExporter.ZIPKIN:
            from opentelemetry.exporter.zipkin.proto.http import ZipkinExporter
            return ZipkinExporter(endpoint=config.zipkin_endpoint)
        return None

    @classmethod
    def get_tracer(cls, name: str = "agentos") -> Any:
        if not cls._initialized:
            cls.init()
        from opentelemetry import trace as otel_trace
        return otel_trace.get_tracer(name)

    @classmethod
    @contextmanager
    def span(
        cls,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[Dict[str, Any]] = None,
        parent: Any = None,
    ):
        if not cls._initialized:
            cls.init()

        tracer = cls.get_tracer()
        kind_map = {
            SpanKind.INTERNAL: 0,
            SpanKind.CLIENT: 3,
            SpanKind.SERVER: 2,
            SpanKind.PRODUCER: 4,
            SpanKind.CONSUMER: 5,
        }
        sk = kind_map.get(kind, 0)

        from opentelemetry import trace as otel_trace
        span = tracer.start_span(
            name,
            kind=otel_trace.SpanKind(sk),
            attributes={
                k: _normalize_value(v) for k, v in (attributes or {}).items()
            },
        )

        try:
            yield SpanHandle(span)
        except Exception:
            span.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR))
            raise
        finally:
            span.end()

    @classmethod
    def trace(
        cls,
        name: str = "",
        kind: SpanKind = SpanKind.INTERNAL,
        extract_attrs: Optional[Callable] = None,
    ):
        span_name = name

        def decorator(func):
            nonlocal span_name
            import asyncio
            if not span_name:
                span_name = func.__name__
            is_async = asyncio.iscoroutinefunction(func)

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                attrs = extract_attrs(*args, **kwargs) if extract_attrs else {}
                with cls.span(span_name, kind=kind, attributes=attrs) as span:
                    try:
                        result = await func(*args, **kwargs)
                        span.set_attribute("status", "ok")
                        return result
                    except Exception as e:
                        span.record_exception(e)
                        span.set_status(OtelStatus.ERROR)
                        raise

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                attrs = extract_attrs(*args, **kwargs) if extract_attrs else {}
                with cls.span(span_name, kind=kind, attributes=attrs) as span:
                    try:
                        result = func(*args, **kwargs)
                        span.set_attribute("status", "ok")
                        return result
                    except Exception as e:
                        span.record_exception(e)
                        span.set_status(OtelStatus.ERROR)
                        raise

            return async_wrapper if is_async else sync_wrapper

        return decorator

    @classmethod
    @asynccontextmanager
    async def async_span(cls, name: str, kind: SpanKind = SpanKind.INTERNAL, **attrs):
        with cls.span(name, kind=kind, attributes=attrs) as span:
            yield span

    @classmethod
    def shutdown(cls):
        if cls._tracer_provider:
            try:
                cls._tracer_provider.shutdown()
            except Exception:
                pass
            cls._tracer_provider = None
        cls._initialized = False


# ---- OtelMeter ----

class OtelMeter:
    """Bridge MetricsCollector to OpenTelemetry metrics."""

    _meter: Any = None
    _instruments: Dict[str, Any] = {}

    @classmethod
    def init(cls, config: Optional[OtelConfig] = None):
        if config is None:
            config = OtelConfig().with_env_overrides()
        if config.disabled:
            return
        try:
            from opentelemetry import metrics
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

            resource = Resource.create({SERVICE_NAME: config.service_name})
            exporter = OTLPMetricExporter(endpoint=config.metrics_endpoint)
            reader = PeriodicExportingMetricReader(exporter)
            provider = MeterProvider(resource=resource, metric_readers=[reader])
            metrics.set_meter_provider(provider)
            cls._meter = metrics.get_meter(config.service_name, config.service_version)
            logger.info("OtelMeter initialized: endpoint=%s", config.metrics_endpoint)
        except ImportError:
            logger.warning("opentelemetry metrics packages not installed")
        except Exception as e:
            logger.error("OtelMeter init failed: %s", e)

    @classmethod
    def record_counter(
        cls, name: str, value: float, attrs: Optional[Dict[str, str]] = None
    ):
        if cls._meter is None:
            return
        if name not in cls._instruments:
            cls._instruments[name] = cls._meter.create_counter(name, description="")
        cls._instruments[name].add(value, attributes=attrs or {})

    @classmethod
    def record_histogram(
        cls, name: str, value: float, attrs: Optional[Dict[str, str]] = None
    ):
        if cls._meter is None:
            return
        key = f"hist_{name}"
        if key not in cls._instruments:
            cls._instruments[key] = cls._meter.create_histogram(name, description="")
        cls._instruments[key].record(value, attributes=attrs or {})

    @classmethod
    def record_gauge(
        cls, name: str, value: float, attrs: Optional[Dict[str, str]] = None
    ):
        if cls._meter is None:
            return
        key = f"gauge_{name}"
        if key not in cls._instruments:
            cls._instruments[key] = cls._meter.create_up_down_counter(
                name, description=""
            )
        cls._instruments[key].add(value, attributes=attrs or {})

    @classmethod
    def bridge(cls, collector: "MetricsCollector"):
        """Wire MetricsCollector snapshots to OtelMeter on flush."""
        original_flush = collector.flush

        def _hooked_flush():
            snapshots = original_flush()
            for snap in snapshots:
                attrs = dict(snap.tags) if hasattr(snap, "tags") else {}
                if snap.type == "counter":
                    cls.record_counter(snap.name, snap.value, attrs)
                elif snap.type == "histogram":
                    cls.record_histogram(snap.name, snap.value, attrs)
                elif snap.type == "gauge":
                    cls.record_gauge(snap.name, snap.value, attrs)
            return snapshots

        collector.flush = _hooked_flush  # type: ignore[method-assign]


# ---- OtelMiddleware ----

class OtelMiddleware:
    """W3C TraceContext propagation for multi-agent pipelines."""

    @staticmethod
    def inject_context(headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        if headers is None:
            headers = {}
        try:
            from opentelemetry import propagate
            propagate.inject(headers)
        except Exception:
            pass
        return headers

    @staticmethod
    def extract_context(headers: Optional[Dict[str, str]] = None) -> None:
        if headers is None:
            return
        try:
            from opentelemetry import propagate, context
            ctx = propagate.extract(headers)
            context.attach(ctx)
        except Exception:
            pass

    @staticmethod
    def get_trace_id() -> str:
        try:
            from opentelemetry import trace as otel_trace
            span = otel_trace.get_current_span()
            ctx = span.get_span_context()
            if ctx.is_valid:
                return format(ctx.trace_id, "032x")
        except Exception:
            pass
        return ""

    @staticmethod
    def get_span_id() -> str:
        try:
            from opentelemetry import trace as otel_trace
            span = otel_trace.get_current_span()
            ctx = span.get_span_context()
            if ctx.is_valid:
                return format(ctx.span_id, "016x")
        except Exception:
            pass
        return ""
