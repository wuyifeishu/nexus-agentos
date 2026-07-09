"""Tests for agentos.errors module."""

import pytest

from agentos.errors import (
    CATEGORY_HINTS,
    ErrorCategory,
    ErrorContext,
    ErrorFormatter,
    HumanError,
    format_error,
    friendly_error,
)


class TestErrorCategory:
    def test_11_categories(self):
        assert len(ErrorCategory) == 11

    def test_all_auto_values(self):
        for cat in ErrorCategory:
            assert isinstance(cat.value, int)

    def test_unique_values(self):
        vals = [c.value for c in ErrorCategory]
        assert len(vals) == len(set(vals))

    def test_category_hints_coverage(self):
        for cat in ErrorCategory:
            assert cat in CATEGORY_HINTS


class TestErrorContext:
    def test_default_instantiation(self):
        ctx = ErrorContext()
        assert ctx.trace_id == ""
        assert ctx.category == ErrorCategory.UNKNOWN
        assert ctx.message == ""
        assert ctx.suggestion == ""
        assert ctx.detail == ""
        assert ctx.recovery_actions == []

    def test_full_instantiation(self):
        ctx = ErrorContext(
            trace_id="t1",
            category=ErrorCategory.NETWORK,
            message="fail",
            suggestion="retry",
            detail="timeout",
            recovery_actions=["action1", "action2"],
        )
        assert ctx.trace_id == "t1"
        assert ctx.category == ErrorCategory.NETWORK
        assert ctx.message == "fail"
        assert ctx.suggestion == "retry"
        assert ctx.detail == "timeout"
        assert ctx.recovery_actions == ["action1", "action2"]

    def test_is_dataclass(self):
        ctx = ErrorContext()
        assert hasattr(ctx, "__dataclass_fields__")


class TestHumanError:
    def test_raise_and_catch(self):
        inner = ValueError("inner err")
        ctx = ErrorContext(message="friendly msg")
        with pytest.raises(HumanError) as exc_info:
            raise HumanError(inner, ctx)
        assert exc_info.value.original is inner
        assert exc_info.value.context is ctx

    def test_str_uses_context_message(self):
        inner = RuntimeError("raw")
        ctx = ErrorContext(message="user-friendly")
        e = HumanError(inner, ctx)
        assert str(e) == "user-friendly"

    def test_str_fallback_to_original(self):
        inner = RuntimeError("raw error")
        ctx = ErrorContext(message="")
        e = HumanError(inner, ctx)
        assert str(e) == "raw error"


class TestErrorFormatterCategorize:
    def test_timeout(self):
        assert ErrorFormatter.categorize(TimeoutError("timed out")) == ErrorCategory.TIMEOUT

    def test_rate_limit(self):
        assert ErrorFormatter.categorize(Exception("too many requests 429")) == ErrorCategory.RATE_LIMIT

    def test_auth(self):
        assert ErrorFormatter.categorize(Exception("unauthorized 401")) == ErrorCategory.AUTH

    def test_network(self):
        assert ErrorFormatter.categorize(ConnectionError("connection refused")) == ErrorCategory.NETWORK

    def test_validation(self):
        assert ErrorFormatter.categorize(ValueError("invalid input")) == ErrorCategory.VALIDATION

    def test_resource(self):
        assert ErrorFormatter.categorize(Exception("disk quota exceeded")) == ErrorCategory.RESOURCE

    def test_config(self):
        assert ErrorFormatter.categorize(Exception("config.yaml missing")) == ErrorCategory.CONFIG

    def test_unknown_fallback(self):
        assert ErrorFormatter.categorize(Exception("???")) == ErrorCategory.UNKNOWN


class TestErrorFormatterExtractRecovery:
    def test_returns_list(self):
        actions = ErrorFormatter.extract_recovery(Exception("x"), ErrorCategory.NETWORK)
        assert isinstance(actions, list)

    def test_retry_for_network(self):
        actions = ErrorFormatter.extract_recovery(Exception("x"), ErrorCategory.NETWORK)
        assert any("重试" in a for a in actions)

    def test_api_key_hint(self):
        actions = ErrorFormatter.extract_recovery(Exception("api key invalid"), ErrorCategory.AUTH)
        assert any("api_key" in a for a in actions)

    def test_model_not_found_hint(self):
        actions = ErrorFormatter.extract_recovery(
            Exception("model not found"), ErrorCategory.MODEL
        )
        assert any("model_name" in a or "拼写" in a for a in actions)


class TestErrorFormatterFormat:
    def test_returns_error_context(self):
        ctx = ErrorFormatter.format(ValueError("invalid input"), "tid-1")
        assert isinstance(ctx, ErrorContext)
        assert ctx.trace_id == "tid-1"
        assert ctx.category == ErrorCategory.VALIDATION

    def test_includes_suggestion(self):
        ctx = ErrorFormatter.format(Exception("timeout"), "t2")
        assert ctx.suggestion != ""


class TestFormatError:
    def test_returns_string(self):
        msg = format_error(ValueError("invalid input"), "trace-x")
        assert isinstance(msg, str)
        assert "VALIDATION" in msg

    def test_includes_category(self):
        msg = format_error(ConnectionError("refused"))
        assert "NETWORK" in msg


class TestFriendlyError:
    def test_passes_through_success(self):
        @friendly_error
        def ok():
            return 42

        assert ok() == 42

    def test_prints_and_reraises(self):
        @friendly_error
        def fail():
            raise ValueError("bad")

        with pytest.raises(ValueError):
            fail()
