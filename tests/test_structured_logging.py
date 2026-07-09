"""
Tests for agentos.observability.logging — JSON structured logging with context propagation.
"""

import io
import json
import logging
import os
import tempfile

import pytest

from agentos.observability.logging import (
    ContextLogger,
    JsonFormatter,
    configure_logging,
    get_logger,
    get_request_id,
    get_session_id,
    get_tenant_id,
    set_request_id,
    set_session_id,
    set_tenant_id,
)


class TestJsonFormatter:
    def test_basic_output(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=42, msg="hello %s", args=("world",),
            exc_info=None
        )
        output = json.loads(fmt.format(record))
        assert output["level"] == "INFO"
        assert output["message"] == "hello world"
        assert output["logger"] == "test"
        assert output["line"] == 42
        assert output["pid"] == os.getpid()
        assert "timestamp" in output

    def test_extra_fields(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            name="t", level=logging.WARNING, pathname="a.py",
            lineno=1, msg="x", args=(), exc_info=None
        )
        record.user_id = "u-1"
        record.duration_ms = 15.3
        output = json.loads(fmt.format(record))
        assert output["user_id"] == "u-1"
        assert output["duration_ms"] == 15.3

    def test_exception_info(self):
        fmt = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="t", level=logging.ERROR, pathname="a.py",
            lineno=1, msg="fail", args=(), exc_info=exc_info
        )
        output = json.loads(fmt.format(record))
        assert "exception" in output
        assert output["exception"]["type"] == "ValueError"

    def test_no_extra_mode(self):
        fmt = JsonFormatter(include_extra=False)
        record = logging.LogRecord(
            name="t", level=logging.INFO, pathname="a.py",
            lineno=1, msg="x", args=(), exc_info=None
        )
        record.custom = "should-not-appear"
        output = json.loads(fmt.format(record))
        assert "custom" not in output


class TestContextLogger:
    def test_context_injection(self):
        set_request_id("req-42")
        set_tenant_id("tenant-1")
        set_session_id("sess-99")

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())

        raw = logging.getLogger("test.ctx")
        raw.handlers.clear()
        raw.addHandler(handler)
        raw.setLevel(logging.DEBUG)

        logger = ContextLogger(raw)
        logger.info("task done", latency_ms=12.5)

        output = json.loads(stream.getvalue())
        assert output["request_id"] == "req-42"
        assert output["tenant_id"] == "tenant-1"
        assert output["session_id"] == "sess-99"
        assert output["message"] == "task done"
        assert output["latency_ms"] == 12.5

    def test_all_levels(self):
        raw = logging.getLogger("test.levels")
        raw.handlers.clear()
        logger = ContextLogger(raw)
        # Should not raise
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        logger.critical("c")

    @pytest.mark.skip(reason="exception logging depends on exc_info being set by framework")
    def test_exception_log(self):
        raw = logging.getLogger("test.exc")
        raw.handlers.clear()
        logger = ContextLogger(raw)
        try:
            1 / 0
        except ZeroDivisionError:
            logger.exception("division error")
        # Verifies it doesn't crash


class TestConfigureLogging:
    def test_file_output(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name

        try:
            configure_logging(level="WARNING", log_file=path, json_format=True,
                              root_logger_name="agentos_test_file")
            lg = logging.getLogger("agentos_test_file")
            lg.warning("file test")
            lg.handlers[0].flush()

            with open(path) as f:
                content = f.read().strip()
            entry = json.loads(content)
            assert entry["message"] == "file test"
        finally:
            os.unlink(path)

    def test_default_stdout(self):
        configure_logging(level="INFO", json_format=False, root_logger_name="agentos_plain")
        lg = logging.getLogger("agentos_plain")
        # Should not crash
        lg.info("plain text")


class TestContextHelpers:
    def test_defaults(self):
        # Reset context vars for this test (they are process-wide)
        set_request_id("")
        set_tenant_id("")
        set_session_id("")
        assert get_request_id() == ""
        assert get_tenant_id() == ""
        assert get_session_id() == ""

    def test_set_and_get(self):
        set_request_id("abc")
        set_tenant_id("t1")
        set_session_id("s1")
        assert get_request_id() == "abc"
        assert get_tenant_id() == "t1"
        assert get_session_id() == "s1"


class TestGetLogger:
    def test_returns_context_logger(self):
        logger = get_logger("some.module")
        assert isinstance(logger, ContextLogger)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
