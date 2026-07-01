"""AgentOS monitoring — alert rules and webhook notification dispatcher."""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class AlertSeverity(str, Enum):
    """告警实例。"""

    """告警严重级别。"""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertState(str, Enum):

    """告警状态。"""

    FIRING = "firing"
    RESOLVED = "resolved"


@dataclass
class AlertRule:
    """告警规则。"""
    name: str
    description: str
    severity: AlertSeverity = AlertSeverity.WARNING
    condition: Optional[Callable[[], bool]] = None
    cooldown_seconds: int = 300
    _last_fired: float = field(default=0.0, repr=False)

    def evaluate(self) -> bool:
        if not self.condition:
            return False
        now = time.time()
        if now - self._last_fired < self.cooldown_seconds:
            return False
        result = self.condition()
        if result:
            self._last_fired = now
        return result


@dataclass
class Alert:
    rule_name: str
    severity: AlertSeverity
    message: str
    state: AlertState = AlertState.FIRING
    timestamp: float = field(default_factory=time.time)
    labels: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "message": self.message,
            "state": self.state.value,
            "timestamp": self.timestamp,
            "labels": self.labels,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class MonitoringConfig:
    """监控配置。"""
    enabled: bool = True
    evaluation_interval: int = 60
    max_alerts_per_interval: int = 10


@dataclass
class WebhookConfig:
    """Webhook 配置。"""
    url: str = ""
    method: str = "POST"
    headers: dict = field(default_factory=dict)
    timeout: float = 5.0
    retry_count: int = 3


class WebhookDispatcher:
    """Dispatches Alerts to configured webhook endpoints."""

    def __init__(self, config: Optional[WebhookConfig] = None):
        self.config = config or WebhookConfig()

    def send(self, alert: Alert) -> bool:
        if not self.config.url:
            return False
        payload = json.dumps(alert.to_dict()).encode("utf-8")
        for attempt in range(self.config.retry_count + 1):
            try:
                req = urllib.request.Request(
                    self.config.url,
                    data=payload,
                    headers=self.config.headers,
                    method=self.config.method,
                )
                with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                    return resp.status < 400
            except Exception:
                if attempt == self.config.retry_count:
                    return False
                time.sleep(1.0 * (attempt + 1))
        return False


class AlertEvaluator:
    """Evaluates AlertRules and generates Alerts."""

    def __init__(self, config: Optional[MonitoringConfig] = None):
        self.config = config or MonitoringConfig()
        self.rules: list[AlertRule] = []

    def add_rule(self, rule: AlertRule):
        self.rules.append(rule)

    def evaluate(self) -> list[Alert]:
        if not self.config.enabled:
            return []
        alerts: list[Alert] = []
        count = 0
        for rule in self.rules:
            if count >= self.config.max_alerts_per_interval:
                break
            if rule.evaluate():
                alerts.append(Alert(
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=f"Alert: {rule.description}",
                ))
                count += 1
        return alerts
