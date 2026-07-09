"""Tests for observability/tracing module."""

from agentos.observability.tracing import (
    _NoOpSpan,
    _NoOpTracer,
    get_current_span,
    get_tracer,
    setup_tracing,
    shutdown_tracing,
    trace_function,
)


class TestNoOpTracer:
    """Without OTel configured, all calls should be no-op."""

    def test_get_tracer_returns_noop(self):
        tracer = get_tracer("test")
        assert isinstance(tracer, _NoOpTracer)

    def test_start_as_current_span_yields_noop(self):
        tracer = get_tracer("test")
        with tracer.start_as_current_span("test.span") as span:
            assert isinstance(span, _NoOpSpan)
            span.set_attribute("key", "value")  # no error
            span.set_status(None)  # no error
            span.add_event("event", {"k": "v"})  # no error

    def test_trace_function_decorator_works(self):
        @trace_function(name="my_span")
        def my_fn(x):
            return x * 2

        result = my_fn(42)
        assert result == 84

    def test_get_current_span_noop(self):
        span = get_current_span()
        assert isinstance(span, _NoOpSpan)

    def test_setup_tracing_no_endpoint_does_nothing(self):
        setup_tracing(otlp_endpoint="")  # should not crash
        tracer = get_tracer()
        assert isinstance(tracer, _NoOpTracer)

    def test_shutdown_tracing_noop(self):
        shutdown_tracing()  # should not crash
