"""Tests for agentos.core.retry — Retry, RetryConfig, delay functions."""

import pytest

from agentos.core.retry import (
    JitterStrategy,
    Retry,
    RetryConfig,
    RetryPolicies,
    RetryResult,
    SyncRetry,
    _calc_jitter,
    exponential_delay,
    fibonacci_delay,
    fixed_delay,
)

# ============================================================================
# JitterStrategy
# ============================================================================

class TestJitterStrategy:
    def test_enum_values(self):
        assert JitterStrategy.NONE == "none"
        assert JitterStrategy.FULL == "full"
        assert JitterStrategy.DECORRELATED == "decorrelated"
        assert JitterStrategy.EQUAL == "equal"


# ============================================================================
# RetryConfig
# ============================================================================

class TestRetryConfig:
    def test_defaults(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.base_delay == 1.0
        assert cfg.max_delay == 60.0
        assert cfg.multiplier == 2.0
        assert cfg.jitter == JitterStrategy.DECORRELATED
        assert cfg.retryable_exceptions == (Exception,)
        assert cfg.on_retry is None

    def test_custom(self):
        cfg = RetryConfig(
            max_retries=5,
            base_delay=0.5,
            max_delay=10.0,
            multiplier=3.0,
            jitter=JitterStrategy.FULL,
            retryable_exceptions=(ValueError, TypeError),
        )
        assert cfg.max_retries == 5
        assert cfg.multiplier == 3.0
        assert cfg.retryable_exceptions == (ValueError, TypeError)


# ============================================================================
# _calc_jitter
# ============================================================================

class TestCalcJitter:
    def test_none(self):
        result = _calc_jitter(2.0, JitterStrategy.NONE)
        assert result == 2.0

    def test_full(self):
        result = _calc_jitter(2.0, JitterStrategy.FULL)
        assert 0.0 <= result <= 2.0

    def test_decorrelated(self):
        result = _calc_jitter(2.0, JitterStrategy.DECORRELATED)
        assert 0.0 <= result <= 2.0

    def test_equal(self):
        result = _calc_jitter(2.0, JitterStrategy.EQUAL)
        assert 1.0 <= result <= 2.0


# ============================================================================
# Delay functions
# ============================================================================

class TestDelayFunctions:
    def test_exponential_delay_basic(self):
        cfg = RetryConfig(base_delay=1.0, multiplier=2.0, max_delay=60, jitter=JitterStrategy.NONE)
        d1 = exponential_delay(1, cfg)
        d2 = exponential_delay(2, cfg)
        assert d1 == 1.0
        assert d2 == 2.0

    def test_exponential_delay_cap(self):
        cfg = RetryConfig(base_delay=50, max_delay=60, jitter=JitterStrategy.NONE)
        assert exponential_delay(1, cfg) == 50.0
        # attempt 2: 50*2 = 100, capped to 60
        assert exponential_delay(2, cfg) == 60.0

    def test_fibonacci_delay(self):
        cfg = RetryConfig(base_delay=1.0, max_delay=60, jitter=JitterStrategy.NONE)
        # fib: 1,1,2,3,5,8...
        assert fibonacci_delay(1, cfg) == 1.0  # fib(1)=1 * 1.0
        assert fibonacci_delay(2, cfg) == 1.0  # fib(2)=1 * 1.0
        assert fibonacci_delay(3, cfg) == 2.0  # fib(3)=2 * 1.0

    def test_fibonacci_delay_cap(self):
        cfg = RetryConfig(base_delay=100, max_delay=50, jitter=JitterStrategy.NONE)
        assert fibonacci_delay(1, cfg) == 50.0

    def test_fixed_delay(self):
        cfg = RetryConfig(base_delay=2.0, max_delay=60)
        assert fixed_delay(1, cfg) == 2.0
        assert fixed_delay(10, cfg) == 2.0

    def test_fixed_delay_cap(self):
        cfg = RetryConfig(base_delay=100, max_delay=50)
        assert fixed_delay(1, cfg) == 50.0


# ============================================================================
# RetryResult
# ============================================================================

class TestRetryResult:
    def test_success(self):
        r = RetryResult(attempts=1, success=True, total_delay=0.5)
        assert r.success is True
        assert r.last_exception is None
        assert r.total_delay == 0.5

    def test_failure(self):
        exc = ValueError("x")
        r = RetryResult(attempts=3, success=False, last_exception=exc, total_delay=2.0)
        assert r.success is False
        assert r.last_exception is exc


# ============================================================================
# Retry — execute
# ============================================================================

class TestRetryExecute:
    @pytest.mark.asyncio
    async def test_first_attempt_success(self):
        cfg = RetryConfig(max_retries=3, base_delay=0.01)
        retry = Retry(cfg)

        async def ok():
            return "success"

        result = await retry.execute(ok)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        cfg = RetryConfig(max_retries=3, base_delay=0.01)
        retry = Retry(cfg)
        call_count = []

        async def flaky():
            call_count.append(1)
            if len(call_count) < 2:
                raise ValueError("fail")
            return "ok"

        result = await retry.execute(flaky)
        assert result == "ok"
        assert len(call_count) == 2

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        cfg = RetryConfig(max_retries=2, base_delay=0.01)
        retry = Retry(cfg)

        async def always_fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await retry.execute(always_fail)

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        cfg = RetryConfig(max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        retry = Retry(cfg)

        async def fail_with_type():
            raise TypeError("not retryable")

        with pytest.raises(TypeError):
            await retry.execute(fail_with_type)

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        callbacks = []

        def on_retry(attempt, exc, delay):
            callbacks.append((attempt, delay))

        cfg = RetryConfig(max_retries=2, base_delay=0.01, on_retry=on_retry)
        retry = Retry(cfg)

        async def flaky():
            if len(callbacks) < 2:
                raise ValueError("x")
            return "done"

        result = await retry.execute(flaky)
        assert result == "done"
        assert len(callbacks) == 2

    @pytest.mark.asyncio
    async def test_args_kwargs_passed(self):
        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))

        async def fn(a, b, c=None):
            return a + b + (c or 0)

        result = await retry.execute(fn, 1, 2, c=3)
        assert result == 6


# ============================================================================
# Retry — execute_with_result
# ============================================================================

class TestRetryExecuteWithResult:
    @pytest.mark.asyncio
    async def test_success_result(self):
        retry = Retry(RetryConfig(max_retries=3, base_delay=0.01))

        async def ok():
            return 42

        result = await retry.execute_with_result(ok)
        assert isinstance(result, RetryResult)
        assert result.success is True
        assert result.attempts == 1
        assert len(result.attempt_history) == 1

    @pytest.mark.asyncio
    async def test_failure_result(self):
        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))

        async def fail():
            raise ValueError("x")

        result = await retry.execute_with_result(fail)
        assert result.success is False
        assert result.attempts == 3  # initial + 2 retries
        assert isinstance(result.last_exception, ValueError)

    @pytest.mark.asyncio
    async def test_retry_history(self):
        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))

        async def flaky():
            if not hasattr(flaky, "count"):
                flaky.count = 0
            flaky.count += 1
            if flaky.count < 2:
                raise ValueError("fail")
            return "ok"

        result = await retry.execute_with_result(flaky)
        assert result.success
        assert len(result.attempt_history) >= 1


# ============================================================================
# Retry — with_retry decorator
# ============================================================================

class TestRetryDecorator:
    @pytest.mark.asyncio
    async def test_decorator_success(self):
        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))

        @retry.with_retry
        async def api():
            return "ok"

        assert await api() == "ok"

    @pytest.mark.asyncio
    async def test_decorator_preserves_name(self):
        retry = Retry(RetryConfig(max_retries=1, base_delay=0.01))

        @retry.with_retry
        async def my_func():
            return 1

        assert my_func.__name__ == "my_func"


# ============================================================================
# RetryPolicies
# ============================================================================

class TestRetryPolicies:
    def test_fast(self):
        r = RetryPolicies.fast()
        assert r.config.max_retries == 3
        assert r.config.base_delay == 0.1
        assert r.config.max_delay == 1.0

    def test_standard(self):
        r = RetryPolicies.standard()
        assert r.config.max_retries == 5
        assert r.config.base_delay == 0.5
        assert r.config.max_delay == 30.0

    def test_persistent(self):
        r = RetryPolicies.persistent()
        assert r.config.max_retries == 10
        assert r.config.base_delay == 1.0
        assert r.config.max_delay == 120.0

    def test_immediate(self):
        r = RetryPolicies.immediate()
        assert r.config.max_retries == 2
        assert r.config.base_delay == 0.0
        assert r.config.jitter == JitterStrategy.NONE

    def test_gentle(self):
        r = RetryPolicies.gentle()
        assert r.config.max_retries == 5
        assert r.config.jitter == JitterStrategy.FULL


# ============================================================================
# SyncRetry
# ============================================================================

class TestSyncRetry:
    def test_sync_success(self):
        retry = SyncRetry(RetryConfig(max_retries=2, base_delay=0.01))

        def ok():
            return "sync_ok"

        result = retry.execute(ok)
        assert result == "sync_ok"

    def test_sync_failure(self):
        retry = SyncRetry(RetryConfig(max_retries=2, base_delay=0.01))

        def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            retry.execute(fail)

    def test_sync_decorator(self):
        retry = SyncRetry(RetryConfig(max_retries=2, base_delay=0.01))

        @retry.with_retry
        def fn():
            return "wrapped"

        assert fn() == "wrapped"
        assert fn.__name__ == "fn"


# ============================================================================
# Edge cases
# ============================================================================

class TestRetryEdgeCases:
    @pytest.mark.asyncio
    async def test_zero_max_retries_success(self):
        retry = Retry(RetryConfig(max_retries=0, base_delay=0.01))

        async def ok():
            return "ok"

        assert await retry.execute(ok) == "ok"

    @pytest.mark.asyncio
    async def test_zero_max_retries_fail(self):
        retry = Retry(RetryConfig(max_retries=0, base_delay=0.01))

        async def fail():
            raise ValueError("x")

        with pytest.raises(ValueError):
            await retry.execute(fail)
