"""
AgentOS Enterprise — Audit Logging.

功能：
  - 全量审计事件记录
  - 事件分类（认证/操作/数据/系统）
  - 可配置保留策略
  - 合规报告导出（CSV/JSON）
  - GDPR/CCPA 数据删除支持
"""

from __future__ import annotations

import csv
import io
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class AuditCategory(StrEnum):
    """审计事件分类。"""

    AUTH = "auth"  # 登录/登出/Token
    API_KEY = "api_key"  # Key 创建/撤销/轮转
    AGENT = "agent"  # Agent 创建/运行/删除
    TENANT = "tenant"  # 租户管理
    CONFIG = "config"  # 配置变更
    SYSTEM = "system"  # 系统事件
    DATA = "data"  # 数据访问/导出
    SECURITY = "security"  # 安全事件（违规/攻击）


class AuditSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """一条审计事件。"""

    event_id: str
    timestamp: float
    category: AuditCategory
    action: str  # 如 "api_key.created", "agent.run"
    severity: AuditSeverity
    actor_type: str  # "user" / "agent" / "system" / "api_key"
    actor_id: str  # user_id / agent_id / key_id
    tenant_id: str
    resource_type: str  # "agent" / "api_key" / "tenant" / ...
    resource_id: str
    ip_address: str
    user_agent: str
    status: str  # "success" / "failure"
    details: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class RetentionPolicy:
    """审计日志保留策略。"""

    max_events: int = 100_000  # 最大事件数
    max_age_days: int = 90  # 最大保留天数
    auto_prune: bool = True  # 是否自动清理过期事件


class AuditLogger:
    """审计日志引擎。

    特性：
      - 全量事件记录
      - 内存 + 文件双存储模式
      - 可配置保留策略
      - 过滤/搜索/导出
      - 合规支持（GDPR 数据删除）
    """

    def __init__(self, retention: RetentionPolicy = None):
        self._events: list[AuditEvent] = []
        self.retention = retention or RetentionPolicy()

    # ── 记录 ──

    def log(
        self,
        category: AuditCategory,
        action: str,
        severity: AuditSeverity = AuditSeverity.INFO,
        actor_type: str = "system",
        actor_id: str = "",
        tenant_id: str = "",
        resource_type: str = "",
        resource_id: str = "",
        ip_address: str = "",
        user_agent: str = "",
        status: str = "success",
        details: dict = None,
        metadata: dict = None,
    ) -> AuditEvent:
        """记录一条审计事件。"""
        event = AuditEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            category=category,
            action=action,
            severity=severity,
            actor_type=actor_type,
            actor_id=actor_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            status=status,
            details=details or {},
            metadata=metadata or {},
        )
        self._events.append(event)

        # 自动清理
        if self.retention.auto_prune:
            self._prune()

        return event

    def log_auth(
        self,
        action: str,
        user_id: str,
        tenant_id: str,
        status: str,
        ip: str = "",
        ua: str = "",
        **kwargs,
    ):
        """便捷：记录认证事件。"""
        return self.log(
            category=AuditCategory.AUTH,
            action=action,
            actor_type="user",
            actor_id=user_id,
            tenant_id=tenant_id,
            resource_type="session",
            resource_id=user_id,
            ip_address=ip,
            user_agent=ua,
            status=status,
            details=kwargs,
        )

    def log_api_key(self, action: str, key_id: str, tenant_id: str, actor_id: str, **kwargs):
        """便捷：记录 API Key 事件。"""
        return self.log(
            category=AuditCategory.API_KEY,
            action=action,
            severity=AuditSeverity.WARNING if action.endswith(".revoked") else AuditSeverity.INFO,
            actor_type="user",
            actor_id=actor_id,
            tenant_id=tenant_id,
            resource_type="api_key",
            resource_id=key_id,
            details=kwargs,
        )

    def log_agent_run(self, agent_id: str, tenant_id: str, status: str, **kwargs):
        """便捷：记录 Agent 运行事件。"""
        return self.log(
            category=AuditCategory.AGENT,
            action="agent.run",
            actor_type="agent",
            actor_id=agent_id,
            tenant_id=tenant_id,
            resource_type="agent",
            resource_id=agent_id,
            status=status,
            details=kwargs,
        )

    def log_security(self, action: str, severity: AuditSeverity, details: dict, **kwargs):
        """便捷：记录安全事件。"""
        return self.log(
            category=AuditCategory.SECURITY,
            action=action,
            severity=severity,
            actor_type=kwargs.pop("actor_type", "system"),
            actor_id=kwargs.pop("actor_id", ""),
            tenant_id=kwargs.pop("tenant_id", ""),
            resource_type=kwargs.pop("resource_type", ""),
            resource_id=kwargs.pop("resource_id", ""),
            details=details,
            **kwargs,
        )

    # ── 查询 ──

    def query(
        self,
        category: AuditCategory | None = None,
        severity: AuditSeverity | None = None,
        tenant_id: str | None = None,
        actor_id: str | None = None,
        status: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """多条件过滤查询。"""
        results = self._events

        if category:
            results = [e for e in results if e.category == category]
        if severity:
            results = [e for e in results if e.severity == severity]
        if tenant_id:
            results = [e for e in results if e.tenant_id == tenant_id]
        if actor_id:
            results = [e for e in results if e.actor_id == actor_id]
        if status:
            results = [e for e in results if e.status == status]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]

        return sorted(results, key=lambda e: e.timestamp, reverse=True)[:limit]

    def get_recent(self, n: int = 50) -> list[AuditEvent]:
        """最近 N 条事件。"""
        return sorted(self._events, key=lambda e: e.timestamp, reverse=True)[:n]

    # ── 导出 ──

    def export_json(self, events: list[AuditEvent] = None) -> str:
        """导出为 JSON 字符串。"""
        target = events or self._events
        return json.dumps(
            [_event_to_dict(e) for e in target],
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    def export_csv(self, events: list[AuditEvent] = None) -> str:
        """导出为 CSV 字符串。"""
        target = events or self._events
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "event_id",
                "timestamp",
                "category",
                "action",
                "severity",
                "actor_type",
                "actor_id",
                "tenant_id",
                "resource_type",
                "resource_id",
                "ip_address",
                "status",
                "details",
            ],
        )
        writer.writeheader()
        for e in target:
            writer.writerow(
                {
                    "event_id": e.event_id,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e.timestamp)),
                    "category": e.category.value,
                    "action": e.action,
                    "severity": e.severity.value,
                    "actor_type": e.actor_type,
                    "actor_id": e.actor_id,
                    "tenant_id": e.tenant_id,
                    "resource_type": e.resource_type,
                    "resource_id": e.resource_id,
                    "ip_address": e.ip_address,
                    "status": e.status,
                    "details": json.dumps(e.details, ensure_ascii=False),
                }
            )
        return output.getvalue()

    # ── 合规 ──

    def delete_user_data(self, user_id: str) -> int:
        """GDPR / CCPA：删除指定用户相关的所有审计记录。返回删除条数。"""
        before = len(self._events)
        self._events = [e for e in self._events if e.actor_id != user_id]
        return before - len(self._events)

    def compliance_report(self, tenant_id: str, start: float, end: float) -> dict:
        """生成合规报告摘要。"""
        events = self.query(tenant_id=tenant_id, since=start, until=end, limit=10000)
        by_category = {}
        by_severity = {}
        failure_count = 0
        for e in events:
            by_category[e.category.value] = by_category.get(e.category.value, 0) + 1
            by_severity[e.severity.value] = by_severity.get(e.severity.value, 0) + 1
            if e.status == "failure":
                failure_count += 1
        return {
            "tenant_id": tenant_id,
            "period": {
                "start": time.strftime("%Y-%m-%d", time.gmtime(start)),
                "end": time.strftime("%Y-%m-%d", time.gmtime(end)),
            },
            "total_events": len(events),
            "by_category": by_category,
            "by_severity": by_severity,
            "failure_rate": f"{failure_count / len(events) * 100:.1f}%" if events else "0%",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    # ── 统计 ──

    def stats(self) -> dict:
        total = len(self._events)
        by_category = {}
        by_severity = {}
        for e in self._events:
            by_category[e.category.value] = by_category.get(e.category.value, 0) + 1
            by_severity[e.severity.value] = by_severity.get(e.severity.value, 0) + 1
        return {
            "total_events": total,
            "by_category": by_category,
            "by_severity": by_severity,
            "retention_policy": {
                "max_events": self.retention.max_events,
                "max_age_days": self.retention.max_age_days,
            },
        }

    # ── 内部 ──

    def _prune(self):
        """按保留策略清理过期事件。"""
        # 按数量
        if len(self._events) > self.retention.max_events:
            self._events = self._events[-self.retention.max_events :]

        # 按时间
        cutoff = time.time() - self.retention.max_age_days * 86400
        self._events = [e for e in self._events if e.timestamp > cutoff]


def _event_to_dict(e: AuditEvent) -> dict:
    return {
        "event_id": e.event_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e.timestamp)),
        "category": e.category.value,
        "action": e.action,
        "severity": e.severity.value,
        "actor_type": e.actor_type,
        "actor_id": e.actor_id,
        "tenant_id": e.tenant_id,
        "resource_type": e.resource_type,
        "resource_id": e.resource_id,
        "ip_address": e.ip_address,
        "user_agent": e.user_agent,
        "status": e.status,
        "details": e.details,
        "metadata": e.metadata,
    }
