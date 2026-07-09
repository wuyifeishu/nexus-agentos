"""Tests for agentos.core.feature_flags."""
from agentos.core.feature_flags import (
    FlagContext,
    FlagEvaluation,
    FlagRule,
    FlagType,
    InMemoryFlagStore,
    create_flag_manager,
)


class TestInMemoryFlagStore:
    async def test_set_get(self):
        store = InMemoryFlagStore()
        rule = FlagRule(flag_type=FlagType.BOOLEAN, enabled=True)
        await store.set("test_flag", rule)
        result = await store.get("test_flag")
        assert result is not None
        assert result.enabled is True

    async def test_get_missing(self):
        store = InMemoryFlagStore()
        result = await store.get("nonexistent")
        assert result is None

    async def test_delete(self):
        store = InMemoryFlagStore()
        await store.set("flag", FlagRule(enabled=True))
        assert await store.delete("flag") is True
        assert await store.get("flag") is None

    async def test_delete_missing(self):
        store = InMemoryFlagStore()
        assert await store.delete("missing") is False

    async def test_list(self):
        store = InMemoryFlagStore()
        await store.set("a", FlagRule())
        await store.set("b", FlagRule())
        flags = await store.list()
        assert sorted(flags) == ["a", "b"]


class TestBooleanFlag:
    async def test_enabled(self):
        mgr = create_flag_manager()
        await mgr.set_flag("feature_x", FlagRule(flag_type=FlagType.BOOLEAN, enabled=True))
        assert await mgr.is_enabled("feature_x")

    async def test_disabled(self):
        mgr = create_flag_manager()
        await mgr.set_flag("feature_x", FlagRule(flag_type=FlagType.BOOLEAN, enabled=False))
        assert not await mgr.is_enabled("feature_x")

    async def test_not_found(self):
        mgr = create_flag_manager()
        assert not await mgr.is_enabled("nonexistent")


class TestPercentageFlag:
    async def test_zero_percent(self):
        mgr = create_flag_manager()
        await mgr.set_flag("rollout", FlagRule(
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            rollout_percentage=0,
        ))
        assert not await mgr.is_enabled("rollout", FlagContext(user_id="user_1"))

    async def test_hundred_percent(self):
        mgr = create_flag_manager()
        await mgr.set_flag("rollout", FlagRule(
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            rollout_percentage=100,
        ))
        assert await mgr.is_enabled("rollout", FlagContext(user_id="any_user"))

    async def test_deterministic(self):
        """Same user should get same result."""
        mgr = create_flag_manager()
        await mgr.set_flag("rollout", FlagRule(
            flag_type=FlagType.PERCENTAGE,
            enabled=True,
            rollout_percentage=50,
        ))
        result1 = await mgr.is_enabled("rollout", FlagContext(user_id="user_x"))
        result2 = await mgr.is_enabled("rollout", FlagContext(user_id="user_x"))
        assert result1 == result2


class TestTargeting:
    async def test_allowlist_user(self):
        mgr = create_flag_manager()
        await mgr.set_flag("beta", FlagRule(
            flag_type=FlagType.BOOLEAN,
            enabled=True,
            allowlist_users={"vip_user"},
        ))
        # Not in allowlist → should be disabled
        assert not await mgr.is_enabled("beta", FlagContext(user_id="normal_user"))
        # In allowlist → should be enabled
        assert await mgr.is_enabled("beta", FlagContext(user_id="vip_user"))

    async def test_blocklist_overrides_allowlist(self):
        mgr = create_flag_manager()
        await mgr.set_flag("beta", FlagRule(
            flag_type=FlagType.BOOLEAN,
            enabled=True,
            allowlist_users={"user_a"},
            blocklist_users={"user_a"},
        ))
        assert not await mgr.is_enabled("beta", FlagContext(user_id="user_a"))

    async def test_tenant_targeting(self):
        mgr = create_flag_manager()
        await mgr.set_flag("enterprise", FlagRule(
            flag_type=FlagType.BOOLEAN,
            enabled=True,
            allowlist_tenants={"tenant_enterprise"},
        ))
        assert await mgr.is_enabled("enterprise", FlagContext(tenant_id="tenant_enterprise"))
        assert not await mgr.is_enabled("enterprise", FlagContext(tenant_id="tenant_free"))


class TestVariantFlag:
    async def test_variant_selection(self):
        mgr = create_flag_manager()
        await mgr.set_flag("ab_test", FlagRule(
            flag_type=FlagType.VARIANT,
            enabled=True,
            variants={"control": 50, "treatment_a": 50},
        ))
        variant = await mgr.get_variant("ab_test", FlagContext(user_id="user_1"))
        assert variant is not None

    async def test_empty_variants(self):
        mgr = create_flag_manager()
        await mgr.set_flag("ab_test", FlagRule(
            flag_type=FlagType.VARIANT,
            enabled=True,
            variants={},
        ))
        variant = await mgr.get_variant("ab_test", FlagContext(user_id="user_1"))
        assert variant is None


class TestKillSwitch:
    async def test_kill_switch(self):
        mgr = create_flag_manager()
        await mgr.set_flag("dangerous", FlagRule(flag_type=FlagType.BOOLEAN, enabled=True))
        assert await mgr.is_enabled("dangerous")

        await mgr.kill_switch("dangerous")
        assert not await mgr.is_enabled("dangerous")


class TestEvaluationLog:
    async def test_log_entries(self):
        mgr = create_flag_manager()
        await mgr.set_flag("f1", FlagRule(enabled=True))
        await mgr.is_enabled("f1")
        await mgr.is_enabled("f1")
        log = mgr.get_evaluation_log()
        assert len(log) == 2
        assert all(isinstance(e, FlagEvaluation) for e in log)

    async def test_clear_log(self):
        mgr = create_flag_manager()
        await mgr.set_flag("f1", FlagRule(enabled=True))
        await mgr.is_enabled("f1")
        mgr.clear_evaluation_log()
        assert len(mgr.get_evaluation_log()) == 0
