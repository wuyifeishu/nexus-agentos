"""Tests for agentos.tools.feature_flag."""

import pytest

from agentos.tools.feature_flag import FeatureFlag


class TestFeatureFlag:
    def test_default_false(self):
        ff = FeatureFlag()
        ff.define("my_flag", default=False)
        assert not ff.is_enabled("my_flag")

    def test_default_true(self):
        ff = FeatureFlag()
        ff.define("my_flag", default=True)
        assert ff.is_enabled("my_flag")

    def test_unknown_flag(self):
        ff = FeatureFlag()
        assert not ff.is_enabled("nonexistent")

    def test_target_groups(self):
        ff = FeatureFlag()
        ff.define("beta", default=False, targets=["beta-users", "staff"])
        assert ff.is_enabled("beta", context={"groups": ["beta-users"]})
        assert not ff.is_enabled("beta", context={"groups": ["normal"]})

    def test_percentage_rollout(self):
        ff = FeatureFlag()
        ff.define("new_feature", default=False, rollout=50)

        # User ID hashing is deterministic — same user gets same result
        results = [ff.is_enabled("new_feature", context={"user_id": f"user{i}"}) for i in range(100)]
        # Roughly 50% should be true
        rate = sum(results) / len(results)
        assert 20 <= sum(results) <= 80  # Wide range to avoid flakiness

    def test_rollout_deterministic(self):
        ff = FeatureFlag()
        ff.define("feat", rollout=50)
        # Same user always gets same result
        results = [ff.is_enabled("feat", context={"user_id": "consistent-user"}) for _ in range(10)]
        assert all(r == results[0] for r in results)

    def test_override(self):
        ff = FeatureFlag()
        ff.define("flag", default=False)
        ff.set_override("flag", "user1", True)
        assert ff.is_enabled("flag", context={"user_id": "user1"})
        assert not ff.is_enabled("flag", context={"user_id": "user2"})

    def test_clear_override(self):
        ff = FeatureFlag()
        ff.define("flag", default=False)
        ff.set_override("flag", "user1", True)
        ff.clear_override("flag", "user1")
        assert not ff.is_enabled("flag", context={"user_id": "user1"})

    def test_clear_all_overrides(self):
        ff = FeatureFlag()
        ff.define("flag", default=False)
        ff.set_override("flag", "user1", True)
        ff.set_override("flag", "user2", True)
        ff.clear_all_overrides("flag")
        assert not ff.is_enabled("flag", context={"user_id": "user1"})
        assert not ff.is_enabled("flag", context={"user_id": "user2"})

    def test_clear_all_overrides_no_name(self):
        ff = FeatureFlag()
        ff.define("flag1", default=False)
        ff.define("flag2", default=False)
        ff.set_override("flag1", "user1", True)
        ff.set_override("flag2", "user2", True)
        ff.clear_all_overrides()
        assert not ff.is_enabled("flag1", context={"user_id": "user1"})
        assert not ff.is_enabled("flag2", context={"user_id": "user2"})

    def test_override_unknown_flag(self):
        ff = FeatureFlag()
        with pytest.raises(KeyError):
            ff.set_override("nonexistent", "user1", True)

    def test_dependency_chain(self):
        ff = FeatureFlag()
        ff.define("parent", default=True)
        ff.define("child", default=True, depends_on=["parent"])
        assert ff.is_enabled("child", context={})
        # If parent is off via override, child should also be off
        ff.set_override("parent", "user1", False)
        assert not ff.is_enabled("child", context={"user_id": "user1"})

    def test_dependency_default_false(self):
        ff = FeatureFlag()
        ff.define("parent", default=False)
        ff.define("child", default=True, depends_on=["parent"])
        assert not ff.is_enabled("child")

    def test_list_flags(self):
        ff = FeatureFlag()
        ff.define("a")
        ff.define("b")
        assert set(ff.list_flags()) == {"a", "b"}

    def test_get_definition(self):
        ff = FeatureFlag()
        ff.define("flag", default=True, rollout=30, targets=["admin"])
        d = ff.get_definition("flag")
        assert d["name"] == "flag"
        assert d["default"] is True
        assert d["rollout"] == 30
        assert d["targets"] == ["admin"]

    def test_get_definition_nonexistent(self):
        ff = FeatureFlag()
        assert ff.get_definition("nope") is None

    def test_remove_flag(self):
        ff = FeatureFlag()
        ff.define("flag")
        ff.remove("flag")
        assert not ff.is_enabled("flag")

    def test_invalid_rollout(self):
        ff = FeatureFlag()
        with pytest.raises(ValueError):
            ff.define("bad", rollout=101)

    def test_overrides_vs_targets(self):
        ff = FeatureFlag()
        ff.define("flag", default=False, targets=["staff"])
        # Override wins over targets
        ff.set_override("flag", "user1", False)
        assert not ff.is_enabled("flag", context={"user_id": "user1", "groups": ["staff"]})
