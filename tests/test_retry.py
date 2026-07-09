"""Tests for agentos.core.retry — 28 test cases."""

import pytest

from agentos.core.retry import (
    JitterStrategy,
    Retry,
    RetryConfig,
    RetryPolicies,
    SyncRetry,
    exponential_delay,
    fibonacci_delay,
    fixed_delay,
)

# ============================================================================
# Delay functions
# ============================================================================

class TestDelayFunctions:
    """Test delay calculation functions."""

    def test_exponential_delay_attempt_1(self):
        config = RetryConfig(base_delay=1.0, multiplier=2.0, max_delay=60.0, jitter=JitterStrategy.NONE)
        delay = exponential_delay(1, config)
        assert delay == 1.0

    def test_exponential_delay_attempt_3(self):
        config = RetryConfig(base_delay=1.0, multiplier=2.0, max_delay=60.0, jitter=JitterStrategy.NONE)
        delay = exponential_delay(3, config)
        assert delay == 4.0  # 1 * 2^2

    def test_exponential_delay_capped(self):
        config = RetryConfig(base_delay=10.0, multiplier=2.0, max_delay=5.0, jitter=JitterStrategy.NONE)
        delay = exponential_delay(3, config)
        assert delay == 5.0  # capped

    def test_fibonacci_delay_sequence(self):
        config = RetryConfig(base_delay=1.0, max_delay=60.0, jitter=JitterStrategy.NONE)
        # fib: 1,1,2,3,5,8
        assert fibonacci_delay(1, config) == 1.0
        assert fibonacci_delay(2, config) == 1.0
        assert fibonacci_delay(3, config) == 2.0
        assert fibonacci_delay(4, config) == 3.0
        assert fibonacci_delay(5, config) == 5.0

    def test_fixed_delay(self):
        config = RetryConfig(base_delay=2.5, max_delay=60.0)
        assert fixed_delay(1, config) == 2.5
        assert fixed_delay(5, config) == 2.5

    def test_jitter_decorrelated_in_range(self):
        config = RetryConfig(base_delay=1.0, multiplier=2.0, max_delay=60.0, jitter=JitterStrategy.DECORRELATED)
        for _ in range(20):
            delay = exponential_delay(1, config)
            assert 0 <= delay <= 1.0

    def test_jitter_full_in_range(self):
        config = RetryConfig(base_delay=2.0, multiplier=2.0, max_delay=60.0, jitter=JitterStrategy.FULL)
        for _ in range(20):
            delay = exponential_delay(1, config)
            assert 0 <= delay <= 2.0


# ============================================================================
# Retry execution
# ============================================================================

class TestRetryExecute:
    """Test Retry.execute behavior."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        retry = Retry(RetryConfig(max_retries=3, base_delay=0.01))
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry.execute(flaky)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        retry = Retry(RetryConfig(max_retries=3, base_delay=0.01))
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = await retry.execute(flaky)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausted_retries(self):
        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))

        async def always_fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await retry.execute(always_fail)

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        retry = Retry(RetryConfig(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
        ))

        async def raises_type_error():
            raise TypeError("not retryable")

        with pytest.raises(TypeError):
            await retry.execute(raises_type_error)

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        callbacks = []

        def on_retry(attempt, exc, delay):
            callbacks.append((attempt, type(exc).__name__, delay))

        retry = Retry(RetryConfig(
            max_retries=2,
            base_delay=0.01,
            on_retry=on_retry,
        ))

        async def fails_twice():
            if len(callbacks) < 2:
                raise ConnectionError("timeout")
            return "done"

        result = await retry.execute(fails_twice)
        assert result == "done"
        assert len(callbacks) == 2
        assert callbacks[0][1] == "ConnectionError"

    @pytest.mark.asyncio
    async def test_on_retry_callback_failure_no_interrupt(self):
        def bad_callback(attempt, exc, delay):
            raise RuntimeError("callback error")

        retry = Retry(RetryConfig(
            max_retries=2,
            base_delay=0.01,
            on_retry=bad_callback,
        ))

        async def fails_once():
            if not hasattr(fails_once, "called"):
                fails_once.called = True
                raise ValueError("fail")
            return "ok"

        result = await retry.execute(fails_once)
        assert result == "ok"


# ============================================================================
# Retry execute_with_result
# ============================================================================

class TestRetryWithResult:
    """Test Retry.execute_with_result."""

    @pytest.mark.asyncio
    async def test_success_result(self):
        retry = Retry(RetryConfig(max_retries=3, base_delay=0.01))

        async def works():
            return "data"

        result = await retry.execute_with_result(works)
        assert result.success is True
        assert result.attempts == 1
        assert result.last_exception is None
        assert result.total_delay == 0.0

    @pytest.mark.asyncio
    async def test_failure_result(self):
        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))

        async def always_fails():
            raise RuntimeError("dead")

        result = await retry.execute_with_result(always_fails)
        assert result.success is False
        assert result.attempts == 3  # 1 initial + 2 retries
        assert isinstance(result.last_exception, RuntimeError)
        assert result.total_delay > 0

    @pytest.mark.asyncio
    async def test_result_history(self):
        retry = Retry(RetryConfig(max_retries=2, base_delay=0.01))

        async def fails_twice():
            if not hasattr(fails_twice, "count"):
                fails_twice.count = 0
            fails_twice.count += 1
            if fails_twice.count < 3:
                raise ValueError(f"fail {fails_twice.count}")
            return "ok"

        result = await retry.execute_with_result(fails_twice)
        assert result.success is True
        assert len(result.attempt_history) == 3

        # First two should have exceptions
        assert result.attempt_history[0][2] is not None
        assert result.attempt_history[1][2] is not None
        # Last should be None (success)
        assert result.attempt_history[2][2] is None


# ============================================================================
# Decorator
# ============================================================================

class TestRetryDecorator:
    """Test @retry.with_retry decorator."""

    @pytest.mark.asyncio
    async def test_decorator_success(self):
        retry = Retry(RetryConfig(max_retries=3, base_delay=0.01))

        @retry.with_retry
        async def fetch():
            return "data"

        result = await fetch()
        assert result == "data"

    @pytest.mark.asyncio
    async def test_decorator_preserves_name(self):
        retry = Retry(RetryConfig(max_retries=1, base_delay=0.01))

        @retry.with_retry
        async def my_function():
            pass

        assert my_function.__name__ == "my_function"


# ============================================================================
# RetryPolicies
# ============================================================================

class TestRetryPolicies:
    """Test pre-built retry policies."""

    def test_fast_policy(self):
        r = RetryPolicies.fast()
        assert r.config.max_retries == 3
        assert r.config.base_delay == 0.1

    def test_standard_policy(self):
        r = RetryPolicies.standard()
        assert r.config.max_retries == 5
        assert r.config.base_delay == 0.5

    def test_persistent_policy(self):
        r = RetryPolicies.persistent()
        assert r.config.max_retries == 10
        assert r.config.max_delay == 120.0

    def test_immediate_policy(self):
        r = RetryPolicies.immediate()
        assert r.config.max_retries == 2
        assert r.config.base_delay == 0.0
        assert r.config.jitter == JitterStrategy.NONE

    def test_gentle_policy(self):
        r = RetryPolicies.gentle()
        assert r.config.max_retries == 5
        assert r.delay_fn == fibonacci_delay

    @pytest.mark.asyncio
    async def test_immediate_policy_no_delay(self):
        r = RetryPolicies.immediate()
        call_count = 0

        async def fails_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = await r.execute(fails_twice)
        assert result == "ok"
        assert call_count == 3


# ============================================================================
# SyncRetry
# ============================================================================

class TestSyncRetry:
    """Test SyncRetry for synchronous contexts."""

    def test_sync_retry_success(self):
        retry = SyncRetry(RetryConfig(max_retries=3, base_delay=0.01))
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "sync_ok"

        result = retry.execute(flaky)
        assert result == "sync_ok"

    def test_sync_retry_exhausted(self):
        retry = SyncRetry(RetryConfig(max_retries=1, base_delay=0.01))

        def always_fails():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            retry.execute(always_fails)
