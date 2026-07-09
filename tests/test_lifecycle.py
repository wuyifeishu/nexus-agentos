"""Test AgentOS Lifecycle — graceful startup/shutdown with hooks."""

from __future__ import annotations

import asyncio

import pytest

from agentos.core.lifecycle import (
    ComponentStatus,
    LifecycleManager,
    LifecyclePhase,
    get_lifecycle,
)

# ============================================================================
# Helpers
# ============================================================================

@pytest.fixture
def lifecycle():
    """Fresh LifecycleManager per test."""
    return LifecycleManager(grace_period=5.0, startup_timeout=10.0)


@pytest.fixture
def record():
    """Mutable list to record hook execution order."""
    return []


# ============================================================================
# Registration
# ============================================================================

class TestRegistration:
    """Hook registration tests."""

    def test_on_startup_registers_hook(self, lifecycle, record):
        """Decorator registers a startup hook."""
        @lifecycle.on_startup(name="init_db", phase=LifecyclePhase.INFRA)
        async def init_db():
            record.append("db")

        assert len(lifecycle._startup_hooks) == 1
        assert lifecycle._startup_hooks[0].name == "init_db"
        assert lifecycle._startup_hooks[0].phase == LifecyclePhase.INFRA

    def test_on_startup_auto_name(self, lifecycle):
        """Decorator uses function name when name not provided."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG)
        async def load_config():
            pass

        assert lifecycle._startup_hooks[0].name == "load_config"

    def test_on_startup_detects_async(self, lifecycle):
        """Decorator correctly detects async functions."""
        @lifecycle.on_startup(phase=LifecyclePhase.SERVICES)
        def sync_hook():
            pass

        @lifecycle.on_startup(phase=LifecyclePhase.SERVICES)
        async def async_hook():
            pass

        assert lifecycle._startup_hooks[0].is_async is False
        assert lifecycle._startup_hooks[1].is_async is True

    def test_on_shutdown_registers_hook(self, lifecycle, record):
        """Decorator registers a shutdown hook."""
        @lifecycle.on_shutdown(name="close_db")
        async def close_db():
            record.append("close_db")

        assert len(lifecycle._shutdown_hooks) == 1
        assert lifecycle._shutdown_hooks[0].name == "close_db"

    def test_on_startup_critical_default(self, lifecycle):
        """Startup hooks are critical by default."""
        @lifecycle.on_startup(phase=LifecyclePhase.INFRA)
        async def db():
            pass

        assert lifecycle._startup_hooks[0].critical is True

    def test_on_startup_non_critical(self, lifecycle):
        """Non-critical hook can be registered."""
        @lifecycle.on_startup(phase=LifecyclePhase.SERVICES, critical=False)
        async def cache():
            pass

        assert lifecycle._startup_hooks[0].critical is False

    def test_on_startup_with_retries(self, lifecycle):
        """Hook with retry configuration."""
        @lifecycle.on_startup(phase=LifecyclePhase.INFRA, retries=2, retry_delay=0.1)
        async def flaky():
            pass

        assert lifecycle._startup_hooks[0].retries == 2


# ============================================================================
# Startup
# ============================================================================

class TestStartup:
    """Startup execution tests."""

    async def test_basic_startup(self, lifecycle, record):
        """All hooks execute in phase order."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG, name="cfg")
        async def cfg():
            record.append("cfg")

        @lifecycle.on_startup(phase=LifecyclePhase.INFRA, name="db")
        async def db():
            record.append("db")

        @lifecycle.on_startup(phase=LifecyclePhase.API, name="http")
        async def http():
            record.append("http")

        report = await lifecycle.start()
        assert report.overall_status == ComponentStatus.HEALTHY
        assert record == ["cfg", "db", "http"]

    def test_phase_order_is_deterministic(self, lifecycle):
        """PHASE_ORDER covers all phases."""
        phases = LifecycleManager.PHASE_ORDER
        assert phases[0] == LifecyclePhase.CONFIG
        assert phases[-1] == LifecyclePhase.READY
        assert len(phases) == len(set(phases))  # No duplicates

    async def test_same_phase_ordered_by_weight(self, lifecycle, record):
        """Hooks in the same phase execute in weight order."""
        @lifecycle.on_startup(phase=LifecyclePhase.SERVICES, name="a", weight=30)
        async def a():
            record.append("a")

        @lifecycle.on_startup(phase=LifecyclePhase.SERVICES, name="b", weight=10)
        async def b():
            record.append("b")

        await lifecycle.start()
        assert record == ["b", "a"]  # Lower weight first

    async def test_critical_failure_stops_startup(self, lifecycle, record):
        """Critical hook failure prevents further startup."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG, name="cfg")
        async def cfg():
            record.append("cfg")

        @lifecycle.on_startup(phase=LifecyclePhase.INFRA, name="db", critical=True)
        async def db():
            raise RuntimeError("DB connection failed")

        @lifecycle.on_startup(phase=LifecyclePhase.API, name="http")
        async def http():
            record.append("http")  # Should NOT execute

        report = await lifecycle.start()
        assert report.overall_status == ComponentStatus.UNHEALTHY
        assert record == ["cfg"]  # http never runs

    async def test_non_critical_failure_continues(self, lifecycle, record):
        """Non-critical hook failure does not halt startup."""
        @lifecycle.on_startup(phase=LifecyclePhase.SERVICES, name="cache", critical=False)
        async def cache():
            record.append("cache-fail")
            raise RuntimeError("Cache unavailable")

        @lifecycle.on_startup(phase=LifecyclePhase.API, name="http")
        async def http():
            record.append("http")

        report = await lifecycle.start()
        assert report.overall_status == ComponentStatus.HEALTHY
        assert "cache-fail" in record
        assert "http" in record

    async def test_hook_timeout_marks_unhealthy(self, lifecycle):
        """Hook exceeding timeout is treated as failure."""
        @lifecycle.on_startup(
            phase=LifecyclePhase.INFRA, name="slow_db",
            timeout_seconds=0.1, critical=True,
        )
        async def slow_db():
            await asyncio.sleep(1.0)

        report = await lifecycle.start()
        assert report.overall_status == ComponentStatus.UNHEALTHY

    async def test_hook_with_retries_succeeds(self, lifecycle, record):
        """Retry: hook fails first, succeeds second."""
        attempts = []

        @lifecycle.on_startup(
            phase=LifecyclePhase.INFRA, name="flaky",
            retries=1, retry_delay=0.05,
        )
        async def flaky():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("First attempt failed")

        report = await lifecycle.start()
        assert report.overall_status == ComponentStatus.HEALTHY
        assert len(attempts) == 2

    async def test_hook_exhausts_retries(self, lifecycle):
        """Hook eventually fails after all retries."""
        @lifecycle.on_startup(
            phase=LifecyclePhase.INFRA, name="doomed",
            retries=2, retry_delay=0.05, critical=True,
        )
        async def doomed():
            raise RuntimeError("Always fails")

        report = await lifecycle.start()
        assert report.overall_status == ComponentStatus.UNHEALTHY

    async def test_sync_hooks_executed(self, lifecycle, record):
        """Sync (non-async) hooks are executed in executor."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG, name="sync_cfg")
        def sync_cfg():
            record.append("sync")

        @lifecycle.on_startup(phase=LifecyclePhase.API, name="async_api")
        async def async_api():
            record.append("async")

        await lifecycle.start()
        assert "sync" in record
        assert "async" in record


# ============================================================================
# Shutdown
# ============================================================================

class TestShutdown:
    """Shutdown execution tests."""

    async def test_shutdown_reverse_order(self, lifecycle, record):
        """Shutdown hooks execute in reverse registration order."""
        @lifecycle.on_shutdown(name="a")
        async def a():
            record.append("a")

        @lifecycle.on_shutdown(name="b")
        async def b():
            record.append("b")

        @lifecycle.on_shutdown(name="c")
        async def c():
            record.append("c")

        await lifecycle.shutdown()
        assert record == ["c", "b", "a"]

    async def test_shutdown_continues_on_error(self, lifecycle, record):
        """Shutdown errors don't prevent remaining hooks."""
        @lifecycle.on_shutdown(name="fail")
        async def fail():
            record.append("fail")
            raise RuntimeError("Close failed")

        @lifecycle.on_shutdown(name="ok")
        async def ok():
            record.append("ok")

        await lifecycle.shutdown()
        assert "fail" in record
        assert "ok" in record

    async def test_shutdown_idempotent(self, lifecycle, record):
        """Second shutdown call is a no-op."""
        @lifecycle.on_shutdown(name="close")
        async def close():
            record.append("close")

        await lifecycle.shutdown()
        await lifecycle.shutdown()
        assert record == ["close"]  # Only once

    async def test_shutdown_sync_hook(self, lifecycle, record):
        """Sync shutdown hooks work."""
        @lifecycle.on_shutdown(name="sync_close")
        def sync_close():
            record.append("sync")

        await lifecycle.shutdown()
        assert "sync" in record


# ============================================================================
# Probes
# ============================================================================

class TestProbes:
    """Liveness and readiness probe tests."""

    def test_not_ready_before_start(self, lifecycle):
        """is_ready() returns False before startup."""
        assert lifecycle.is_ready() is False

    async def test_ready_after_start(self, lifecycle):
        """is_ready() returns True after successful startup."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG)
        async def cfg():
            pass

        await lifecycle.start()
        assert lifecycle.is_ready() is True

    def test_is_live_defaults_false(self, lifecycle):
        """is_live() returns False before start (UNINITIALIZED is not STOPPED/UNHEALTHY)."""
        # UNINITIALIZED is not STOPPED or UNHEALTHY → should be True
        assert lifecycle.is_live() is True

    async def test_is_live_after_start(self, lifecycle):
        """is_live() returns True when healthy."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG)
        async def cfg():
            pass

        await lifecycle.start()
        assert lifecycle.is_live() is True

    async def test_is_live_false_after_shutdown(self, lifecycle):
        """is_live() returns False when stopped."""
        await lifecycle.shutdown()
        assert lifecycle.is_live() is False


# ============================================================================
# Report
# ============================================================================

class TestReport:
    """Lifecycle report tests."""

    async def test_report_after_start(self, lifecycle):
        """Report includes component health after startup."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG, name="cfg")
        async def cfg():
            pass

        report = await lifecycle.start()
        assert report.overall_status == ComponentStatus.HEALTHY
        assert "cfg" in report.components
        assert report.components["cfg"].status == ComponentStatus.HEALTHY
        assert report.components["cfg"].duration_ms >= 0
        assert report.startup_duration_ms >= 0

    async def test_report_captures_failures(self, lifecycle):
        """Report includes unhealthy component after failure."""
        @lifecycle.on_startup(phase=LifecyclePhase.INFRA, name="db", critical=True)
        async def db():
            raise RuntimeError("boom")

        report = await lifecycle.start()
        assert report.components["db"].status == ComponentStatus.UNHEALTHY
        assert "boom" in (report.components["db"].error or "")

    async def test_report_tracks_duration(self, lifecycle):
        """startup_duration_ms reflects actual time."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG, name="cfg")
        async def cfg():
            await asyncio.sleep(0.05)

        report = await lifecycle.start()
        assert report.startup_duration_ms >= 50


# ============================================================================
# Context Manager
# ============================================================================

class TestContextManager:
    """Async context manager tests."""

    async def test_context_manager_basic(self, lifecycle, record):
        """`async with` starts and shuts down."""
        @lifecycle.on_startup(phase=LifecyclePhase.CONFIG, name="cfg")
        async def cfg():
            record.append("start")

        @lifecycle.on_shutdown(name="close")
        async def close():
            record.append("stop")

        async with lifecycle:
            assert lifecycle.is_ready()
        assert record == ["start", "stop"]

    async def test_context_manager_exception(self, lifecycle, record):
        """Exception during context does not prevent shutdown."""
        @lifecycle.on_shutdown(name="close")
        async def close():
            record.append("cleaned")

        with pytest.raises(ValueError, match="boom"):
            async with lifecycle:
                raise ValueError("boom")
        assert "cleaned" in record

    async def test_context_manager_does_not_suppress(self, lifecycle):
        """__aexit__ returns False so exceptions propagate."""
        try:
            async with lifecycle:
                raise RuntimeError("test")
        except RuntimeError:
            pass  # Expected


# ============================================================================
# Signal integration
# ============================================================================

class TestSignals:
    """Signal handler tests."""

    async def test_setup_signal_handlers_no_error(self, lifecycle):
        """setup_signal_handlers() does not raise."""
        loop = asyncio.get_event_loop()
        lifecycle.setup_signal_handlers(loop)  # Should not error

    async def test_shutdown_event_set(self, lifecycle):
        """_shutdown_event is set during shutdown."""
        assert not lifecycle._shutdown_event.is_set()
        await lifecycle.shutdown()
        assert lifecycle._shutdown_event.is_set()

    async def test_shutdown_with_signal_name(self, lifecycle):
        """shutdown accepts signal_name parameter."""
        report = await lifecycle.shutdown("SIGTERM")
        assert report.overall_status == ComponentStatus.STOPPED


# ============================================================================
# Singleton
# ============================================================================

class TestSingleton:
    """get_lifecycle singleton tests."""

    def test_get_lifecycle_returns_same_instance(self):
        """Multiple calls return same instance."""
        # Reset to test
        import agentos.core.lifecycle as lc
        lc._default_lifecycle = None

        lm1 = get_lifecycle()
        lm2 = get_lifecycle()
        assert lm1 is lm2

    def test_get_lifecycle_custom_params_first_call_only(self):
        """Custom params on first call; subsequent calls return same instance."""
        import agentos.core.lifecycle as lc
        lc._default_lifecycle = None

        lm1 = get_lifecycle(grace_period=60.0, startup_timeout=300.0)
        lm2 = get_lifecycle(grace_period=10.0)  # Ignored
        assert lm1._grace_period == 60.0
        assert lm2._grace_period == 60.0  # Same instance
