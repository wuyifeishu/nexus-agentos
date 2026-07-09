"""
Production health check with dependency liveness probes.

Extends the basic health endpoint with:
- Database connectivity check (async)
- Redis connectivity check (async)
- Component-level health status

Usage:
    from agentos.core.health import HealthChecker
    checker = HealthChecker(db_url="...", redis_url="...")
    status = await checker.check()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ComponentHealth:
    name: str
    status: str  # "healthy" | "degraded" | "unhealthy"
    latency_ms: float
    error: str | None = None


@dataclass
class HealthReport:
    status: str  # "healthy" | "degraded" | "unhealthy"
    uptime_seconds: float
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class HealthChecker:
    """Async health checker with component-level probing."""

    def __init__(
        self,
        start_time: float,
        db_url: str | None = None,
        redis_url: str | None = None,
    ):
        self.start_time = start_time
        self.db_url = db_url
        self.redis_url = redis_url

    async def _probe(self, name: str, check_fn, timeout: float = 3.0) -> ComponentHealth:
        """Run a single component health probe with timeout."""
        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(check_fn(), timeout=timeout)
            latency = (time.perf_counter() - t0) * 1000
            return ComponentHealth(name=name, status="healthy", latency_ms=latency)
        except TimeoutError:
            latency = (time.perf_counter() - t0) * 1000
            return ComponentHealth(
                name=name, status="unhealthy", latency_ms=latency, error=f"Timeout after {timeout}s"
            )
        except Exception as e:
            latency = (time.perf_counter() - t0) * 1000
            return ComponentHealth(name=name, status="unhealthy", latency_ms=latency, error=str(e))

    async def check(self) -> HealthReport:
        """Run a full health check across all configured components."""
        probes = []

        # DB probe
        if self.db_url:
            probes.append(self._probe("database", self._check_db))

        # Redis probe
        if self.redis_url:
            probes.append(self._probe("redis", self._check_redis))

        # Always probe disk (write test)
        probes.append(self._probe("disk", self._check_disk))

        results = await asyncio.gather(*probes, return_exceptions=True)

        components: dict[str, ComponentHealth] = {}
        overall = "healthy"

        for r in results:
            if isinstance(r, ComponentHealth):
                components[r.name] = r
                if r.status == "unhealthy":
                    if overall == "healthy":
                        overall = "degraded"
                elif r.status == "degraded" and overall == "healthy":
                    overall = "degraded"
            elif isinstance(r, Exception):
                # Probe itself crashed
                components["internal"] = ComponentHealth(
                    name="internal", status="unhealthy", latency_ms=0, error=str(r)
                )
                overall = "unhealthy"

        return HealthReport(
            status=overall,
            uptime_seconds=time.time() - self.start_time,
            components=components,
        )

    async def _check_db(self):
        """Database connectivity probe."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(self.db_url, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()

    async def _check_redis(self):
        """Redis connectivity probe."""
        import redis.asyncio as redis

        r = redis.from_url(self.redis_url)
        await r.ping()
        await r.close()

    async def _check_disk(self):
        """Filesystem write test."""
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, prefix="health_", suffix=".tmp") as f:
            f.write(b"ok")

        try:
            os.unlink(f.name)
        except OSError:
            pass


__all__ = ["HealthChecker", "HealthReport", "ComponentHealth"]
