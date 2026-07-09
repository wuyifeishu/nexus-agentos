"""Tests for agentos.core.feature_flags — Gradual Rollout & Experimentation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agentos.core.feature_flags import (
    FlagContext,
    FlagEvaluation,
    FlagRule,
    FlagType,
    InMemoryFlagStore,
    create_flag_manager,
)

# ============================================================================
# InMemoryFlagStore
# ============================================================================

class TestInMemoryFlagStore:
    @pytest.fixture
    def store(self):
        return InMemoryFlagStore()

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store):
        rule = await store.get("nonexistent")
        assert rule is None

    @pytest.mark.asyncio
    async def test_set_and_get(self, store):
        rule = FlagRule(flag_type=FlagType.BOOLEAN, enabled=True)
        await store.set("test-flag", rule)
        retrieved = await store.get("test-flag")
        assert retrieved is not None
        assert retrieved.enabled is True

    @pytest.mark.asyncio
    async def test_delete(self, store):
        await store.set("flag1", FlagRule(enabled=True))
        assert await store.delete("flag1") is True
        assert await store.get("flag1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        assert await store.delete("no-such-flag") is False

    @pytest.mark.asyncio
    async def test_list(self, store):
        await store.set("a", FlagRule(enabled=True))
        await store.set("b", FlagRule(enabled=False))
        names = await store.list()
        assert "a" in names
        assert "b" in names
        assert len(names) == 2


# ============================================================================
# FlagRule
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

    def test_to_dict(self):
        rule = FlagRule(
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            rollout_percentage=50,
            allowlist_users={"user_a"},
            metadata={"owner": "team-x"},
        )
        d = rule.to_dict()
        assert d["flag_type"] == "percentage"
        assert d["enabled"] is True
        assert d["rollout_percentage"] == 50
        assert "user_a" in d["allowlist_users"]
        assert d["metadata"]["owner"] == "team-x"


# ============================================================================
# FlagContext
# ============================================================================

class TestFlagContext:
    def test_empty_context(self):
        ctx = FlagContext()
        assert ctx.user_id is None
        assert ctx.tenant_id is None

    def test_with_user(self):
        ctx = FlagContext(user_id="user_123")
        assert ctx.user_id == "user_123"

    def test_with_attributes(self):
        ctx = FlagContext(attributes={"beta_tester": True, "region": "us-east"})
        assert ctx.attributes["beta_tester"] is True


# ============================================================================
# FeatureFlagManager — Boolean Flags
# ============================================================================

class TestFeatureFlagManagerBoolean:
    @pytest.fixture
    async def manager(self):
        mgr = create_flag_manager()
        return mgr

    @pytest.mark.asyncio
    async def test_flag_not_found_disabled(self, manager):
        assert await manager.is_enabled("nonexistent") is False

    @pytest.mark.asyncio
    async def test_disabled_flag(self, manager):
        await manager.set_flag("feature-x", FlagRule(enabled=False))
        assert await manager.is_enabled("feature-x") is False

    @pytest.mark.asyncio
    async def test_enabled_flag(self, manager):
        await manager.set_flag("feature-x", FlagRule(enabled=True))
        assert await manager.is_enabled("feature-x") is True

    @pytest.mark.asyncio
    async def test_list_flags(self, manager):
        await manager.set_flag("a", FlagRule(enabled=True))
        await manager.set_flag("b", FlagRule(enabled=True))
        flags = await manager.list_flags()
        assert len(flags) == 2

    @pytest.mark.asyncio
    async def test_delete_flag(self, manager):
        await manager.set_flag("temp", FlagRule(enabled=True))
        assert await manager.delete_flag("temp") is True
        assert await manager.is_enabled("temp") is False

    @pytest.mark.asyncio
    async def test_get_flag(self, manager):
        rule = FlagRule(enabled=True, metadata={"version": "1.0"})
        await manager.set_flag("flag1", rule)
        retrieved = await manager.get_flag("flag1")
        assert retrieved is not None
        assert retrieved.metadata["version"] == "1.0"

    @pytest.mark.asyncio
    async def test_kill_switch(self, manager):
        await manager.set_flag("experiment", FlagRule(enabled=True))
        await manager.kill_switch("experiment")
        assert await manager.is_enabled("experiment") is False

    @pytest.mark.asyncio
    async def test_kill_switch_nonexistent(self, manager):
        # kill_switch on nonexistent flag does nothing
        await manager.kill_switch("does-not-exist")


# ============================================================================
# FeatureFlagManager — Targeting
# ============================================================================

class TestFeatureFlagManagerTargeting:
    @pytest.fixture
    async def manager(self):
        mgr = create_flag_manager()
        return mgr

    @pytest.mark.asyncio
    async def test_allowlist_user_included(self, manager):
        await manager.set_flag(
            "beta",
            FlagRule(enabled=True, allowlist_users={"power_user"}),
        )
        ctx = FlagContext(user_id="power_user")
        assert await manager.is_enabled("beta", ctx) is True

    @pytest.mark.asyncio
    async def test_allowlist_user_excluded(self, manager):
        await manager.set_flag(
            "beta",
            FlagRule(enabled=True, allowlist_users={"power_user"}),
        )
        ctx = FlagContext(user_id="regular_user")
        assert await manager.is_enabled("beta", ctx) is False

    @pytest.mark.asyncio
    async def test_blocklist_user(self, manager):
        await manager.set_flag(
            "feature",
            FlagRule(enabled=True, blocklist_users={"bad_user"}),
        )
        ctx = FlagContext(user_id="bad_user")
        assert await manager.is_enabled("feature", ctx) is False

    @pytest.mark.asyncio
    async def test_allowlist_tenant(self, manager):
        await manager.set_flag(
            "enterprise",
            FlagRule(enabled=True, allowlist_tenants={"tenant_ent"}),
        )
        ctx = FlagContext(tenant_id="tenant_ent")
        assert await manager.is_enabled("enterprise", ctx) is True

    @pytest.mark.asyncio
    async def test_blocklist_tenant(self, manager):
        await manager.set_flag(
            "feature",
            FlagRule(enabled=True, blocklist_tenants={"blocked_tenant"}),
        )
        ctx = FlagContext(tenant_id="blocked_tenant")
        assert await manager.is_enabled("feature", ctx) is False

    @pytest.mark.asyncio
    async def test_blocklist_priority_over_allowlist(self, manager):
        await manager.set_flag(
            "feature",
            FlagRule(
                enabled=True,
                allowlist_users={"user_x"},
                blocklist_users={"user_x"},
            ),
        )
        ctx = FlagContext(user_id="user_x")
        assert await manager.is_enabled("feature", ctx) is False


# ============================================================================
# FeatureFlagManager — Percentage Rollout
# ============================================================================

class TestFeatureFlagManagerPercentage:
    @pytest.fixture
    async def manager(self):
        mgr = create_flag_manager()
        return mgr

    @pytest.mark.asyncio
    async def test_percentage_0_always_disabled(self, manager):
        await manager.set_flag(
            "new-ui",
            FlagRule(flag_type=FlagType.PERCENTAGE, enabled=True, rollout_percentage=0),
        )
        for i in range(20):
            ctx = FlagContext(user_id=f"user_{i}")
            assert await manager.is_enabled("new-ui", ctx) is False

    @pytest.mark.asyncio
    async def test_percentage_100_always_enabled(self, manager):
        await manager.set_flag(
            "new-ui",
            FlagRule(flag_type=FlagType.PERCENTAGE, enabled=True, rollout_percentage=100),
        )
        for i in range(20):
            ctx = FlagContext(user_id=f"user_{i}")
            assert await manager.is_enabled("new-ui", ctx) is True

    @pytest.mark.asyncio
    async def test_percentage_deterministic(self, manager):
        """Same user always gets the same result."""
        await manager.set_flag(
            "feature",
            FlagRule(flag_type=FlagType.PERCENTAGE, enabled=True, rollout_percentage=50),
        )
        ctx = FlagContext(user_id="deterministic_user")
        results = [await manager.is_enabled("feature", ctx) for _ in range(10)]
        assert all(r == results[0] for r in results)

    @pytest.mark.asyncio
    async def test_percentage_distribution(self, manager):
        """50% rollout should roughly split users."""
        await manager.set_flag(
            "feature",
            FlagRule(flag_type=FlagType.PERCENTAGE, enabled=True, rollout_percentage=50),
        )
        enabled_count = 0
        for i in range(100):
            ctx = FlagContext(user_id=f"user_{i}")
            if await manager.is_enabled("feature", ctx):
                enabled_count += 1
        # Allow generous tolerance for 100 users
        assert 25 <= enabled_count <= 75


# ============================================================================
# FeatureFlagManager — Time-based
# ============================================================================

class TestFeatureFlagManagerScheduled:
    @pytest.fixture
    async def manager(self):
        mgr = create_flag_manager()
        return mgr

    @pytest.mark.asyncio
    async def test_before_start_disabled(self, manager):
        future = datetime.now(UTC) + timedelta(days=30)
        await manager.set_flag(
            "launch",
            FlagRule(flag_type=FlagType.SCHEDULED, enabled=True, start_time=future),
        )
        assert await manager.is_enabled("launch") is False

    @pytest.mark.asyncio
    async def test_after_end_disabled(self, manager):
        past = datetime.now(UTC) - timedelta(days=30)
        await manager.set_flag(
            "expired",
            FlagRule(flag_type=FlagType.SCHEDULED, enabled=True, end_time=past),
        )
        assert await manager.is_enabled("expired") is False

    @pytest.mark.asyncio
    async def test_within_window_enabled(self, manager):
        past_start = datetime.now(UTC) - timedelta(days=1)
        future_end = datetime.now(UTC) + timedelta(days=1)
        await manager.set_flag(
            "active",
            FlagRule(
                flag_type=FlagType.SCHEDULED,
                enabled=True,
                start_time=past_start,
                end_time=future_end,
            ),
        )
        assert await manager.is_enabled("active") is True


# ============================================================================
# FeatureFlagManager — Variants (A/B Testing)
# ============================================================================

class TestFeatureFlagManagerVariants:
    @pytest.fixture
    async def manager(self):
        mgr = create_flag_manager()
        return mgr

    @pytest.mark.asyncio
    async def test_variant_selection(self, manager):
        await manager.set_flag(
            "ab-test",
            FlagRule(
                flag_type=FlagType.VARIANT,
                enabled=True,
                variants={"control": 50, "treatment": 50},
            ),
        )
        ctx = FlagContext(user_id="test_user")
        variant = await manager.get_variant("ab-test", ctx)
        assert variant in ("control", "treatment")

    @pytest.mark.asyncio
    async def test_variant_deterministic(self, manager):
        await manager.set_flag(
            "ab-test",
            FlagRule(
                flag_type=FlagType.VARIANT,
                enabled=True,
                variants={"A": 50, "B": 50},
            ),
        )
        ctx = FlagContext(user_id="stable_user")
        results = [await manager.get_variant("ab-test", ctx) for _ in range(10)]
        assert all(r == results[0] for r in results)

    @pytest.mark.asyncio
    async def test_variant_distribution(self, manager):
        await manager.set_flag(
            "ab-test",
            FlagRule(
                flag_type=FlagType.VARIANT,
                enabled=True,
                variants={"A": 30, "B": 70},
            ),
        )
        a_count = 0
        b_count = 0
        for i in range(100):
            ctx = FlagContext(user_id=f"user_{i}")
            variant = await manager.get_variant("ab-test", ctx)
            if variant == "A":
                a_count += 1
            elif variant == "B":
                b_count += 1
        assert a_count + b_count == 100
        assert b_count > a_count  # B should dominate with 70%

    @pytest.mark.asyncio
    async def test_variant_flag_is_enabled(self, manager):
        await manager.set_flag(
            "ab-test",
            FlagRule(
                flag_type=FlagType.VARIANT,
                enabled=True,
                variants={"control": 50, "treatment": 50},
            ),
        )
        ctx = FlagContext(user_id="any_user")
        assert await manager.is_enabled("ab-test", ctx) is True

    @pytest.mark.asyncio
    async def test_no_variants_returns_none(self, manager):
        await manager.set_flag(
            "empty-variant",
            FlagRule(flag_type=FlagType.VARIANT, enabled=True, variants={}),
        )
        ctx = FlagContext(user_id="user1")
        assert await manager.get_variant("empty-variant", ctx) is None


# ============================================================================
# Evaluation Log / Audit
# ============================================================================

class TestEvaluationLog:
    @pytest.fixture
    async def manager(self):
        mgr = create_flag_manager()
        return mgr

    @pytest.mark.asyncio
    async def test_log_records_evaluations(self, manager):
        await manager.set_flag("f1", FlagRule(enabled=True))
        await manager.is_enabled("f1")
        log = manager.get_evaluation_log()
        assert len(log) == 1
        assert log[0].flag_name == "f1"

    @pytest.mark.asyncio
    async def test_log_limit(self, manager):
        for i in range(5):
            await manager.set_flag(f"f{i}", FlagRule(enabled=True))
            await manager.is_enabled(f"f{i}")
        log = manager.get_evaluation_log(limit=3)
        assert len(log) == 3

    @pytest.mark.asyncio
    async def test_clear_log(self, manager):
        await manager.set_flag("f1", FlagRule(enabled=True))
        await manager.is_enabled("f1")
        manager.clear_evaluation_log()
        assert len(manager.get_evaluation_log()) == 0


# ============================================================================
# FlagEvaluation
# ============================================================================

class TestFlagEvaluation:
    def test_defaults(self):
        e = FlagEvaluation(flag_name="test", enabled=True)
        assert e.flag_name == "test"
        assert e.enabled is True
        assert e.variant is None
        assert e.reason == ""
        assert e.evaluated_at > 0

    def test_with_variant(self):
        e = FlagEvaluation(flag_name="ab", enabled=True, variant="B", reason="Variant selected")
        assert e.variant == "B"
        assert "Variant" in e.reason


# ============================================================================
# FlagType
# ============================================================================

class TestFlagType:
    def test_enum_values(self):
        assert FlagType.BOOLEAN.value == "boolean"
        assert FlagType.PERCENTAGE.value == "percentage"
        assert FlagType.VARIANT.value == "variant"
        assert FlagType.SCHEDULED.value == "scheduled"


# ============================================================================
# create_flag_manager convenience
# ============================================================================

class TestCreateFlagManager:
    @pytest.mark.asyncio
    async def test_creates_working_manager(self):
        mgr = create_flag_manager()
        await mgr.set_flag("test", FlagRule(enabled=True))
        assert await mgr.is_enabled("test") is True
