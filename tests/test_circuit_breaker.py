"""Tests for agentos.tools.circuit_breaker — CircuitBreaker, CircuitRegistry."""

import time

import pytest

from agentos.tools.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitRegistry,
    CircuitState,
    get_circuit_registry,
)


class TestCircuitState:
    def test_three_states(self):
        assert len(CircuitState) == 3
        assert CircuitState.CLOSED != CircuitState.OPEN != CircuitState.HALF_OPEN


class TestCircuitBreaker:
    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.name == "default"

    def test_call_success(self):
        cb = CircuitBreaker()
        result = cb.call(lambda x: x + 1, 1)
        assert result == 2

    def test_call_failure(self):
        cb = CircuitBreaker(failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

        assert cb.state == CircuitState.OPEN

    def test_call_open_raises(self):
        cb = CircuitBreaker(failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            cb.call(lambda: 42)

    def test_half_open_after_recovery(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))

        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        result = cb.call(lambda: 42)
        assert result == 42

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, success_threshold=1)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        time.sleep(0.02)
        cb.call(lambda: 42)
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        time.sleep(0.02)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        assert cb.state == CircuitState.OPEN

    def test_half_open_max_calls(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=2, success_threshold=5)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        time.sleep(0.02)
        cb.call(lambda: 42)  # probe 1
        cb.call(lambda: 42)  # probe 2
        with pytest.raises(CircuitOpenError):
            cb.call(lambda: 42)  # limit reached

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_trip(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.trip()
        assert cb.state == CircuitState.OPEN

    def test_stats(self):
        cb = CircuitBreaker(name="api")
        cb.call(lambda: 1)
        stats = cb.stats
        assert stats["name"] == "api"
        assert stats["state"] == "CLOSED"
        assert stats["total_calls"] == 1

    def test_on_state_change_callback(self):
        states = []

        def track(cb, old, new):
            states.append((old, new))

        cb = CircuitBreaker(failure_threshold=1, on_state_change=track)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        assert len(states) >= 1
        assert states[0] == (CircuitState.CLOSED, CircuitState.OPEN)


class TestCircuitRegistry:
    def test_get_creates_new(self):
        reg = CircuitRegistry()
        cb = reg.get("api", failure_threshold=3)
        assert cb.name == "api"
        assert cb.failure_threshold == 3

    def test_get_reuses(self):
        reg = CircuitRegistry()
        cb1 = reg.get("db")
        cb2 = reg.get("db")
        assert cb1 is cb2

    def test_list_breakers(self):
        reg = CircuitRegistry()
        reg.get("api")
        reg.get("db")
        lst = reg.list_breakers()
        assert len(lst) == 2
        assert lst["api"] == "CLOSED"

    def test_remove(self):
        reg = CircuitRegistry()
        reg.get("temp")
        assert reg.remove("temp") is True
        assert reg.remove("temp") is False

    def test_reset_all(self):
        reg = CircuitRegistry()
        cb = reg.get("api", failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
        assert cb.state == CircuitState.OPEN
        reg.reset_all()
        assert cb.state == CircuitState.CLOSED


class TestGetCircuitRegistry:
    def test_singleton(self):
        r1 = get_circuit_registry()
        r2 = get_circuit_registry()
        assert r1 is r2

    def test_reset_after_remove_singleton(self):
        # ensure registry is cleared between tests
        r = get_circuit_registry()
        r.reset_all()
        r.get("test")
        assert "test" in r.list_breakers()
        r.remove("test")
        assert "test" not in r.list_breakers()
