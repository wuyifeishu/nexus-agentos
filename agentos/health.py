from dataclasses import dataclass
from enum import Enum


class HealthStatus(Enum):
    HEALTHY = "healthy"


@dataclass
class CheckResult:
    status: HealthStatus = HealthStatus.HEALTHY


class HealthCheck:
    pass


class HealthChecker:
    pass
