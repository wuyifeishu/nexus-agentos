"""
Circuit Breaker for AgentOS.

Protects against cascading failures with three states:
- CLOSED: normal operation, track failures
- OPEN: circuit tripped, fast-fail all calls
- HALF_OPEN: probe with limited calls to test recovery

Supports failure/success thresholds, recovery timeout, and callbacks.
"""

import threading
import time
from collections.abc import Callable
from enum import Enum, auto
from typing import Any, TypeVar

T = TypeVar("T")


# ============================================================================
# Enums & Types
# ============================================================================


class CircuitState(Enum):
    CLOSED = auto()  # Normal operation
    OPEN = auto()  # Fast-fail, no calls allowed
    HALF_OPEN = auto()  # Probe mode, limited calls allowed


CircuitCallback = Callable[["CircuitBreaker", CircuitState, CircuitState], None]


# ============================================================================
# CircuitBreaker
# ============================================================================


class CircuitBreaker:
    """Thread-safe circuit breaker.

    Parameters:
        failure_threshold: consecutive/max failures before tripping
        recovery_timeout: seconds before transitioning OPEN → HALF_OPEN
        half_open_max_calls: max probe calls in HALF_OPEN before deciding
        success_threshold: successes needed in HALF_OPEN to close circuit
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        success_threshold: int = 2,
        on_state_change: CircuitCallback | None = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        self.on_state_change = on_state_change

        self._lock = threading.RLock()
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._half_open_calls: int = 0
        self._last_failure_time: float = 0.0
        self._last_success_time: float = 0.0
        self._total_calls: int = 0
        self._total_failures: int = 0
        self._total_successes: int = 0
        self._opened_at: float = 0.0

    # ---------- state management ----------

    def _transition(self, new_state: CircuitState) -> None:
        old = self._state
        if old == new_state:
            return
        self._state = new_state
        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
        elif new_state == CircuitState.HALF_OPEN:
            self._success_count = 0
            self._half_open_calls = 0
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
        if self.on_state_change:
            try:
                self.on_state_change(self, old, new_state)
            except Exception:
                pass

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    # ---------- call execution ----------

    def call(self, fn: Callable[..., T], *args, **kwargs) -> T:
        """Execute fn through the circuit breaker. Raises CircuitOpenError if open."""
        self._check_state()
        self._total_calls += 1
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _check_state(self) -> None:
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return
            if self._state == CircuitState.OPEN:
                elapsed = time.time() - self._opened_at
                if elapsed >= self.recovery_timeout:
                    self._transition(CircuitState.HALF_OPEN)
                    self._half_open_calls += 1  # count this probe
                    return
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is OPEN "
                    f"(recovery in {self.recovery_timeout - elapsed:.1f}s)"
                )
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitOpenError(
                        f"Circuit '{self.name}' HALF_OPEN limit reached "
                        f"({self._half_open_calls}/{self.half_open_max_calls})"
                    )
                self._half_open_calls += 1

    def _on_success(self) -> None:
        with self._lock:
            self._total_successes += 1
            self._last_success_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._total_failures += 1
            self._last_failure_time = time.time()
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
            elif (
                self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold
            ):
                self._transition(CircuitState.OPEN)

    # ---------- manual control with granular hooks ----------

    def allow_request(self) -> bool:
        """Check whether a request is allowed (used by ToolExecutor)."""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                elapsed = time.time() - self._opened_at
                if elapsed >= self.recovery_timeout:
                    self._transition(CircuitState.HALF_OPEN)
                    self._half_open_calls += 1
                    return True
                return False
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    return False
                self._half_open_calls += 1
                return True
            return False

    def record_success(self) -> None:
        """Record a successful call (used by ToolExecutor)."""
        with self._lock:
            self._total_calls += 1
            self._total_successes += 1
            self._last_success_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition(CircuitState.CLOSED)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call (used by ToolExecutor)."""
        with self._lock:
            self._total_calls += 1
            self._total_failures += 1
            self._last_failure_time = time.time()
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._transition(CircuitState.OPEN)

    # ---------- manual control ----------

    def reset(self) -> None:
        """Force circuit back to CLOSED."""
        with self._lock:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._transition(CircuitState.CLOSED)

    def trip(self) -> None:
        """Force circuit OPEN."""
        with self._lock:
            self._failure_count = self.failure_threshold
            self._transition(CircuitState.OPEN)

    # ---------- stats ----------

    @property
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.name,
                "failure_count": self._failure_count,
                "half_open_calls": self._half_open_calls,
                "total_calls": self._total_calls,
                "total_successes": self._total_successes,
                "total_failures": self._total_failures,
                "last_failure": self._last_failure_time,
                "last_success": self._last_success_time,
                "opened_at": self._opened_at,
            }


# ============================================================================
# Errors
# ============================================================================


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an OPEN circuit."""



# ============================================================================
# CircuitRegistry — manage multiple breakers by name
# ============================================================================


class CircuitRegistry:
    """Global registry for named circuit breakers."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, name: str, **kwargs) -> CircuitBreaker:
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name=name, **kwargs)
            return self._breakers[name]

    def remove(self, name: str) -> bool:
        with self._lock:
            return self._breakers.pop(name, None) is not None

    def list_breakers(self) -> dict[str, str]:
        with self._lock:
            return {n: b.state.name for n, b in self._breakers.items()}

    def reset_all(self) -> None:
        with self._lock:
            for b in self._breakers.values():
                b.reset()


_default_registry: CircuitRegistry | None = None
_registry_lock = threading.Lock()


def get_circuit_registry() -> CircuitRegistry:
    global _default_registry
    if _default_registry is None:
        with _registry_lock:
            if _default_registry is None:
                _default_registry = CircuitRegistry()
    return _default_registry
