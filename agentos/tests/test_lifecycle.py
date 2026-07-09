"""Tests for agentos.core.lifecycle — LifecycleManager, hooks, probes, reports."""

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
# LifecycleHook
# ============================================================================


class TestLifecycleHook:
    def test_defaults(self):
        hook = LifecycleHook(name="test", phase=LifecyclePhase.SERVICES, fn=lambda: None)
        assert hook.name == "test"
        assert hook.phase == LifecyclePhase.SERVICES
        assert hook.timeout_seconds == 30.0
        assert hook.critical is True
        assert hook.weight == 50
        assert hook.retries == 0

    def test_custom(self):
        hook = LifecycleHook(
            name="test", phase=LifecyclePhase.API, fn=lambda: None,
            critical=False, weight=10, retries=3,
        )
        assert hook.critical is False
        assert hook.weight == 10
        assert hook.retries == 3


# ============================================================================
# ComponentHealth
# ============================================================================


class TestComponentHealth:
    def test_defaults(self):
        ch = ComponentHealth(name="db")
        assert ch.name == "db"
        assert ch.status == ComponentStatus.UNINITIALIZED
        assert ch.phase is None
        assert ch.message == ""

    def test_custom(self):
        ch = ComponentHealth(
            name="db", status=ComponentStatus.HEALTHY,
            phase=LifecyclePhase.INFRA, message="ok",
        )
        assert ch.status == ComponentStatus.HEALTHY


# ============================================================================
# LifecycleReport
# ============================================================================


class TestLifecycleReport:
    def test_is_healthy(self):
        r = LifecycleReport(overall_status=ComponentStatus.HEALTHY)
        assert r.is_healthy is True

    def test_not_healthy(self):
        r = LifecycleReport(overall_status=ComponentStatus.UNHEALTHY)
        assert r.is_healthy is False

    def test_is_ready_healthy(self):
        r = LifecycleReport(overall_status=ComponentStatus.HEALTHY)
        assert r.is_ready is True

    def test_is_ready_degraded(self):
        r = LifecycleReport(overall_status=ComponentStatus.DEGRADED)
        assert r.is_ready is True

    def test_not_ready(self):
        r = LifecycleReport(overall_status=ComponentStatus.UNINITIALIZED)
        assert r.is_ready is False


# ============================================================================
# LifecycleManager
# ============================================================================


class TestLifecycleManagerCore:
    @pytest.mark.asyncio
    async def test_single_startup_hook(self):
        lm = LifecycleManager()
        ran = []

        @lm.on_startup(name="s1")
        async def startup():
            ran.append(1)

        report = await lm.start()
        assert ran == [1]
        assert report.overall_status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_sync_startup_hook(self):
        lm = LifecycleManager()
        ran = []

        @lm.on_startup(name="s1")
        def startup():
            ran.append(1)

        report = await lm.start()
        assert ran == [1]
        assert report.overall_status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_phase_ordering(self):
        lm = LifecycleManager()
        order = []

        @lm.on_startup(phase=LifecyclePhase.API)
        async def api():
            order.append("api")

        @lm.on_startup(phase=LifecyclePhase.CONFIG)
        async def cfg():
            order.append("config")

        @lm.on_startup(phase=LifecyclePhase.SECURITY)
        async def sec():
            order.append("security")

        await lm.start()
        assert order == ["config", "security", "api"]

    @pytest.mark.asyncio
    async def test_weight_ordering_same_phase(self):
        lm = LifecycleManager()
        order = []

        @lm.on_startup(phase=LifecyclePhase.SERVICES, weight=90)
        async def s3():
            order.append("s3")

        @lm.on_startup(phase=LifecyclePhase.SERVICES, weight=10)
        async def s1():
            order.append("s1")

        @lm.on_startup(phase=LifecyclePhase.SERVICES, weight=50)
        async def s2():
            order.append("s2")

        await lm.start()
        assert order == ["s1", "s2", "s3"]

    @pytest.mark.asyncio
    async def test_critical_hook_failure(self):
        lm = LifecycleManager()

        @lm.on_startup(name="bad", critical=True)
        async def bad():
            raise RuntimeError("boom")

        @lm.on_startup(name="after", phase=LifecyclePhase.API)
        async def after():
            pass

        report = await lm.start()
        assert report.overall_status == ComponentStatus.UNHEALTHY
        assert report.components["bad"].status == ComponentStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_noncritical_hook_failure(self):
        lm = LifecycleManager()
        ran = []

        @lm.on_startup(name="bad", critical=False)
        async def bad():
            raise RuntimeError("boom")

        @lm.on_startup(name="after", phase=LifecyclePhase.API)
        async def after():
            ran.append("after")

        report = await lm.start()
        assert ran == ["after"]
        assert report.overall_status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_hook_timeout(self):
        lm = LifecycleManager()

        @lm.on_startup(name="slow", timeout_seconds=0.01)
        async def slow():
            await asyncio.sleep(99)

        report = await lm.start()
        assert report.overall_status == ComponentStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_hook_retries_succeed(self):
        lm = LifecycleManager()
        attempts = []

        @lm.on_startup(name="retry", retries=2, retry_delay=0.01)
        async def retry():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("fail")

        report = await lm.start()
        assert len(attempts) == 3
        assert report.overall_status == ComponentStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_hook_retries_exhausted(self):
        lm = LifecycleManager()

        @lm.on_startup(name="retry", retries=1, retry_delay=0.01, critical=True)
        async def retry():
            raise RuntimeError("always fail")

        report = await lm.start()
        assert report.overall_status == ComponentStatus.UNHEALTHY


class TestLifecycleManagerShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_reverse_order(self):
        lm = LifecycleManager()
        order = []

        @lm.on_shutdown(name="a")
        async def a():
            order.append("a")

        @lm.on_shutdown(name="b")
        async def b():
            order.append("b")

        @lm.on_shutdown(name="c")
        async def c():
            order.append("c")

        report = await lm.shutdown()
        assert order == ["c", "b", "a"]
        assert report.overall_status == ComponentStatus.STOPPED

    @pytest.mark.asyncio
    async def test_shutdown_sync_hook(self):
        lm = LifecycleManager()
        ran = []

        @lm.on_shutdown(name="sync")
        def sync():
            ran.append(1)

        await lm.shutdown()
        assert ran == [1]

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self):
        lm = LifecycleManager()
        count = 0

        @lm.on_shutdown(name="x")
        async def x():
            nonlocal count
            count += 1

        await lm.shutdown()
        await lm.shutdown()
        assert count == 1

    @pytest.mark.asyncio
    async def test_shutdown_after_start_stops(self):
        lm = LifecycleManager()

        @lm.on_shutdown(name="close")
        async def close():
            pass

        await lm.start()
        report = await lm.shutdown()
        assert report.overall_status == ComponentStatus.STOPPED
        assert lm.is_live() is False


class TestLifecycleManagerProbes:
    def test_initial_probes(self):
        lm = LifecycleManager()
        assert lm.is_ready() is False
        assert lm.is_live() is True

    @pytest.mark.asyncio
    async def test_ready_after_start(self):
        lm = LifecycleManager()
        await lm.start()
        assert lm.is_ready() is True
        assert lm.is_live() is True

    @pytest.mark.asyncio
    async def test_not_ready_before_start(self):
        lm = LifecycleManager()

        @lm.on_startup(name="s1")
        async def s1():
            pass

        assert lm.is_ready() is False

    @pytest.mark.asyncio
    async def test_live_after_startup_failure(self):
        lm = LifecycleManager()

        @lm.on_startup(name="bad", critical=True)
        async def bad():
            raise RuntimeError("fail")

        await lm.start()
        assert lm.is_ready() is False
        assert lm.is_live() is False


class TestLifecycleManagerContext:
    @pytest.mark.asyncio
    async def test_context_manager(self):
        ran_start = False
        ran_stop = False

        lm = LifecycleManager()

        @lm.on_startup(name="s")
        async def s():
            nonlocal ran_start
            ran_start = True

        @lm.on_shutdown(name="close")
        async def close():
            nonlocal ran_stop
            ran_stop = True

        async with lm:
            assert ran_start is True
            assert ran_stop is False

        assert ran_stop is True


class TestLifecycleManagerReport:
    @pytest.mark.asyncio
    async def test_report_after_start(self):
        lm = LifecycleManager()

        @lm.on_startup(name="db")
        async def db():
            pass

        report = await lm.start()
        assert report.overall_status == ComponentStatus.HEALTHY
        assert "db" in report.components
        assert report.components["db"].status == ComponentStatus.HEALTHY
        assert report.startup_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_report_after_shutdown(self):
        lm = LifecycleManager()
        report = await lm.shutdown()
        assert report.overall_status == ComponentStatus.STOPPED
        assert report.components == {}


# ============================================================================
# get_lifecycle singleton
# ============================================================================


class TestGetLifecycle:
    def test_singleton(self):
        lm1 = get_lifecycle()
        lm2 = get_lifecycle()
        assert lm1 is lm2

    def test_initial_status(self):
        import agentos.core.lifecycle as lc
        lc._default_lifecycle = None
        lm = get_lifecycle()
        assert lm.is_ready() is False
        assert lm.is_live() is True
