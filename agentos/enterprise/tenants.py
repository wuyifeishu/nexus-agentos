"""
AgentOS Enterprise — Multi-Tenant Management.

功能：
  - 租户创建/启停/删除
  - 租户级配额管理（API 调用数、Token 数、并发数）
  - 租户隔离（数据/配置/Agent 命名空间）
  - 用量追踪与超限拦截
  - 租户级自定义配置
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class TenantTier(StrEnum):
    """租户等级。"""

    FREE = "free"  # 100 调用/天, 1 并发
    STARTER = "starter"  # 1000 调用/天, 3 并发
    PRO = "pro"  # 10000 调用/天, 10 并发
    ENTERPRISE = "enterprise"  # 自定义


TIER_QUOTAS = {
    TenantTier.FREE: {
        "daily_api_calls": 100,
        "daily_tokens": 100_000,
        "max_concurrency": 1,
        "max_agents": 3,
        "max_api_keys": 2,
    },
    TenantTier.STARTER: {
        "daily_api_calls": 1_000,
        "daily_tokens": 1_000_000,
        "max_concurrency": 3,
        "max_agents": 10,
        "max_api_keys": 5,
    },
    TenantTier.PRO: {
        "daily_api_calls": 10_000,
        "daily_tokens": 10_000_000,
        "max_concurrency": 10,
        "max_agents": 50,
        "max_api_keys": 20,
    },
    TenantTier.ENTERPRISE: {
        "daily_api_calls": 1_000_000,
        "daily_tokens": 1_000_000_000,
        "max_concurrency": 100,
        "max_agents": 500,
        "max_api_keys": 100,
    },
}


@dataclass
class TenantConfig:
    """租户级配置覆盖。"""

    default_model: str = "gpt-4o-mini"
    default_provider: str = "openai"
    allowed_providers: list[str] = field(
        default_factory=lambda: ["openai", "deepseek", "anthropic"]
    )
    max_iterations: int = 10
    guardrail_level: str = "standard"  # none / standard / strict
    custom_settings: dict = field(default_factory=dict)


@dataclass
class TenantUsage:
    """租户用量统计（当日）。"""

    tenant_id: str
    date: str  # YYYY-MM-DD
    api_calls: int = 0
    tokens_used: int = 0
    current_concurrency: int = 0
    last_updated: float = field(default_factory=time.time)


@dataclass
class Tenant:
    """租户实体。"""

    tenant_id: str
    name: str
    tier: TenantTier
    status: TenantStatus = TenantStatus.ACTIVE
    config: TenantConfig = field(default_factory=TenantConfig)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)
    # 自定义配额覆盖（仅 Enterprise 级别可用）
    custom_quotas: dict = field(default_factory=dict)


class TenantManager:
    """多租户管理器。

    特性：
      - 租户 CRUD + 启停
      - 等级配额自动分配
      - 用量追踪 + 超限拦截
      - 租户级配置隔离
      - 每日用量自动重置
    """

    def __init__(self):
        self._tenants: dict[str, Tenant] = {}
        self._usage: dict[str, TenantUsage] = {}  # tenant_id → usage

    # ── 租户管理 ──

    def create_tenant(
        self,
        name: str,
        tier: TenantTier = TenantTier.FREE,
        config: TenantConfig | None = None,
        metadata: dict = None,
    ) -> Tenant:
        """创建租户。"""
        import uuid

        tenant_id = f"tn_{uuid.uuid4().hex[:12]}"
        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            tier=tier,
            config=config or TenantConfig(),
            metadata=metadata or {},
        )
        self._tenants[tenant_id] = tenant
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def list_tenants(self, status: TenantStatus | None = None) -> list[Tenant]:
        tenants = list(self._tenants.values())
        if status:
            tenants = [t for t in tenants if t.status == status]
        return sorted(tenants, key=lambda t: t.created_at)

    def update_tenant(self, tenant_id: str, **kwargs) -> Tenant | None:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return None
        for k, v in kwargs.items():
            if hasattr(tenant, k):
                setattr(tenant, k, v)
        tenant.updated_at = time.time()
        return tenant

    def suspend_tenant(self, tenant_id: str) -> bool:
        t = self._tenants.get(tenant_id)
        if not t:
            return False
        t.status = TenantStatus.SUSPENDED
        t.updated_at = time.time()
        return True

    def activate_tenant(self, tenant_id: str) -> bool:
        t = self._tenants.get(tenant_id)
        if not t:
            return False
        t.status = TenantStatus.ACTIVE
        t.updated_at = time.time()
        return True

    def delete_tenant(self, tenant_id: str) -> bool:
        t = self._tenants.get(tenant_id)
        if not t:
            return False
        t.status = TenantStatus.DELETED
        t.updated_at = time.time()
        return True

    # ── 配额 ──

    def get_quotas(self, tenant_id: str) -> dict:
        """获取租户当前有效配额。"""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return {}
        base = dict(TIER_QUOTAS.get(tenant.tier, {}))
        base.update(tenant.custom_quotas)
        return base

    def check_quota(self, tenant_id: str, resource: str, amount: int = 1) -> tuple[bool, str]:
        """检查配额是否允许此次操作。返回 (允许, 原因)。"""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False, "租户不存在"
        if tenant.status != TenantStatus.ACTIVE:
            return False, f"租户状态: {tenant.status.value}"

        quotas = self.get_quotas(tenant_id)
        limit = quotas.get(resource)

        if limit is None:
            return True, ""

        usage = self._get_usage(tenant_id)
        current = getattr(usage, resource, 0)

        if current + amount > limit:
            return False, f"超出配额: {resource} ({current}/{limit})"

        return True, ""

    # ── 用量追踪 ──

    def record_usage(
        self, tenant_id: str, api_calls: int = 0, tokens: int = 0, concurrency_delta: int = 0
    ):
        """记录一次用量。"""
        if not self._tenants.get(tenant_id):
            return
        usage = self._get_usage(tenant_id)
        usage.api_calls += api_calls
        usage.tokens_used += tokens
        usage.current_concurrency = max(0, usage.current_concurrency + concurrency_delta)
        usage.last_updated = time.time()

    def get_usage(self, tenant_id: str) -> TenantUsage | None:
        return self._get_usage(tenant_id)

    def reset_daily_usage(self, tenant_id: str = None):
        """重置每日用量（定时任务调用）。"""
        if tenant_id:
            self._usage.pop(tenant_id, None)
        else:
            self._usage.clear()

    # ── 统计 ──

    def stats(self) -> dict:
        total = len(self._tenants)
        by_tier = {}
        by_status = {}
        for t in self._tenants.values():
            by_tier[t.tier.value] = by_tier.get(t.tier.value, 0) + 1
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
        return {
            "total": total,
            "by_tier": by_tier,
            "by_status": by_status,
        }

    # ── 内部 ──

    def _get_usage(self, tenant_id: str) -> TenantUsage:
        today = time.strftime("%Y-%m-%d")
        key = f"{tenant_id}:{today}"
        if key not in self._usage:
            self._usage[key] = TenantUsage(tenant_id=tenant_id, date=today)
        return self._usage[key]
