"""Tests for agentos.core.health — health check with dependency probes."""

import asyncio
import time

import pytest

from agentos.core.health import (
    ComponentHealth,
    HealthChecker,
    HealthReport,
)


class TestComponentHealth:
    def test_healthy(self):
        c = ComponentHealth(name="db", status="healthy", latency_ms=5.2)
        assert c.status == "healthy"
        assert c.latency_ms == 5.2
        assert c.error is None

    def test_unhealthy_with_error(self):
        c = ComponentHealth(name="redis", status="unhealthy", latency_ms=100.0, error="timeout")
        assert c.error == "timeout"


class TestHealthReport:
    def test_healthy(self):
        r = HealthReport(status="healthy", uptime_seconds=3600.0)
        assert r.status == "healthy"
        assert r.components == {}

    def test_with_components(self):
        r = HealthReport(
            status="degraded", uptime_seconds=10.0,
            components={"db": ComponentHealth("db", "healthy", 1.0)}
        )
        assert r.components["db"].status == "healthy"


class TestHealthChecker:
    @pytest.mark.asyncio
    async def test_disk_probe_only(self):
        """With no db/redis config, only disk probe runs."""
        checker = HealthChecker(start_time=time.time())
        report = await checker.check()
        assert report.status == "healthy"
        assert "disk" in report.components
        assert report.components["disk"].status == "healthy"

    @pytest.mark.asyncio
    async def test_uptime(self):
        checker = HealthChecker(start_time=time.time() - 100)
        report = await checker.check()
        assert report.uptime_seconds >= 100

    @pytest.mark.asyncio
    async def test_timestamp(self):
        checker = HealthChecker(start_time=time.time())
        report = await checker.check()
        assert report.timestamp > 0

    @pytest.mark.asyncio
    async def test_degraded_when_one_fails(self):
        """Configure a fake db_url that will fail — degraded overall."""
        checker = HealthChecker(
            start_time=time.time(),
            db_url="postgresql+asyncpg://nonexistent:5432/db",
        )
        report = await checker.check()
        assert report.status in ("degraded", "unhealthy")
        assert "database" in report.components

    @pytest.mark.asyncio
    async def test_probe_timeout(self):
        """Probe that exceeds timeout returns unhealthy."""
        checker = HealthChecker(start_time=time.time())

        async def slow():
            await asyncio.sleep(10)

        result = await checker._probe("slow", slow, timeout=0.1)
        assert result.status == "unhealthy"
        assert "Timeout" in (result.error or "")

    @pytest.mark.asyncio
    async def test_probe_exception(self):
        checker = HealthChecker(start_time=time.time())

        async def failing():
            raise RuntimeError("boom")

        result = await checker._probe("bad", failing, timeout=1.0)
        assert result.status == "unhealthy"
        assert "boom" in (result.error or "")
