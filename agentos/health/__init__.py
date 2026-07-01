"""AgentOS health checks — readiness, liveness, and dependency probes.

Provides standard health-check endpoints for Kubernetes, Docker, and load balancers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class HealthStatus(Enum):

    """健康状态枚举。"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheck:
    """健康检查定义。"""
    name: str
    check_fn: Callable[[], bool]
    timeout_seconds: float = 5.0
    description: str = ""


@dataclass
class CheckResult:
    """检查结果。"""
    name: str
    status: HealthStatus
    latency_ms: float
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "message": self.message,
        }


class HealthChecker:
    """Aggregate readiness and liveness checks."""

    def __init__(self):
        self._readiness_checks: list[HealthCheck] = []
        self._liveness_checks: list[HealthCheck] = []

    def add_readiness(self, check: HealthCheck):
        self._readiness_checks.append(check)

    def add_liveness(self, check: HealthCheck):
        self._liveness_checks.append(check)

    def _run_checks(self, checks: list[HealthCheck]) -> tuple[HealthStatus, list[CheckResult]]:
        results: list[CheckResult] = []
        overall = HealthStatus.HEALTHY
        for chk in checks:
            start = time.monotonic()
            try:
                ok = chk.check_fn()
            except Exception as e:
                ok = False
                msg = str(e)
            else:
                msg = "ok" if ok else "check returned False"
            latency = (time.monotonic() - start) * 1000
            status = HealthStatus.HEALTHY if ok else HealthStatus.UNHEALTHY
            if status == HealthStatus.UNHEALTHY and overall != HealthStatus.UNHEALTHY:
                overall = HealthStatus.DEGRADED
            if status == HealthStatus.UNHEALTHY:
                overall = HealthStatus.UNHEALTHY
            results.append(CheckResult(name=chk.name, status=status, latency_ms=latency, message=msg))
        return (overall, results)

    def readiness(self) -> dict:
        """Run all readiness checks.  Returns a dict suitable for a /health/ready endpoint."""
        overall, results = self._run_checks(self._readiness_checks)
        return {
            "status": overall.value,
            "timestamp": time.time(),
            "checks": [r.to_dict() for r in results],
        }

    def liveness(self) -> dict:
        """Run all liveness checks.  Returns a dict suitable for a /health/live endpoint."""
        overall, results = self._run_checks(self._liveness_checks)
        return {
            "status": overall.value,
            "timestamp": time.time(),
            "checks": [r.to_dict() for r in results],
        }

    def all(self) -> dict:
        """Combined readiness + liveness report, suitable for /health."""
        r = self.readiness()
        l = self.liveness()
        combined_status = HealthStatus.HEALTHY
        for s in (r["status"], l["status"]):
            if s == HealthStatus.UNHEALTHY.value:
                combined_status = HealthStatus.UNHEALTHY
                break
            if s == HealthStatus.DEGRADED.value:
                combined_status = HealthStatus.DEGRADED
        return {
            "status": combined_status.value,
            "timestamp": time.time(),
            "readiness": r,
            "liveness": l,
        }


# ── Built-in checks ───────────────────────────────────────────────────────────


def check_openai_connectivity(api_key: Optional[str] = None) -> HealthCheck:
    """Verify connectivity to the OpenAI API."""
    def _check() -> bool:
        try:
            import urllib.request
            req = urllib.request.Request("https://api.openai.com/v1/models", method="HEAD")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            return False
    return HealthCheck(name="openai-connectivity", check_fn=_check, timeout_seconds=5.0,
                       description="Check OpenAI API reachability")


def check_vectorstore_health(db_instance=None) -> HealthCheck:
    """Check vector store connection health."""
    def _check() -> bool:
        if db_instance is None:
            return False
        try:
            return hasattr(db_instance, "is_healthy") and db_instance.is_healthy()
        except Exception:
            return False
    return HealthCheck(name="vectorstore-health", check_fn=_check, timeout_seconds=5.0,
                       description="Check vector store connection")


def check_disk_space(threshold_bytes: int = 100 * 1024 * 1024) -> HealthCheck:
    """Check available disk space exceeds threshold (default 100MB)."""
    def _check() -> bool:
        import shutil
        usage = shutil.disk_usage("/")
        return usage.free >= threshold_bytes
    return HealthCheck(name="disk-space", check_fn=_check, timeout_seconds=1.0,
                       description=f"Free disk space >= {threshold_bytes/1024/1024:.0f}MB")


def check_memory(threshold_bytes: int = 50 * 1024 * 1024) -> HealthCheck:
    """Check available system memory exceeds threshold (default 50MB)."""
    def _check() -> bool:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        kb = int(line.split()[1])
                        return kb * 1024 >= threshold_bytes
        except Exception:
            return True  # can't check, assume OK
        return True
    return HealthCheck(name="memory", check_fn=_check, timeout_seconds=1.0,
                       description=f"Available memory >= {threshold_bytes/1024/1024:.0f}MB")


# ── Default health checker factory ────────────────────────────────────────────


def create_default_health_checker() -> HealthChecker:
    """Return a HealthChecker pre-loaded with sensible built-in checks."""
    hc = HealthChecker()
    hc.add_liveness(check_memory())
    hc.add_readiness(check_disk_space())
    return hc
