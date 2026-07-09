"""Tests for agentos.core.circuit_breaker — CircuitBreaker, CircuitRegistry, decorator."""

import asyncio

import pytest

from agentos.core.circuit_breaker import (
    CircuitBreaker,
    CircuitConfig,
    CircuitOpenError,
    CircuitRegistry,
    CircuitState,
    CircuitStats,
    circuit_breaker,
    default_registry,
)

# ============================================================================
# CircuitState
# ============================================================================

class TestCircuitState:
    def test_enum_values(self):
        assert CircuitState.CLOSED == "closed"
        assert CircuitState.OPEN == "open"
        assert CircuitState.HALF_OPEN == "half_open"


# ============================================================================
# CircuitConfig
# ============================================================================

class TestCircuitConfig:
    def test_defaults(self):
        cfg = CircuitConfig()
        assert cfg.failure_threshold == 5
        assert cfg.success_threshold == 2
        assert cfg.timeout_seconds == 60.0
        assert cfg.half_open_max_requests == 1
        assert cfg.excluded_exceptions == ()

    def test_custom(self):
        cfg = CircuitConfig(
            failure_threshold=3,
            success_threshold=1,
            timeout_seconds=10.0,
        )
        assert cfg.failure_threshold == 3
        assert cfg.timeout_seconds == 10.0


# ============================================================================
# CircuitStats
# ============================================================================

class TestCircuitStats:
    def test_defaults(self):
        s = CircuitStats()
        assert s.state == CircuitState.CLOSED
        assert s.failure_count == 0
        assert s.total_failures == 0

    def test_reset(self):
        s = CircuitStats()
        s.failure_count = 5
        s.success_count = 3
        s.half_open_requests = 2
        s.reset()
        assert s.failure_count == 0
        assert s.success_count == 0
        assert s.half_open_requests == 0


# ============================================================================
# CircuitBreaker — Basic
# ============================================================================

class TestCircuitBreakerBasic:
    def test_default_state(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.name == "test"

    def test_custom_config(self):
        cfg = CircuitConfig(failure_threshold=2)
        cb = CircuitBreaker(name="test", config=cfg)
        assert cb.config.failure_threshold == 2


# ============================================================================
# CircuitBreaker — Acquire / Release
# ============================================================================

class TestCircuitBreakerAcquire:
    @pytest.mark.asyncio
    async def test_closed_always_acquires(self):
        cb = CircuitBreaker(name="test")
        assert await cb.acquire() is True
        assert await cb.acquire() is True

    @pytest.mark.asyncio
    async def test_release_half_open(self):
        cb = CircuitBreaker(name="test")
        # Force half-open state for testing release
        cb.stats.state = CircuitState.HALF_OPEN
        cb.stats.half_open_requests = 1
        await cb.release()
        assert cb.stats.half_open_requests == 0

    @pytest.mark.asyncio
    async def test_release_floor_zero(self):
        cb = CircuitBreaker(name="test")
        cb.stats.state = CircuitState.HALF_OPEN
        cb.stats.half_open_requests = 0
        await cb.release()
        assert cb.stats.half_open_requests == 0


# ============================================================================
# CircuitBreaker — State transitions
# ============================================================================

class TestCircuitBreakerTransitions:
    @pytest.mark.asyncio
    async def test_success_keeps_closed(self):
        cb = CircuitBreaker(name="test")

        async def ok(): return "success"
        result = await cb.call(ok)
        assert result == "success"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_below_threshold(self):
        cb = CircuitBreaker(name="test", config=CircuitConfig(failure_threshold=3))

        async def fail():
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_trips_open(self):
        cb = CircuitBreaker(name="test", config=CircuitConfig(failure_threshold=2))

        async def fail():
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_rejects_requests(self):
        cb = CircuitBreaker(name="test", config=CircuitConfig(failure_threshold=1, timeout_seconds=60))

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.state == CircuitState.OPEN
        # Subsequent request should raise CircuitOpenError
        with pytest.raises(CircuitOpenError):
            await cb.call(lambda: "ok")

    @pytest.mark.asyncio
    async def test_half_open_probing(self):
        cb = CircuitBreaker(
            name="test",
            config=CircuitConfig(failure_threshold=1, timeout_seconds=0.01, success_threshold=1),
        )

        async def fail():
            raise ValueError("boom")

        # Trip open
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        # Wait for timeout to expire
        await asyncio.sleep(0.05)

        # Now should probe (half-open)
        async def ok():
            return "recovered"

        result = await cb.call(ok)
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(
            name="test",
            config=CircuitConfig(
                failure_threshold=1,
                timeout_seconds=0.01,
                success_threshold=1,
            ),
        )

        async def fail():
            raise ValueError("boom")

        # Trip open
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.05)

        # Probe fails → back to OPEN
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_count_in_closed(self):
        cb = CircuitBreaker(name="test", config=CircuitConfig(failure_threshold=3))

        async def fail():
            raise ValueError("boom")

        async def ok():
            return "ok"

        with pytest.raises(ValueError):
            await cb.call(fail)
        await cb.call(ok)
        # One failure then success should reset failure count
        assert cb.stats.failure_count == 0


# ============================================================================
# CircuitBreaker — Excluded exceptions
# ============================================================================

class TestCircuitBreakerExcluded:
    @pytest.mark.asyncio
    async def test_excluded_exception_does_not_count(self):
        cfg = CircuitConfig(failure_threshold=1, excluded_exceptions=(ValueError,))
        cb = CircuitBreaker(name="test", config=cfg)

        async def fail():
            raise ValueError("ignored")

        # This should NOT count toward failure threshold
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.CLOSED


# ============================================================================
# CircuitBreaker — Fallback
# ============================================================================

class TestCircuitBreakerFallback:
    @pytest.mark.asyncio
    async def test_fallback_used_when_open(self):
        cb = CircuitBreaker(
            name="test",
            config=CircuitConfig(failure_threshold=1, timeout_seconds=60),
        )

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.state == CircuitState.OPEN

        # Use fallback
        async def fallback_fn():
            return "fallback_value"

        result = await cb.call(lambda: "ok", fallback=fallback_fn)
        assert result == "fallback_value"


# ============================================================================
# CircuitBreaker — config reset behavior
# ============================================================================

class TestCircuitBreakerConfig:
    @pytest.mark.asyncio
    async def test_failure_threshold_one(self):
        cb = CircuitBreaker(name="test", config=CircuitConfig(failure_threshold=1))

        async def fail():
            raise ValueError("x")

        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN


# ============================================================================
# CircuitRegistry
# ============================================================================

class TestCircuitRegistry:
    @pytest.mark.asyncio
    async def test_get_or_create(self):
        reg = CircuitRegistry()
        cb1 = await reg.get_or_create("api")
        cb2 = await reg.get_or_create("api")
        assert cb1 is cb2

    @pytest.mark.asyncio
    async def test_get_or_create_different_names(self):
        reg = CircuitRegistry()
        cb1 = await reg.get_or_create("a")
        cb2 = await reg.get_or_create("b")
        assert cb1 is not cb2

    @pytest.mark.asyncio
    async def test_get_or_create_with_config(self):
        reg = CircuitRegistry()
        cfg = CircuitConfig(failure_threshold=10)
        cb = await reg.get_or_create("api", config=cfg)
        assert cb.config.failure_threshold == 10

    @pytest.mark.asyncio
    async def test_get_all_stats(self):
        reg = CircuitRegistry()
        await reg.get_or_create("a")
        await reg.get_or_create("b")
        stats = reg.get_all_stats()
        assert "a" in stats
        assert "b" in stats

    @pytest.mark.asyncio
    async def test_reset_all(self):
        reg = CircuitRegistry()
        cb = await reg.get_or_create("test")

        async def fail():
            raise ValueError("x")
        cb_cfg = CircuitConfig(failure_threshold=1, timeout_seconds=60)
        cb.config = cb_cfg
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        await reg.reset_all()
        # After reset, failure_count is 0 and state is CLOSED
        assert cb.stats.failure_count == 0

    @pytest.mark.asyncio
    async def test_force_open(self):
        reg = CircuitRegistry()
        cb = await reg.get_or_create("test")
        await reg.force_open("test")
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_force_closed(self):
        reg = CircuitRegistry()
        cb = await reg.get_or_create("test")
        cb.stats.state = CircuitState.OPEN
        await reg.force_closed("test")
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_force_open_missing(self):
        reg = CircuitRegistry()
        await reg.force_open("nonexistent")  # Should not raise


# ============================================================================
# Decorator
# ============================================================================

class TestCircuitBreakerDecorator:
    def test_decorator_creates_breaker(self):
        @circuit_breaker("llm_api", failure_threshold=3, timeout_seconds=30)
        async def call_llm(prompt: str) -> str:
            return f"response: {prompt}"

        assert hasattr(call_llm, "_circuit_breaker")
        cb = call_llm._circuit_breaker
        assert cb.name == "llm_api"
        assert cb.config.failure_threshold == 3

    @pytest.mark.asyncio
    async def test_decorator_success(self):
        @circuit_breaker("api")
        async def api_call():
            return "ok"

        result = await api_call()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_decorator_failure_trips(self):
        @circuit_breaker("api", failure_threshold=1, timeout_seconds=60)
        async def failing_call():
            raise ValueError("error")

        with pytest.raises(ValueError):
            await failing_call()

        # Circuit should now be open
        with pytest.raises(CircuitOpenError):
            await failing_call()


# ============================================================================
# CircuitOpenError
# ============================================================================

class TestCircuitOpenError:
    def test_error_message(self):
        err = CircuitOpenError("Circuit 'api' is OPEN")
        assert "api" in str(err)
        assert "OPEN" in str(err)


# ============================================================================
# Default registry
# ============================================================================

class TestDefaultRegistry:
    def test_default_registry_exists(self):
        assert isinstance(default_registry, CircuitRegistry)
