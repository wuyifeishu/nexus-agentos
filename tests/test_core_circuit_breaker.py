"""Tests for agentos.core.circuit_breaker — ~20 test cases."""

import pytest

from agentos.core.circuit_breaker import (
    CircuitBreaker,
    CircuitConfig,
    CircuitOpenError,
    CircuitRegistry,
    CircuitState,
    circuit_breaker,
)


class TestCircuitBreaker:
    """Circuit breaker state machine."""

    def test_initial_state_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_passes_when_closed(self):
        cb = CircuitBreaker("test")
        called = False

        async def fn():
            nonlocal called
            called = True
            return "ok"

        result = await cb.call(fn)
        assert result == "ok"
        assert called

    @pytest.mark.asyncio
    async def test_trips_on_failure_threshold(self):
        config = CircuitConfig(failure_threshold=2, timeout_seconds=99)
        cb = CircuitBreaker("test", config)

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_rejects_when_open(self):
        config = CircuitConfig(failure_threshold=1, timeout_seconds=99)
        cb = CircuitBreaker("test", config)

        with pytest.raises(ValueError):
            await cb.call(_fail)
        with pytest.raises(CircuitOpenError):
            await cb.call(_ok_async)

    @pytest.mark.asyncio
    async def test_fallback_used_when_open(self):
        config = CircuitConfig(failure_threshold=1, timeout_seconds=99)
        cb = CircuitBreaker("test", config)

        with pytest.raises(ValueError):
            await cb.call(_fail)
        result = await cb.call(_ok_async, fallback=_fallback)
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_excluded_exceptions(self):
        config = CircuitConfig(
            failure_threshold=1,
            excluded_exceptions=(KeyError,),
        )
        cb = CircuitBreaker("test", config)

        with pytest.raises(KeyError):
            await cb.call(_raise_key_error)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_timeout_transition_to_half_open(self):
        config = CircuitConfig(failure_threshold=1, timeout_seconds=0)
        cb = CircuitBreaker("test", config)

        with pytest.raises(ValueError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

        # timeout_seconds=0 → immediate HALF_OPEN
        ok = await cb.acquire()
        assert ok
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        config = CircuitConfig(
            failure_threshold=1,
            timeout_seconds=0,
            success_threshold=1,
        )
        cb = CircuitBreaker("test", config)

        with pytest.raises(ValueError):
            await cb.call(_fail)
        result = await cb.call(_ok_async)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        config = CircuitConfig(
            failure_threshold=1,
            timeout_seconds=0,
            success_threshold=3,
        )
        cb = CircuitBreaker("test", config)

        with pytest.raises(ValueError):
            await cb.call(_fail)
        with pytest.raises(ValueError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_stats_counters(self):
        cb = CircuitBreaker("test", CircuitConfig(failure_threshold=10))
        await cb.call(_ok_async)
        await cb.call(_ok_async)
        with pytest.raises(ValueError):
            await cb.call(_fail)

        assert cb.stats.total_successes == 2
        assert cb.stats.total_failures == 1
        assert cb.state == CircuitState.CLOSED


class TestCircuitRegistry:
    """Registry management."""

    @pytest.mark.asyncio
    async def test_singleton_per_name(self):
        reg = CircuitRegistry()
        a = await reg.get_or_create("svc")
        b = await reg.get_or_create("svc")
        assert a is b

    @pytest.mark.asyncio
    async def test_isolated_circuits(self):
        reg = CircuitRegistry()
        cb1 = await reg.get_or_create("a", CircuitConfig(failure_threshold=1))
        with pytest.raises(ValueError):
            await cb1.call(_fail)

        cb2 = await reg.get_or_create("b")
        assert cb2.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_force_admin_ops(self):
        reg = CircuitRegistry()
        await reg.get_or_create("x")
        await reg.force_open("x")
        stats = reg.get_all_stats()
        assert stats["x"].state == CircuitState.OPEN

        await reg.force_closed("x")
        assert reg.get_all_stats()["x"].state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reset_all(self):
        reg = CircuitRegistry()
        cb = await reg.get_or_create("z", CircuitConfig(failure_threshold=1))
        with pytest.raises(ValueError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

        await reg.reset_all()
        assert cb.state == CircuitState.CLOSED


class TestDecorator:
    """@circuit_breaker decorator."""

    @pytest.mark.asyncio
    async def test_decorator_basic(self):
        @circuit_breaker("deco1", failure_threshold=10)
        async def fn():
            return "yes"

        r = await fn()
        assert r == "yes"

    @pytest.mark.asyncio
    async def test_decorator_trips(self):
        @circuit_breaker("deco2", failure_threshold=1, timeout_seconds=99)
        async def fn():
            raise ValueError("bad")

        with pytest.raises(ValueError):
            await fn()
        with pytest.raises(CircuitOpenError):
            await fn()


# Helpers
async def _ok_async():
    return "ok"

async def _fail():
    raise ValueError("fail")

async def _fallback(*args, **kwargs):
    return "fallback"

async def _raise_key_error():
    raise KeyError("excluded")
