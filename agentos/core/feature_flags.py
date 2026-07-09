"""
AgentOS Feature Flags — Gradual Rollout & Experimentation Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Production-grade feature flag system with:
  - Percentage-based gradual rollout
  - User/tenant targeting (allowlist/blocklist)
  - Time-based scheduling (start/end dates)
  - Kill-switch for emergency disable
  - Audit trail for flag changes
  - Backend-agnostic storage (in-memory / Redis / DB)

Architecture:
  FlagStore (abstract)
    ├─ InMemoryFlagStore
    ├─ RedisFlagStore (coming)
    └─ DatabaseFlagStore (coming)

  FeatureFlagManager
    ├─ is_enabled(flag_name, context) → bool
    ├─ get_variant(flag_name, context) → str
    └─ set_flag(...) / delete_flag(...)
"""

from __future__ import annotations

import builtins
import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


class FlagType(StrEnum):
    """Type of feature flag."""

    BOOLEAN = "boolean"  # Simple on/off toggle
    PERCENTAGE = "percentage"  # Gradual rollout (0-100%)
    VARIANT = "variant"  # A/B test variants
    SCHEDULED = "scheduled"  # Time-based enable/disable


@dataclass
class FlagRule:
    """Targeting rule for a feature flag."""

    flag_type: FlagType = FlagType.BOOLEAN
    enabled: bool = False
    rollout_percentage: int = 0  # 0-100 for PERCENTAGE type
    variants: dict[str, int] = field(default_factory=dict)  # variant_name → weight
    allowlist_users: set[str] = field(default_factory=set)
    allowlist_tenants: set[str] = field(default_factory=set)
    blocklist_users: set[str] = field(default_factory=set)
    blocklist_tenants: set[str] = field(default_factory=set)
    start_time: datetime | None = None
    end_time: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag_type": self.flag_type.value,
            "enabled": self.enabled,
            "rollout_percentage": self.rollout_percentage,
            "variants": self.variants,
            "allowlist_users": list(self.allowlist_users),
            "allowlist_tenants": list(self.allowlist_tenants),
            "blocklist_users": list(self.blocklist_users),
            "blocklist_tenants": list(self.blocklist_tenants),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "metadata": self.metadata,
        }


@dataclass
class FlagContext:
    """Context for feature flag evaluation."""

    user_id: str | None = None
    tenant_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None


@dataclass
class FlagEvaluation:
    """Result of a feature flag evaluation."""

    flag_name: str
    enabled: bool
    variant: str | None = None
    reason: str = ""
    evaluated_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Flag Store Interface
# ---------------------------------------------------------------------------


class FlagStore(ABC):
    """Abstract storage backend for feature flags."""

    @abstractmethod
    async def get(self, flag_name: str) -> FlagRule | None:
        """Get a flag rule by name."""

    @abstractmethod
    async def set(self, flag_name: str, rule: FlagRule) -> None:
        """Set or update a flag rule."""

    @abstractmethod
    async def delete(self, flag_name: str) -> bool:
        """Delete a flag. Returns True if existed."""

    @abstractmethod
    async def list(self) -> builtins.list[str]:
        """List all flag names."""


class InMemoryFlagStore(FlagStore):
    """In-memory flag store for development and testing."""

    def __init__(self):
        self._flags: dict[str, FlagRule] = {}

    async def get(self, flag_name: str) -> FlagRule | None:
        return self._flags.get(flag_name)

    async def set(self, flag_name: str, rule: FlagRule) -> None:
        self._flags[flag_name] = rule

    async def delete(self, flag_name: str) -> bool:
        return self._flags.pop(flag_name, None) is not None

    async def list(self) -> builtins.list[str]:
        return list(self._flags.keys())


# ---------------------------------------------------------------------------
# Feature Flag Manager
# ---------------------------------------------------------------------------


class FeatureFlagManager:
    """
    Production feature flag manager.

    Supports:
      - Boolean toggles (on/off)
      - Percentage-based gradual rollout
      - A/B test variants
      - User/tenant targeting (allowlist/blocklist)
      - Time-based scheduling
      - Kill-switch (immediate disable)

    Usage:
        manager = FeatureFlagManager(InMemoryFlagStore())

        # Register a flag
        await manager.set_flag("new_search", FlagRule(
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            rollout_percentage=10,
        ))

        # Check in application code
        ctx = FlagContext(user_id="user_123", tenant_id="tenant_a")
        if await manager.is_enabled("new_search", ctx):
            use_new_search()
    """

    def __init__(self, store: FlagStore):
        self._store = store
        self._evaluation_log: list[FlagEvaluation] = []

    # ── Flag Management ────────────────────────────────────────────────

    async def set_flag(self, flag_name: str, rule: FlagRule) -> None:
        """Create or update a feature flag."""
        await self._store.set(flag_name, rule)

    async def delete_flag(self, flag_name: str) -> bool:
        """Delete a feature flag."""
        return await self._store.delete(flag_name)

    async def get_flag(self, flag_name: str) -> FlagRule | None:
        """Get a flag's rule."""
        return await self._store.get(flag_name)

    async def list_flags(self) -> list[str]:
        """List all registered flags."""
        return await self._store.list()

    async def kill_switch(self, flag_name: str) -> None:
        """Emergency disable a flag (kill-switch)."""
        rule = await self._store.get(flag_name)
        if rule:
            rule.enabled = False
            await self._store.set(flag_name, rule)

    # ── Flag Evaluation ────────────────────────────────────────────────

    async def is_enabled(self, flag_name: str, context: FlagContext | None = None) -> bool:
        """Check if a feature flag is enabled for the given context."""
        evaluation = await self.evaluate(flag_name, context)
        return evaluation.enabled

    async def get_variant(self, flag_name: str, context: FlagContext | None = None) -> str | None:
        """Get the variant name for an A/B test flag."""
        evaluation = await self.evaluate(flag_name, context)
        return evaluation.variant

    async def evaluate(self, flag_name: str, context: FlagContext | None = None) -> FlagEvaluation:
        """Full evaluation of a feature flag with audit trail."""
        ctx = context or FlagContext()
        rule = await self._store.get(flag_name)

        # Flag not found → disabled
        if rule is None:
            evaluation = FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="Flag not found",
            )
            self._evaluation_log.append(evaluation)
            return evaluation

        # Not enabled at rule level
        if not rule.enabled:
            evaluation = FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="Flag disabled at rule level",
            )
            self._evaluation_log.append(evaluation)
            return evaluation

        # Blocklist check (highest priority)
        if ctx.user_id and ctx.user_id in rule.blocklist_users:
            evaluation = FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="User in blocklist",
            )
            self._evaluation_log.append(evaluation)
            return evaluation

        if ctx.tenant_id and ctx.tenant_id in rule.blocklist_tenants:
            evaluation = FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="Tenant in blocklist",
            )
            self._evaluation_log.append(evaluation)
            return evaluation

        # Allowlist check — exclusive: if allowlist is non-empty and user/tenant NOT in it, deny
        has_user_allowlist = bool(rule.allowlist_users)
        has_tenant_allowlist = bool(rule.allowlist_tenants)

        if has_user_allowlist and (not ctx.user_id or ctx.user_id not in rule.allowlist_users):
            evaluation = FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="User not in allowlist",
            )
            self._evaluation_log.append(evaluation)
            return evaluation

        if has_tenant_allowlist and (
            not ctx.tenant_id or ctx.tenant_id not in rule.allowlist_tenants
        ):
            evaluation = FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="Tenant not in allowlist",
            )
            self._evaluation_log.append(evaluation)
            return evaluation

        if ctx.user_id and ctx.user_id in rule.allowlist_users:
            return self._enabled_eval(flag_name, rule, "User in allowlist")

        if ctx.tenant_id and ctx.tenant_id in rule.allowlist_tenants:
            return self._enabled_eval(flag_name, rule, "Tenant in allowlist")

        # Time-based scheduling
        now = datetime.now(UTC)
        if rule.start_time and now < rule.start_time:
            evaluation = FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="Before start_time",
            )
            self._evaluation_log.append(evaluation)
            return evaluation

        if rule.end_time and now > rule.end_time:
            evaluation = FlagEvaluation(
                flag_name=flag_name,
                enabled=False,
                reason="After end_time",
            )
            self._evaluation_log.append(evaluation)
            return evaluation

        # Type-specific evaluation
        if rule.flag_type == FlagType.BOOLEAN:
            return self._enabled_eval(flag_name, rule, "Boolean: enabled=True")

        elif rule.flag_type == FlagType.PERCENTAGE:
            hash_val = self._hash_context(flag_name, ctx)
            bucket = hash_val % 100
            if bucket < rule.rollout_percentage:
                return self._enabled_eval(
                    flag_name, rule, f"Percentage: bucket {bucket} < {rule.rollout_percentage}%"
                )
            else:
                evaluation = FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason=f"Percentage: bucket {bucket} >= {rule.rollout_percentage}%",
                )
                self._evaluation_log.append(evaluation)
                return evaluation

        elif rule.flag_type == FlagType.VARIANT:
            variant = self._select_variant(flag_name, ctx, rule)
            if variant:
                evaluation = FlagEvaluation(
                    flag_name=flag_name,
                    enabled=True,
                    variant=variant,
                    reason=f"Variant selected: {variant}",
                )
                self._evaluation_log.append(evaluation)
                return evaluation
            else:
                evaluation = FlagEvaluation(
                    flag_name=flag_name,
                    enabled=False,
                    reason="Variant: no variant selected",
                )
                self._evaluation_log.append(evaluation)
                return evaluation

        elif rule.flag_type == FlagType.SCHEDULED:
            return self._enabled_eval(flag_name, rule, "Scheduled: within time window")

        # Fallback
        evaluation = FlagEvaluation(
            flag_name=flag_name,
            enabled=False,
            reason="Unknown flag type",
        )
        self._evaluation_log.append(evaluation)
        return evaluation

    # ── Internal Helpers ───────────────────────────────────────────────

    def _hash_context(self, flag_name: str, ctx: FlagContext) -> int:
        """Deterministic hash for percentage-based rollout."""
        seed = f"{flag_name}:{ctx.user_id or ''}:{ctx.tenant_id or ''}"
        return int(hashlib.md5(seed.encode()).hexdigest(), 16)

    def _select_variant(self, flag_name: str, ctx: FlagContext, rule: FlagRule) -> str | None:
        """Select a variant based on weighted distribution."""
        if not rule.variants:
            return None

        hash_val = self._hash_context(flag_name, ctx)
        bucket = hash_val % 100
        cumulative = 0
        for variant_name, weight in rule.variants.items():
            cumulative += weight
            if bucket < cumulative:
                return variant_name
        return None

    def _enabled_eval(self, flag_name: str, rule: FlagRule, reason: str) -> FlagEvaluation:
        evaluation = FlagEvaluation(
            flag_name=flag_name,
            enabled=True,
            reason=reason,
        )
        self._evaluation_log.append(evaluation)
        return evaluation

    # ── Audit ──────────────────────────────────────────────────────────

    def get_evaluation_log(self, limit: int = 100) -> list[FlagEvaluation]:
        """Get recent flag evaluations for audit."""
        return self._evaluation_log[-limit:]

    def clear_evaluation_log(self) -> None:
        self._evaluation_log.clear()


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def create_flag_manager() -> FeatureFlagManager:
    """Create a FeatureFlagManager with in-memory store."""
    return FeatureFlagManager(InMemoryFlagStore())
