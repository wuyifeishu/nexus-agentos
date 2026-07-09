"""Tests for agentos.core.retry — production-grade retry with backoff + jitter."""

from __future__ import annotations

import pytest

from agentos.core.retry import (
    JitterStrategy,
    Retry,
    RetryConfig,
    RetryPolicies,
    RetryResult,
    SyncRetry,
    exponential_delay,
    fibonacci_delay,
    fixed_delay,
)

# ============================================================================
# Delay Functions
# ============================================================================

class TestDelayFunctions:
    def test_fixed_delay(self):
        config = RetryConfig(base_delay=2.0, max_delay=60.0)
        delay = fixed_delay(1, config)
        assert delay == 2.0

    def test_fixed_delay_capped(self):
        config = RetryConfig(base_delay=100.0, max_delay=60.0)
        delay = fixed_delay(1, config)
        assert delay == 60.0

    def test_exponential_delay_ramps_up(self):
        config = RetryConfig(base_delay=1.0, max_delay=100.0, multiplier=2.0, jitter=JitterStrategy.NONE)
        d1 = exponential_delay(1, config)
        d2 = exponential_delay(2, config)
        d3 = exponential_delay(3, config)
        assert d1 == 1.0
        assert d2 == 2.0
        assert d3 == 4.0

    def test_exponential_delay_capped(self):
        config = RetryConfig(base_delay=1.0, max_delay=2.0, multiplier=2.0, jitter=JitterStrategy.NONE)
        d4 = exponential_delay(4, config)  # 1*2^3 = 8 → cap at 2
        assert d4 == 2.0

    def test_exponential_delay_with_jitter(self):
        config = RetryConfig(base_delay=10.0, max_delay=100.0, multiplier=2.0, jitter=JitterStrategy.FULL)
        delay = exponential_delay(1, config)
        assert 0 <= delay <= 10.0

    def test_fibonacci_delay(self):
        config = RetryConfig(base_delay=1.0, max_delay=100.0, jitter=JitterStrategy.NONE)
        # attempt 1: fib(1)=1, attempt 2: fib(2)=1, attempt 3: fib(3)=2, attempt 4: fib(4)=3
        assert fibonacci_delay(1, config) == 1.0
        assert fibonacci_delay(2, config) == 1.0
        assert fibonacci_delay(3, config) == 2.0
        assert fibonacci_delay(4, config) == 3.0


# ============================================================================
# RetryConfig
# ============================================================================

class TestRetryConfig:
    def test_defaults(self):
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.multiplier == 2.0
        assert config.jitter == JitterStrategy.DECORRELATED


# ============================================================================
# Retry Execution (async)
# ============================================================================

class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        call_count = 0

        async def ok():
            nonlocal call_count
            call_count += 1
            return "done"

        retry = Retry(RetryConfig(max_retries=2))
        result = await retry.execute(ok)
        assert result == "done"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_and_succeed(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return "finally"

        retry = Retry(RetryConfig(max_retries=5, base_delay=0.01, jitter=JitterStrategy.NONE))
        result = await retry.execute(flaky)
        assert result == "finally"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        call_count = 0

        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("persistent failure")

        retry = Retry(RetryConfig(max_retries=3, base_delay=0.01, jitter=JitterStrategy.NONE))
        with pytest.raises(RuntimeError, match="persistent failure"):
            await retry.execute(always_fail)
        assert call_count == 4  # initial + 3 retries

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        call_count = 0

        async def fail_keyboard():
            nonlocal call_count
            call_count += 1
            raise KeyboardInterrupt()

        retry = Retry(RetryConfig(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
        ))
        with pytest.raises(KeyboardInterrupt):
            await retry.execute(fail_keyboard)
        assert call_count == 1  # No retry

    @pytest.mark.asyncio
    async def test_execute_with_result_success(self):
        async def ok():
            return 42

        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))
        result: RetryResult = await retry.execute_with_result(ok)
        assert result.success is True
        assert result.attempts == 1
        assert result.last_exception is None

    @pytest.mark.asyncio
    async def test_execute_with_result_failure(self):
        async def fail():
            raise ValueError("bad")

        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01, jitter=JitterStrategy.NONE))
        result: RetryResult = await retry.execute_with_result(fail)
        assert result.success is False
        assert result.attempts == 3  # 1 initial + 2 retries
        assert isinstance(result.last_exception, ValueError)
        assert len(result.attempt_history) == 3

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        events = []

        def on_retry(attempt, exc, delay):
            events.append((attempt, type(exc).__name__, delay))

        retry = Retry(RetryConfig(
            max_retries=3,
            base_delay=0.01,
            jitter=JitterStrategy.NONE,
            on_retry=on_retry,
        ))

        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("oops")
            return "ok"

        await retry.execute(flaky)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_with_retry_decorator(self):
        retry = Retry(RetryConfig(max_retries=3, base_delay=0.01))

        call_count = 0

        @retry.with_retry
        async def decorated():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "ok"

        result = await decorated()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_with_args(self):
        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))

        async def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}"

        result = await retry.execute(greet, "World", greeting="Hi")
        assert result == "Hi, World"

    @pytest.mark.asyncio
    async def test_max_retries_zero(self):
        call_count = 0

        async def fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        retry = Retry(RetryConfig(max_retries=0, base_delay=0.01))
        with pytest.raises(ValueError):
            await retry.execute(fail)
        assert call_count == 1


# ============================================================================
# RetryPolicies
# ============================================================================

class TestRetryPolicies:
    def test_fast(self):
        r = RetryPolicies.fast()
        assert r.config.max_retries == 3
        assert r.config.base_delay == 0.1

    def test_standard(self):
        r = RetryPolicies.standard()
        assert r.config.max_retries == 5
        assert r.config.base_delay == 0.5

    def test_persistent(self):
        r = RetryPolicies.persistent()
        assert r.config.max_retries == 10
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

    @pytest.mark.asyncio
    async def test_fast_policy_works(self):
        r = RetryPolicies.fast()
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "ok"

        result = await r.execute(flaky)
        assert result == "ok"
        assert call_count == 2


# ============================================================================
# SyncRetry
# ============================================================================

class TestSyncRetry:
    def test_success(self):
        sr = SyncRetry(RetryConfig(max_retries=2, base_delay=0.01))

        def ok():
            return "done"

        result = sr.execute(ok)
        assert result == "done"

    def test_retry_and_succeed(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "ok"

        sr = SyncRetry(RetryConfig(max_retries=3, base_delay=0.01, jitter=JitterStrategy.NONE))
        result = sr.execute(flaky)
        assert result == "ok"
        assert call_count == 2

    def test_all_retries_exhausted(self):
        def always_fail():
            raise RuntimeError("bad")

        sr = SyncRetry(RetryConfig(max_retries=2, base_delay=0.01))
        with pytest.raises(RuntimeError):
            sr.execute(always_fail)

    def test_with_retry_decorator(self):
        sr = SyncRetry(RetryConfig(max_retries=2, base_delay=0.01))

        call_count = 0

        @sr.with_retry
        def decorated():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "decorated"

        result = decorated()
        assert result == "decorated"
        assert call_count == 2


# ============================================================================
# RetryResult
# ============================================================================

class TestRetryResult:
    def test_defaults(self):
        r = RetryResult(attempts=1, success=True)
        assert r.attempts == 1
        assert r.success is True
        assert r.last_exception is None
        assert r.total_delay == 0.0

    def test_with_exception(self):
        exc = ValueError("test")
        r = RetryResult(attempts=3, success=False, last_exception=exc, total_delay=5.0)
        assert r.success is False
        assert r.last_exception is exc
        assert r.total_delay == 5.0
