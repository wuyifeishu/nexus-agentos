"""Tests for agentos.core.lifecycle — graceful startup/shutdown."""

from __future__ import annotations

import asyncio

import pytest

from agentos.core.lifecycle import (
    ComponentHealth,
    ComponentStatus,
    LifecycleHook,
    LifecycleManager,
    LifecyclePhase,
    LifecycleReport,
    get_lifecycle,
)

# ============================================================================
# LifecyclePhase
# ============================================================================

class TestLifecyclePhase:
    def test_enum_values(self):
        assert LifecyclePhase.CONFIG.value == "config"
        assert LifecyclePhase.INFRA.value == "infra"
        assert LifecyclePhase.SECURITY.value == "security"
        assert LifecyclePhase.SERVICES.value == "services"
        assert LifecyclePhase.MIDDLEWARE.value == "middleware"
        assert LifecyclePhase.API.value == "api"
        assert LifecyclePhase.READY.value == "ready"

    def test_order_preserved(self):
        """Phase order must match expected startup sequence."""
        expected = [
            LifecyclePhase.CONFIG,
            LifecyclePhase.INFRA,
            LifecyclePhase.SECURITY,
            LifecyclePhase.SERVICES,
            LifecyclePhase.MIDDLEWARE,
            LifecyclePhase.API,
            LifecyclePhase.READY,
        ]
        assert LifecycleManager.PHASE_ORDER == expected


# ============================================================================
# ComponentStatus
# ============================================================================

class TestComponentStatus:
    def test_enum_values(self):
        assert ComponentStatus.UNINITIALIZED.value == "uninitialized"
        assert ComponentStatus.HEALTHY.value == "healthy"
        assert ComponentStatus.DEGRADED.value == "degraded"
        assert ComponentStatus.UNHEALTHY.value == "unhealthy"
        assert ComponentStatus.SHUTTING_DOWN.value == "shutting_down"
        assert ComponentStatus.STOPPED.value == "stopped"


# ============================================================================
# ComponentHealth
# ============================================================================

class TestComponentHealth:
    def test_defaults(self):
        h = ComponentHealth(name="test")
        assert h.name == "test"
        assert h.status == ComponentStatus.UNINITIALIZED
        assert h.duration_ms == 0.0
        assert h.error is None

    def test_custom_values(self):
        h = ComponentHealth(
            name="db",
            status=ComponentStatus.HEALTHY,
            phase=LifecyclePhase.INFRA,
            message="connected",
            duration_ms=12.5,
        )
        assert h.name == "db"
        assert h.status == ComponentStatus.HEALTHY
        assert h.duration_ms == 12.5


# ============================================================================
# LifecycleHook
# ============================================================================

class TestLifecycleHook:
    def test_defaults(self):
        def dummy():
            pass

        hook = LifecycleHook(name="test", phase=LifecyclePhase.SERVICES, fn=dummy)
        assert hook.name == "test"
        assert hook.timeout_seconds == 30.0
        assert hook.critical is True
        assert hook.weight == 50
        assert hook.retries == 0

    def test_custom_retries(self):
        def dummy():
            pass

        hook = LifecycleHook(
            name="flaky", phase=LifecyclePhase.INFRA, fn=dummy,
            retries=3, retry_delay=0.1,
        )
        assert hook.retries == 3
        assert hook.retry_delay == 0.1


# ============================================================================
# LifecycleReport
# ============================================================================

class TestLifecycleReport:
    def test_defaults(self):
        report = LifecycleReport()
        assert report.overall_status == ComponentStatus.UNINITIALIZED
        assert report.is_healthy is False
        assert report.is_ready is False

    def test_healthy_report(self):
        report = LifecycleReport(overall_status=ComponentStatus.HEALTHY)
        assert report.is_healthy is True
        assert report.is_ready is True

    def test_degraded_is_ready(self):
        report = LifecycleReport(overall_status=ComponentStatus.DEGRADED)
        assert report.is_ready is True
        assert report.is_healthy is False

    def test_shutdown_remaining_hooks(self):
        report = LifecycleReport(shutdown_remaining_hooks=3)
        assert report.shutdown_remaining_hooks == 3


# ============================================================================
# LifecycleManager — Registration
# ============================================================================

class TestLifecycleManagerRegistration:
    def test_on_startup_decorator(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.CONFIG)
        def load_config():
            pass

        assert len(lm._startup_hooks) == 1
        assert lm._startup_hooks[0].name == "load_config"
        assert lm._startup_hooks[0].phase == LifecyclePhase.CONFIG

    def test_on_startup_with_custom_name(self):
        lm = LifecycleManager()

        @lm.on_startup(name="custom_init", phase=LifecyclePhase.INFRA)
        def real_name():
            pass

        assert lm._startup_hooks[0].name == "custom_init"

    def test_on_startup_async_detection(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.SERVICES)
        async def async_service():
            pass

        assert lm._startup_hooks[0].is_async is True

    def test_on_shutdown_decorator(self):
        lm = LifecycleManager()

        @lm.on_shutdown()
        def cleanup():
            pass

        assert len(lm._shutdown_hooks) == 1
        assert lm._shutdown_hooks[0].name == "cleanup"

    def test_on_shutdown_async(self):
        lm = LifecycleManager()

        @lm.on_shutdown()
        async def async_cleanup():
            pass

        assert lm._shutdown_hooks[0].is_async is True

    def test_health_registered_on_startup(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.INFRA)
        def init_db():
            pass

        assert "init_db" in lm._health
        assert lm._health["init_db"].phase == LifecyclePhase.INFRA


# ============================================================================
# LifecycleManager — Startup
# ============================================================================

class TestLifecycleManagerStartup:
    @pytest.mark.asyncio
    async def test_start_executes_hooks_in_order(self):
        lm = LifecycleManager()
        execution_order = []

        @lm.on_startup(phase=LifecyclePhase.CONFIG, weight=10)
        def config_first():
            execution_order.append("config")

        @lm.on_startup(phase=LifecyclePhase.INFRA, weight=10)
        def infra_second():
            execution_order.append("infra")

        report = await lm.start()
        assert execution_order == ["config", "infra"]
        assert report.overall_status == ComponentStatus.HEALTHY
        assert report.startup_duration_ms > 0

    @pytest.mark.asyncio
    async def test_start_async_hooks(self):
        lm = LifecycleManager()
        ran = {}

        @lm.on_startup(phase=LifecyclePhase.SERVICES)
        async def async_hook():
            await asyncio.sleep(0.01)
            ran["async"] = True

        report = await lm.start()
        assert ran.get("async") is True
        assert report.overall_status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_start_critical_failure_stops(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.CONFIG, critical=True)
        def bad_config():
            raise RuntimeError("config failure")

        report = await lm.start()
        assert report.overall_status == ComponentStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_start_non_critical_failure_continues(self):
        lm = LifecycleManager()
        ran = {}

        @lm.on_startup(phase=LifecyclePhase.CONFIG, critical=False)
        def warn_config():
            ran["warn"] = True
            raise RuntimeError("non-critical warning")

        @lm.on_startup(phase=LifecyclePhase.INFRA, critical=True)
        def infra_ok():
            ran["infra"] = True

        report = await lm.start()
        assert ran.get("warn") is True
        assert ran.get("infra") is True
        assert report.overall_status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_start_retry_success(self):
        lm = LifecycleManager()
        attempts = []

        @lm.on_startup(phase=LifecyclePhase.INFRA, retries=2, retry_delay=0.01)
        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("temporary failure")

        report = await lm.start()
        assert len(attempts) == 3
        assert report.overall_status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_start_retry_exhausted(self):
        lm = LifecycleManager()
        attempts = []

        @lm.on_startup(phase=LifecyclePhase.INFRA, retries=1, retry_delay=0.01)
        def flaky():
            attempts.append(1)
            raise RuntimeError("always fails")

        report = await lm.start()
        assert len(attempts) == 2  # initial + 1 retry
        assert report.overall_status == ComponentStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_start_timeout_marks_unhealthy(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.CONFIG, timeout_seconds=0.05)
        async def slow():
            await asyncio.sleep(1.0)

        report = await lm.start()
        assert report.overall_status == ComponentStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_start_sets_ready_event(self):
        lm = LifecycleManager()
        await lm.start()
        assert lm.is_ready() is True

    @pytest.mark.asyncio
    async def test_start_tracks_component_health(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.INFRA)
        def init_db():
            pass

        await lm.start()
        health = lm._health.get("init_db")
        assert health is not None
        assert health.status == ComponentStatus.HEALTHY
        assert health.duration_ms > 0


# ============================================================================
# LifecycleManager — Shutdown
# ============================================================================

class TestLifecycleManagerShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_executes_hooks_reverse_order(self):
        lm = LifecycleManager()
        shutdown_order = []

        @lm.on_shutdown(weight=1)
        def first_registered():
            shutdown_order.append("first")

        @lm.on_shutdown(weight=2)
        def second_registered():
            shutdown_order.append("second")

        report = await lm.shutdown()
        assert shutdown_order == ["second", "first"]
        assert report.overall_status == ComponentStatus.STOPPED

    @pytest.mark.asyncio
    async def test_shutdown_async_hooks(self):
        lm = LifecycleManager()
        ran = {}

        @lm.on_shutdown()
        async def async_cleanup():
            await asyncio.sleep(0.01)
            ran["shutdown"] = True

        await lm.shutdown()
        assert ran.get("shutdown") is True

    @pytest.mark.asyncio
    async def test_double_shutdown_noop(self):
        lm = LifecycleManager()
        first = await lm.shutdown()
        second = await lm.shutdown()
        assert first.overall_status == second.overall_status
        assert second.overall_status == ComponentStatus.STOPPED

    @pytest.mark.asyncio
    async def test_shutdown_sets_shutdown_event(self):
        lm = LifecycleManager()
        await lm.shutdown()
        assert lm._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_shutdown_reports_remaining_hooks(self):
        lm = LifecycleManager()

        @lm.on_shutdown
        async def long_shutdown():
            await asyncio.sleep(0.1)

        await lm.start()
        report = await lm.shutdown()
        assert report.shutdown_remaining_hooks == 0


# ============================================================================
# LifecycleManager — Probes
# ============================================================================

class TestLifecycleManagerProbes:
    def test_default_not_ready(self):
        lm = LifecycleManager()
        assert lm.is_ready() is False

    def test_default_is_live(self):
        lm = LifecycleManager()
        assert lm.is_live() is True

    @pytest.mark.asyncio
    async def test_stopped_not_live(self):
        lm = LifecycleManager()
        await lm.shutdown()
        assert lm.is_live() is False

    @pytest.mark.asyncio
    async def test_unhealthy_not_live(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.CONFIG, critical=True)
        def fail():
            raise RuntimeError("dead")

        await lm.start()
        assert lm.is_live() is False


# ============================================================================
# LifecycleManager — Context Manager
# ============================================================================

class TestLifecycleManagerContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_start_shutdown(self):
        lm = LifecycleManager()
        ran_start = {}
        ran_shutdown = {}

        @lm.on_startup(phase=LifecyclePhase.CONFIG)
        def init():
            ran_start["done"] = True

        @lm.on_shutdown()
        def cleanup():
            ran_shutdown["done"] = True

        async with lm:
            assert ran_start["done"] is True
            # simulate running
            await asyncio.sleep(0.01)

        assert ran_shutdown["done"] is True
        assert lm._status == ComponentStatus.STOPPED

    @pytest.mark.asyncio
    async def test_context_manager_does_not_suppress_exception(self):
        lm = LifecycleManager()

        class TestException(Exception):
            pass

        with pytest.raises(TestException):
            async with lm:
                raise TestException("expected")
        # Shutdown still fires after exception
        assert lm._status == ComponentStatus.STOPPED


# ============================================================================
# LifecycleManager — Report
# ============================================================================

class TestLifecycleManagerReport:
    @pytest.mark.asyncio
    async def test_report_after_start(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.CONFIG)
        def init():
            pass

        await lm.start()
        report = lm.report()
        assert report.overall_status == ComponentStatus.HEALTHY
        assert "init" in report.components
        assert report.startup_duration_ms > 0

    @pytest.mark.asyncio
    async def test_report_with_degraded_component(self):
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.CONFIG, critical=False)
        def warn_only():
            raise RuntimeError("degraded but ok")

        @lm.on_startup(phase=LifecyclePhase.INFRA)
        def infra_ok():
            pass

        await lm.start()
        report = lm.report()
        assert report.overall_status == ComponentStatus.HEALTHY


# ============================================================================
# get_lifecycle singleton
# ============================================================================

class TestGetLifecycle:
    def test_returns_singleton(self):
        lm1 = get_lifecycle()
        lm2 = get_lifecycle()
        assert lm1 is lm2

    def test_respects_custom_params_first_call(self, monkeypatch):
        # Reset global to simulate first call
        import agentos.core.lifecycle as lc_mod
        monkeypatch.setattr(lc_mod, "_default_lifecycle", None)
        lm = get_lifecycle(grace_period=60.0, startup_timeout=200.0)
        assert lm._grace_period == 60.0
        assert lm._startup_timeout == 200.0
        # Reset for other tests
        monkeypatch.setattr(lc_mod, "_default_lifecycle", None)
