"""Tests for agentos.log module."""

import json
import logging
import sys
from unittest.mock import MagicMock

from agentos.log import (
    JSONFormatter,
    TraceContext,
    _ExtraAdapter,
    audit_log,
    get_logger,
    setup_structured_logging,
)


class TestTraceContext:
    def test_default_init(self):
        tc = TraceContext()
        assert isinstance(tc.trace_id, str)
        assert len(tc.trace_id) == 16
        assert isinstance(tc.span_id, str)
        assert len(tc.span_id) == 8

    def test_custom_ids(self):
        tc = TraceContext(trace_id="abc", span_id="xyz")
        assert tc.trace_id == "abc"
        assert tc.span_id == "xyz"

    def test_uniqueness(self):
        ids = {TraceContext().trace_id for _ in range(50)}
        assert len(ids) == 50


class TestJSONFormatter:
    def test_basic_format(self):
        fmt = JSONFormatter()
        record = logging.LogRecord("test", logging.INFO, "t.py", 10, "hello", (), None)
        out = json.loads(fmt.format(record))
        assert out["level"] == "INFO"
        assert out["logger"] == "test"
        assert out["message"] == "hello"
        assert "pid" in out

    def test_trace_context_in_output(self):
        tc = TraceContext(trace_id="aaaa", span_id="bbbb")
        fmt = JSONFormatter(trace_ctx=tc)
        record = logging.LogRecord("test", logging.INFO, "t.py", 10, "x", (), None)
        out = json.loads(fmt.format(record))
        assert out["trace_id"] == "aaaa"
        assert out["span_id"] == "bbbb"

    def test_exc_info(self):
        fmt = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                "test", logging.ERROR, "t.py", 10, "fail", (), sys.exc_info()
            )
        out = json.loads(fmt.format(record))
        assert "exc_info" in out
        assert "ValueError" in out["exc_info"]

    def test_structured_extra(self):
        fmt = JSONFormatter()
        record = logging.LogRecord("test", logging.INFO, "t.py", 10, "extra", (), None)
        record._structured_extra = {"user": 42}
        out = json.loads(fmt.format(record))
        assert out["user"] == 42

    def test_no_extra_leak(self):
        fmt = JSONFormatter()
        record = logging.LogRecord("test", logging.INFO, "t.py", 10, "clean", (), None)
        out = json.loads(fmt.format(record))
        assert "user" not in out


class TestExtraAdapter:
    def test_process_merges_structured_extra(self):
        base = logging.getLogger("test_adapter")
        adapter = _ExtraAdapter(base)
        msg, kwargs = adapter.process("hello", {"structured_extra": {"k": "v"}})
        assert msg == "hello"
        assert kwargs["extra"]["_structured_extra"] == {"k": "v"}


class TestAuditLog:
    def test_emits_info_with_details(self):
        logger = MagicMock()
        audit_log(logger, "user.login", "u1", "success", {"ip": "1.2.3.4"})
        logger.info.assert_called_once()
        args = logger.info.call_args
        assert "AUDIT" in str(args)
        assert "user.login" in str(args)

    def test_default_details(self):
        logger = MagicMock()
        audit_log(logger, "config", "admin", "ok")
        logger.info.assert_called_once()


class TestSetupStructuredLogging:
    def test_returns_configured_logger(self):
        logger = setup_structured_logging("test_log", level=logging.DEBUG)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_log"
        assert logger.level == logging.DEBUG

    def test_idempotent_no_duplicate_handlers(self):
        name = "test_idem"
        l1 = setup_structured_logging(name)
        h1 = len(l1.handlers)
        l2 = setup_structured_logging(name)
        assert len(l2.handlers) == h1


class TestGetLogger:
    def test_returns_logging_logger(self):
        logger = get_logger("test_mod")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_mod"
