"""Tests for agentos.tools.policy_engine."""

import pytest

from agentos.tools.policy_engine import (
    Action,
    ActionType,
    Condition,
    MatchMode,
    Op,
    PolicyEngine,
)


class TestCondition:
    def test_eq(self):
        c = Condition(field="role", op=Op.EQ, value="admin")
        assert c.evaluate({"role": "admin"})
        assert not c.evaluate({"role": "user"})

    def test_ne(self):
        c = Condition(field="role", op=Op.NE, value="admin")
        assert not c.evaluate({"role": "admin"})
        assert c.evaluate({"role": "user"})

    def test_gt(self):
        c = Condition(field="count", op=Op.GT, value=10)
        assert c.evaluate({"count": 11})
        assert not c.evaluate({"count": 10})

    def test_gte(self):
        c = Condition(field="count", op=Op.GTE, value=10)
        assert c.evaluate({"count": 10})
        assert c.evaluate({"count": 11})

    def test_lt(self):
        c = Condition(field="count", op=Op.LT, value=10)
        assert c.evaluate({"count": 5})
        assert not c.evaluate({"count": 10})

    def test_lte(self):
        c = Condition(field="count", op=Op.LTE, value=10)
        assert c.evaluate({"count": 10})
        assert c.evaluate({"count": 9})

    def test_contains_str(self):
        c = Condition(field="text", op=Op.CONTAINS, value="hello")
        assert c.evaluate({"text": "hello world"})
        assert not c.evaluate({"text": "world"})

    def test_contains_list(self):
        c = Condition(field="items", op=Op.CONTAINS, value="x")
        assert c.evaluate({"items": ["x", "y", "z"]})
        assert not c.evaluate({"items": ["a", "b"]})

    def test_regex(self):
        c = Condition(field="email", op=Op.REGEX, value=r"@example\.com$")
        assert c.evaluate({"email": "user@example.com"})
        assert not c.evaluate({"email": "user@other.com"})

    def test_regex_non_string(self):
        c = Condition(field="num", op=Op.REGEX, value=r"\d+")
        assert not c.evaluate({"num": 123})

    def test_in_set(self):
        c = Condition(field="role", op=Op.IN_SET, value=["admin", "superadmin"])
        assert c.evaluate({"role": "admin"})
        assert not c.evaluate({"role": "guest"})

    def test_exists(self):
        c = Condition(field="key", op=Op.EXISTS, value=None)
        assert c.evaluate({"key": "val"})
        assert not c.evaluate({})

    def test_custom(self):
        c = Condition(field="val", op=Op.CUSTOM, value=lambda x: x % 2 == 0)
        assert c.evaluate({"val": 4})
        assert not c.evaluate({"val": 3})

    def test_to_from_dict(self):
        c = Condition(field="x", op=Op.GT, value=5)
        d = c.to_dict()
        assert d["field"] == "x"
        assert d["op"] == "gt"
        assert d["value"] == 5
        c2 = Condition.from_dict(d)
        assert c2.field == "x"
        assert c2.op == Op.GT
        assert c2.value == 5


class TestPolicyEngine:
    def test_basic_match(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="admin-allow",
            conditions=[Condition(field="role", op=Op.EQ, value="admin")],
            actions=[Action(type=ActionType.ALLOW)],
            priority=100,
        )
        result = pe.evaluate({"role": "admin"})
        assert result is not None
        assert result["result"]["action"] == "allow"
        assert result["rule"] == "admin-allow"

    def test_no_match(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="admin-only",
            conditions=[Condition(field="role", op=Op.EQ, value="admin")],
            actions=[Action(type=ActionType.ALLOW)],
        )
        assert pe.evaluate({"role": "guest"}) is None

    def test_priority_ordering_first_match(self):
        pe = PolicyEngine(mode=MatchMode.FIRST)
        pe.add_rule(
            name="low",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.SET, params={"matched": "low"})],
            priority=1,
        )
        pe.add_rule(
            name="high",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.SET, params={"matched": "high"})],
            priority=100,
        )
        ctx = {"x": 1}
        result = pe.evaluate(ctx)
        assert result["rule"] == "high"

    def test_all_match_mode(self):
        pe = PolicyEngine(mode=MatchMode.ALL)
        pe.add_rule(
            name="one",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.ALLOW)],
            priority=1,
        )
        pe.add_rule(
            name="two",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.ALLOW)],
            priority=2,
        )
        result = pe.evaluate({"x": 1})
        matches = result["matches"]
        assert len(matches) == 2

    def test_set_action(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="enrich",
            conditions=[Condition(field="type", op=Op.EQ, value="request")],
            actions=[Action(type=ActionType.SET, params={"injected": True, "ts": 100})],
        )
        ctx = {"type": "request"}
        pe.evaluate(ctx)
        assert ctx["injected"] is True
        assert ctx["ts"] == 100

    def test_reject_action(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="block",
            conditions=[Condition(field="blocked", op=Op.EQ, value=True)],
            actions=[Action(type=ActionType.REJECT, params="banned user")],
        )
        result = pe.evaluate({"blocked": True})
        assert result["result"]["action"] == "reject"
        assert result["result"]["reason"] == "banned user"

    def test_multiple_conditions_all_must_match(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="complex",
            conditions=[
                Condition(field="role", op=Op.EQ, value="admin"),
                Condition(field="region", op=Op.IN_SET, value=["us", "eu"]),
                Condition(field="tier", op=Op.GTE, value=3),
            ],
            actions=[Action(type=ActionType.ALLOW)],
        )
        assert pe.evaluate({"role": "admin", "region": "us", "tier": 5}) is not None
        assert pe.evaluate({"role": "admin", "region": "asia", "tier": 5}) is None

    def test_disable_rule(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="disabled-rule",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.ALLOW)],
        )
        pe.disable_rule("disabled-rule")
        assert pe.evaluate({"x": 1}) is None

    def test_enable_rule(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="toggle",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.ALLOW)],
            enabled=False,
        )
        assert pe.evaluate({"x": 1}) is None
        pe.enable_rule("toggle")
        assert pe.evaluate({"x": 1}) is not None

    def test_remove_rule(self):
        pe = PolicyEngine()
        pe.add_rule(name="temp", conditions=[], actions=[])
        assert pe.remove_rule("temp") is True
        assert pe.remove_rule("nonexistent") is False

    def test_duplicate_rule_name(self):
        pe = PolicyEngine()
        pe.add_rule(name="dup", conditions=[], actions=[])
        with pytest.raises(ValueError):
            pe.add_rule(name="dup", conditions=[], actions=[])

    def test_serialization_roundtrip(self):
        pe = PolicyEngine(mode=MatchMode.ALL)
        pe.add_rule(
            name="r1",
            conditions=[Condition(field="x", op=Op.GT, value=0), Condition(field="y", op=Op.EXISTS, value=None)],
            actions=[Action(type=ActionType.ALLOW)],
            priority=10,
            description="test rule",
        )
        pe.add_rule(
            name="r2",
            conditions=[Condition(field="role", op=Op.IN_SET, value=["a", "b"])],
            actions=[Action(type=ActionType.REJECT, params="denied")],
            priority=5,
            enabled=False,
        )
        d = pe.to_dict()
        pe2 = PolicyEngine.from_dict(d)
        assert len(pe2.rules) == 2
        assert pe2._mode == MatchMode.ALL
        r1 = pe2.get_rule("r1")
        assert r1 is not None
        assert r1.priority == 10
        assert r1.description == "test rule"
        r2 = pe2.get_rule("r2")
        assert r2 is not None
        assert r2.enabled is False

    def test_json_roundtrip(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="test",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.ALLOW)],
        )
        json_str = pe.to_json()
        pe2 = PolicyEngine.from_json(json_str)
        assert len(pe2.rules) == 1

    def test_evaluate_all(self):
        pe = PolicyEngine(mode=MatchMode.FIRST)
        pe.add_rule(
            name="a",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.ALLOW)],
        )
        pe.add_rule(
            name="b",
            conditions=[Condition(field="x", op=Op.EQ, value=1)],
            actions=[Action(type=ActionType.REJECT, params="no")],
        )
        matches = pe.evaluate_all({"x": 1})
        assert len(matches) == 2

    def test_call_action(self):
        called = []
        pe = PolicyEngine()
        pe.add_rule(
            name="callback",
            conditions=[Condition(field="trigger", op=Op.EQ, value=True)],
            actions=[Action(type=ActionType.CALL, params=lambda ctx: called.append(ctx["x"]))],
        )
        pe.evaluate({"trigger": True, "x": 42})
        assert called == [42]

    def test_chain_action(self):
        pe = PolicyEngine()
        pe.add_rule(
            name="chain",
            conditions=[Condition(field="go", op=Op.EQ, value=True)],
            actions=[
                Action(type=ActionType.CHAIN, params=[
                    Action(type=ActionType.SET, params={"a": 1}),
                    Action(type=ActionType.SET, params={"b": 2}),
                ]),
            ],
        )
        ctx = {"go": True}
        pe.evaluate(ctx)
        assert ctx["a"] == 1
        assert ctx["b"] == 2
