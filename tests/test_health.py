"""Tests for agentos.health module."""

from unittest.mock import MagicMock

from agentos.health import (
    CheckResult,
    HealthCheck,
    HealthChecker,
    HealthStatus,
    check_disk_space,
    check_memory,
    check_openai_connectivity,
    check_vectorstore_health,
    create_default_health_checker,
)


class TestHealthStatus:
    def test_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_str(self):
        assert str(HealthStatus.HEALTHY) == "HealthStatus.HEALTHY"


class TestHealthCheck:
    def test_attributes(self):
        hc = HealthCheck(name="disk", check_fn=lambda: True, timeout_seconds=3.0, description="desc")
        assert hc.name == "disk"
        assert hc.timeout_seconds == 3.0
        assert hc.description == "desc"
        assert hc.check_fn() is True

    def test_defaults(self):
        hc = HealthCheck(name="mem", check_fn=lambda: False)
        assert hc.timeout_seconds == 5.0
        assert hc.description == ""


class TestCheckResult:
    def test_fields(self):
        cr = CheckResult(name="disk", status=HealthStatus.HEALTHY, latency_ms=1.5, message="ok")
        assert cr.name == "disk"
        assert cr.status == HealthStatus.HEALTHY
        assert cr.latency_ms == 1.5
        assert cr.message == "ok"

    def test_to_dict(self):
        cr = CheckResult(name="disk", status=HealthStatus.DEGRADED, latency_ms=2.34, message="slow")
        d = cr.to_dict()
        assert d["name"] == "disk"
        assert d["status"] == "degraded"
        assert d["latency_ms"] == 2.34
        assert d["message"] == "slow"


class TestHealthChecker:
    def test_add_readiness_and_run(self):
        hc = HealthChecker()
        hc.add_readiness(HealthCheck("r1", lambda: True))
        result = hc.readiness()
        assert result["status"] == "healthy"
        assert len(result["checks"]) == 1
        assert result["checks"][0]["name"] == "r1"

    def test_add_liveness_and_run(self):
        hc = HealthChecker()
        hc.add_liveness(HealthCheck("l1", lambda: False))
        result = hc.liveness()
        assert result["status"] == "unhealthy"

    def test_readiness_unhealthy_propagates(self):
        hc = HealthChecker()
        hc.add_readiness(HealthCheck("r1", lambda: True))
        hc.add_readiness(HealthCheck("r2", lambda: False))
        result = hc.readiness()
        assert result["status"] == "unhealthy"

    def test_readiness_degraded(self):
        hc = HealthChecker()
        hc.add_readiness(HealthCheck("r1", lambda: False))
        hc.add_readiness(HealthCheck("r2", lambda: False))
        result = hc.readiness()
        assert result["status"] == "unhealthy"

    def test_liveness_exception_becomes_unhealthy(self):
        hc = HealthChecker()
        hc.add_liveness(HealthCheck("fail", lambda: 1 / 0))
        result = hc.liveness()
        assert result["status"] == "unhealthy"
        assert "division by zero" in result["checks"][0]["message"]

    def test_all_combined(self):
        hc = HealthChecker()
        hc.add_readiness(HealthCheck("ready", lambda: True))
        hc.add_liveness(HealthCheck("live", lambda: True))
        result = hc.all()
        assert result["status"] == "healthy"
        assert "readiness" in result
        assert "liveness" in result

    def test_all_unhealthy_when_liveness_fails(self):
        hc = HealthChecker()
        hc.add_readiness(HealthCheck("ready", lambda: True))
        hc.add_liveness(HealthCheck("live", lambda: False))
        result = hc.all()
        assert result["status"] == "unhealthy"

    def test_empty_checker(self):
        hc = HealthChecker()
        assert hc.readiness()["status"] == "healthy"
        assert hc.liveness()["status"] == "healthy"

    def test_results_include_latency(self):
        hc = HealthChecker()
        hc.add_readiness(HealthCheck("r1", lambda: True))
        result = hc.readiness()
        assert result["checks"][0]["latency_ms"] >= 0


class TestBuiltinChecks:
    def test_check_disk_space_returns_healthcheck(self):
        hc = check_disk_space(threshold_bytes=1)
        assert isinstance(hc, HealthCheck)
        assert hc.name == "disk-space"
        assert hc.check_fn() is True  # should have >1 byte free

    def test_check_memory_returns_healthcheck(self):
        hc = check_memory(threshold_bytes=1)
        assert isinstance(hc, HealthCheck)
        assert hc.name == "memory"
        assert hc.check_fn() is True

    def test_check_openai_connectivity(self):
        hc = check_openai_connectivity()
        assert isinstance(hc, HealthCheck)
        assert hc.name == "openai-connectivity"

    def test_check_vectorstore_health_no_instance(self):
        hc = check_vectorstore_health(db_instance=None)
        assert hc.check_fn() is False

    def test_check_vectorstore_health_healthy(self):
        mock_db = MagicMock()
        mock_db.is_healthy.return_value = True
        hc = check_vectorstore_health(db_instance=mock_db)
        assert hc.check_fn() is True
        mock_db.is_healthy.assert_called_once()


class TestCreateDefaultHealthChecker:
    def test_returns_health_checker(self):
        hc = create_default_health_checker()
        assert isinstance(hc, HealthChecker)

    def test_has_liveness_and_readiness(self):
        hc = create_default_health_checker()
        live = hc.liveness()
        ready = hc.readiness()
        assert len(live["checks"]) >= 1
        assert len(ready["checks"]) >= 1
