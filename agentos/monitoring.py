from dataclasses import dataclass
from enum import Enum


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertState(Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"


@dataclass
class AlertRule:
    name: str = ""


class Alert:
    pass


class AlertEvaluator:
    pass


@dataclass
class MonitoringConfig:
    enabled: bool = True


@dataclass
class WebhookConfig:
    url: str = ""


@dataclass
class WebhookDispatcher:
    pass
