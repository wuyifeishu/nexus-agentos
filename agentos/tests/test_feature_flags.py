"""Tests for agentos.core.feature_flags — FeatureFlagManager, FlagRule, FlagContext."""

from datetime import UTC, datetime, timedelta

import pytest

from agentos.core.feature_flags import (
    FeatureFlagManager,
    FlagContext,
    FlagEvaluation,
    FlagRule,
    FlagType,
    InMemoryFlagStore,
    create_flag_manager,
)

# ============================================================================
# FlagType
# ============================================================================

class TestFlagType:
    def test_values(self):
        assert FlagType.BOOLEAN == "boolean"
        assert FlagType.PERCENTAGE == "percentage"
        assert FlagType.VARIANT == "variant"
        assert FlagType.SCHEDULED == "scheduled"


# ============================================================================
# FlagRule — to_dict
# ============================================================================

class TestFlagRule:
    def test_defaults(self):
        rule = FlagRule()
        assert rule.flag_type == FlagType.BOOLEAN
        assert rule.enabled is False
        assert rule.rollout_percentage == 0
        assert rule.variants == {}
        assert rule.allowlist_users == set()
        assert rule.start_time is None

    def test_to_dict_basic(self):
        rule = FlagRule(flag_type=FlagType.BOOLEAN, enabled=True)
        d = rule.to_dict()
        assert d["flag_type"] == "boolean"
        assert d["enabled"] is True
        assert d["rollout_percentage"] == 0

    def test_to_dict_with_times(self):
        t1 = datetime(2025, 1, 1, tzinfo=UTC)
        t2 = datetime(2025, 12, 31, tzinfo=UTC)
        rule = FlagRule(start_time=t1, end_time=t2)
        d = rule.to_dict()
        assert "2025-01-01" in d["start_time"]
        assert "2025-12-31" in d["end_time"]


# ============================================================================
# FlagContext
# ============================================================================

class TestFlagContext:
    def test_defaults(self):
        ctx = FlagContext()
        assert ctx.user_id is None
        assert ctx.tenant_id is None

    def test_custom(self):
        ctx = FlagContext(user_id="u1", tenant_id="t1", attributes={"role": "admin"})
        assert ctx.user_id == "u1"
        assert ctx.attributes == {"role": "admin"}


# ============================================================================
# FlagEvaluation
# ============================================================================

class TestFlagEvaluation:
    def test_enabled(self):
        e = FlagEvaluation(flag_name="f1", enabled=True, reason="ok")
        assert e.enabled
        assert e.flag_name == "f1"

    def test_disabled(self):
        e = FlagEvaluation(flag_name="f1", enabled=False, reason="nope")
        assert not e.enabled


# ============================================================================
# InMemoryFlagStore
# ============================================================================

class TestInMemoryFlagStore:
    @pytest.mark.asyncio
    async def test_set_get(self):
        store = InMemoryFlagStore()
        rule = FlagRule(enabled=True)
        await store.set("f1", rule)
        assert await store.get("f1") is rule

    @pytest.mark.asyncio
    async def test_get_missing(self):
        store = InMemoryFlagStore()
        assert await store.get("missing") is None

    @pytest.mark.asyncio
    async def test_delete_existing(self):
        store = InMemoryFlagStore()
        await store.set("f1", FlagRule())
        assert await store.delete("f1") is True
        assert await store.get("f1") is None

    @pytest.mark.asyncio
    async def test_delete_missing(self):
        store = InMemoryFlagStore()
        assert await store.delete("missing") is False

    @pytest.mark.asyncio
    async def test_list(self):
        store = InMemoryFlagStore()
        await store.set("a", FlagRule())
        await store.set("b", FlagRule())
        names = await store.list()
        assert sorted(names) == ["a", "b"]


# ============================================================================
# FeatureFlagManager — Flag Management
# ============================================================================

class TestFeatureFlagManagerManagement:
    @pytest.mark.asyncio
    async def test_set_and_get_flag(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        rule = FlagRule(enabled=True)
        await mgr.set_flag("f1", rule)
        assert await mgr.get_flag("f1") is rule

    @pytest.mark.asyncio
    async def test_delete_flag(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule())
        assert await mgr.delete_flag("f1") is True
        assert await mgr.get_flag("f1") is None

    @pytest.mark.asyncio
    async def test_list_flags(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("a", FlagRule())
        await mgr.set_flag("b", FlagRule())
        assert sorted(await mgr.list_flags()) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_kill_switch(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(enabled=True))
        await mgr.kill_switch("f1")
        rule = await mgr.get_flag("f1")
        assert rule.enabled is False

    @pytest.mark.asyncio
    async def test_kill_switch_missing(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.kill_switch("missing")  # should not raise


# ============================================================================
# FeatureFlagManager — is_enabled / evaluate
# ============================================================================

class TestFeatureFlagManagerEvaluation:
    @pytest.mark.asyncio
    async def test_flag_not_found(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        assert not await mgr.is_enabled("missing")

    @pytest.mark.asyncio
    async def test_boolean_disabled(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(flag_type=FlagType.BOOLEAN, enabled=False))
        assert not await mgr.is_enabled("f1")

    @pytest.mark.asyncio
    async def test_boolean_enabled(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(flag_type=FlagType.BOOLEAN, enabled=True))
        assert await mgr.is_enabled("f1")

    @pytest.mark.asyncio
    async def test_blocklist_user(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.BOOLEAN, enabled=True,
            blocklist_users={"u_bad"},
        ))
        ctx = FlagContext(user_id="u_bad")
        assert not await mgr.is_enabled("f1", ctx)

    @pytest.mark.asyncio
    async def test_blocklist_tenant(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.BOOLEAN, enabled=True,
            blocklist_tenants={"t_bad"},
        ))
        ctx = FlagContext(tenant_id="t_bad")
        assert not await mgr.is_enabled("f1", ctx)

    @pytest.mark.asyncio
    async def test_allowlist_user_granted(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.BOOLEAN, enabled=True,
            allowlist_users={"u_good"},
        ))
        ctx = FlagContext(user_id="u_good")
        assert await mgr.is_enabled("f1", ctx)

    @pytest.mark.asyncio
    async def test_allowlist_user_not_in(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.BOOLEAN, enabled=True,
            allowlist_users={"u_good"},
        ))
        ctx = FlagContext(user_id="u_other")
        assert not await mgr.is_enabled("f1", ctx)

    @pytest.mark.asyncio
    async def test_allowlist_tenant_not_in(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.BOOLEAN, enabled=True,
            allowlist_tenants={"t_good"},
        ))
        ctx = FlagContext(tenant_id="t_other")
        assert not await mgr.is_enabled("f1", ctx)

    @pytest.mark.asyncio
    async def test_start_time_future(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        future = datetime.now(UTC) + timedelta(days=30)
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.SCHEDULED, enabled=True,
            start_time=future,
        ))
        assert not await mgr.is_enabled("f1")

    @pytest.mark.asyncio
    async def test_end_time_past(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        past = datetime.now(UTC) - timedelta(days=30)
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.SCHEDULED, enabled=True,
            end_time=past,
        ))
        assert not await mgr.is_enabled("f1")

    @pytest.mark.asyncio
    async def test_scheduled_within_window(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        past = datetime.now(UTC) - timedelta(days=1)
        future = datetime.now(UTC) + timedelta(days=1)
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.SCHEDULED, enabled=True,
            start_time=past, end_time=future,
        ))
        assert await mgr.is_enabled("f1")


# ============================================================================
# FeatureFlagManager — Percentage rollout
# ============================================================================

class TestFeatureFlagManagerPercentage:
    @pytest.mark.asyncio
    async def test_percentage_zero(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.PERCENTAGE, enabled=True,
            rollout_percentage=0,
        ))
        ctx = FlagContext(user_id="u1")
        assert not await mgr.is_enabled("f1", ctx)

    @pytest.mark.asyncio
    async def test_percentage_hundred(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.PERCENTAGE, enabled=True,
            rollout_percentage=100,
        ))
        ctx = FlagContext(user_id="u1")
        assert await mgr.is_enabled("f1", ctx)

    @pytest.mark.asyncio
    async def test_percentage_deterministic(self):
        """Same user should always get same result."""
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.PERCENTAGE, enabled=True,
            rollout_percentage=50,
        ))
        ctx = FlagContext(user_id="u1")
        r1 = await mgr.is_enabled("f1", ctx)
        r2 = await mgr.is_enabled("f1", ctx)
        assert r1 == r2


# ============================================================================
# FeatureFlagManager — Variant (A/B)
# ============================================================================

class TestFeatureFlagManagerVariant:
    @pytest.mark.asyncio
    async def test_get_variant(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("ab_test", FlagRule(
            flag_type=FlagType.VARIANT, enabled=True,
            variants={"control": 50, "treatment": 50},
        ))
        ctx = FlagContext(user_id="u1")
        variant = await mgr.get_variant("ab_test", ctx)
        assert variant in ("control", "treatment")

    @pytest.mark.asyncio
    async def test_variant_deterministic(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("ab_test", FlagRule(
            flag_type=FlagType.VARIANT, enabled=True,
            variants={"a": 30, "b": 70},
        ))
        ctx = FlagContext(user_id="u1")
        v1 = await mgr.get_variant("ab_test", ctx)
        v2 = await mgr.get_variant("ab_test", ctx)
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_variant_no_variants(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.VARIANT, enabled=True,
        ))
        ctx = FlagContext(user_id="u1")
        assert await mgr.get_variant("f1", ctx) is None


# ============================================================================
# FeatureFlagManager — Audit log
# ============================================================================

class TestFeatureFlagManagerAudit:
    @pytest.mark.asyncio
    async def test_evaluation_log(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(flag_type=FlagType.BOOLEAN, enabled=True))
        await mgr.is_enabled("f1")
        log = mgr.get_evaluation_log()
        assert len(log) == 1
        assert log[0].enabled

    @pytest.mark.asyncio
    async def test_log_limit(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(flag_type=FlagType.BOOLEAN, enabled=True))
        for _ in range(5):
            await mgr.is_enabled("f1")
        assert len(mgr.get_evaluation_log(limit=3)) == 3

    @pytest.mark.asyncio
    async def test_clear_log(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(enabled=True))
        await mgr.is_enabled("f1")
        mgr.clear_evaluation_log()
        assert len(mgr.get_evaluation_log()) == 0


# ============================================================================
# FeatureFlagManager — Edge cases
# ============================================================================

class TestFeatureFlagManagerEdgeCases:
    @pytest.mark.asyncio
    async def test_null_context(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(flag_type=FlagType.BOOLEAN, enabled=True))
        assert await mgr.is_enabled("f1")  # no context passed

    @pytest.mark.asyncio
    async def test_evaluate_returns_flag_evaluation(self):
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(flag_type=FlagType.BOOLEAN, enabled=True))
        result = await mgr.evaluate("f1")
        assert isinstance(result, FlagEvaluation)
        assert result.enabled

    @pytest.mark.asyncio
    async def test_allowlist_exclusive_behavior(self):
        """Non-empty allowlist + user/tenant NOT in it → disabled."""
        mgr = FeatureFlagManager(InMemoryFlagStore())
        await mgr.set_flag("f1", FlagRule(
            flag_type=FlagType.BOOLEAN, enabled=True,
            allowlist_users={"specific"},
            allowlist_tenants={"t1"},
        ))
        # No user/tenant context
        ctx = FlagContext()
        assert not await mgr.is_enabled("f1", ctx)


# ============================================================================
# create_flag_manager convenience
# ============================================================================

class TestCreateFlagManager:
    @pytest.mark.asyncio
    async def test_creates_functional_manager(self):
        mgr = create_flag_manager()
        await mgr.set_flag("test", FlagRule(enabled=True))
        assert await mgr.is_enabled("test")
