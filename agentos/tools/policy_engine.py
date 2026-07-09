"""
PolicyEngine — declarative rule engine with conditions, actions, and priorities.

Supports:
    - Rule DSL: WHEN {condition} THEN {action} WITH priority {int}
    - Conditions: equals, contains, regex, gt/lt/gte/lte, in_set, exists, custom callable
    - Actions: set, log, reject, allow, call, chain
    - Priority ordering + first-match / all-match modes
    - Dynamic rule add/remove at runtime
    - JSON serialization for persistence
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Condition Operators
# ============================================================================


class Op(Enum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    REGEX = "regex"
    IN_SET = "in_set"
    EXISTS = "exists"
    CUSTOM = "custom"

    def evaluate(self, actual: Any, expected: Any) -> bool:
        if self == Op.EQ:
            return actual == expected
        elif self == Op.NE:
            return actual != expected
        elif self == Op.GT:
            return actual > expected
        elif self == Op.GTE:
            return actual >= expected
        elif self == Op.LT:
            return actual < expected
        elif self == Op.LTE:
            return actual <= expected
        elif self == Op.CONTAINS:
            return expected in actual if isinstance(actual, (str, list, set, tuple)) else False
        elif self == Op.REGEX:
            return bool(re.search(expected, actual)) if isinstance(actual, str) else False
        elif self == Op.IN_SET:
            return actual in expected if isinstance(expected, (list, set, tuple)) else False
        elif self == Op.EXISTS:
            return actual is not None
        elif self == Op.CUSTOM:
            # expected is a callable
            return bool(expected(actual))
        return False


# ============================================================================
# Condition
# ============================================================================


@dataclass
class Condition:
    """A single condition: field OP value."""

    field: str
    op: Op
    value: Any

    def evaluate(self, context: dict[str, Any]) -> bool:
        actual = context.get(self.field)
        return self.op.evaluate(actual, self.value)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"field": self.field, "op": self.op.value}
        if self.op != Op.EXISTS:
            result["value"] = self.value if self.op != Op.CUSTOM else "<callable>"
        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Condition:
        return cls(field=d["field"], op=Op(d["op"]), value=d.get("value"))


# ============================================================================
# Actions
# ============================================================================


class ActionType(Enum):
    SET = "set"
    LOG = "log"
    REJECT = "reject"
    ALLOW = "allow"
    CALL = "call"
    CHAIN = "chain"

    def execute(
        self,
        context: dict[str, Any],
        params: Any,
    ) -> dict[str, Any] | None:
        result: dict[str, Any] | None = None
        if self == ActionType.SET:
            if isinstance(params, dict):
                for k, v in params.items():
                    context[k] = v
        elif self == ActionType.LOG:
            logger.info("policy_engine: %s", params)
        elif self == ActionType.REJECT:
            result = {"action": "reject", "reason": str(params)}
        elif self == ActionType.ALLOW:
            result = {"action": "allow"}
        elif self == ActionType.CALL:
            if callable(params):
                params(context)
        elif self == ActionType.CHAIN:
            if isinstance(params, list):
                for sub_action in params:
                    if isinstance(sub_action, Action):
                        sub_action.execute(context)
        return result

    @classmethod
    def from_str(cls, s: str) -> ActionType:
        return ActionType(s.lower())


# ============================================================================
# Action
# ============================================================================


@dataclass
class Action:
    """Action definition."""

    type: ActionType
    params: Any = None

    def execute(self, context: dict[str, Any]) -> dict[str, Any] | None:
        return self.type.execute(context, self.params)

    def to_dict(self) -> dict[str, Any]:
        result = {"type": self.type.value}
        if self.params is not None:
            result["params"] = self.params if not callable(self.params) else "<callable>"
        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Action:
        return cls(type=ActionType.from_str(d["type"]), params=d.get("params"))


# ============================================================================
# Rule
# ============================================================================


@dataclass
class Rule:
    """A single rule: when all conditions match, execute actions."""

    name: str
    conditions: list[Condition] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    description: str = ""

    def matches(self, context: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        return all(c.evaluate(context) for c in self.conditions)

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Evaluate rule against context. Returns action result if triggered."""
        if not self.matches(context):
            return None
        results = []
        for action in self.actions:
            r = action.execute(context)
            if r:
                results.append(r)
        return results[-1] if results else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "conditions": [c.to_dict() for c in self.conditions],
            "actions": [a.to_dict() for a in self.actions],
            "priority": self.priority,
            "enabled": self.enabled,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Rule:
        return cls(
            name=d["name"],
            conditions=[Condition.from_dict(c) for c in d.get("conditions", [])],
            actions=[Action.from_dict(a) for a in d.get("actions", [])],
            priority=d.get("priority", 0),
            enabled=d.get("enabled", True),
            description=d.get("description", ""),
        )


# ============================================================================
# Match Mode
# ============================================================================


class MatchMode(Enum):
    FIRST = "first"  # Stop after first matching rule
    ALL = "all"  # Evaluate all rules, collect results


# ============================================================================
# PolicyEngine
# ============================================================================


class PolicyEngine:
    """Declarative rule engine.

    Usage:
        pe = PolicyEngine()

        pe.add_rule(
            name="admin-access",
            conditions=[
                Condition(field="role", op=Op.EQ, value="admin"),
            ],
            actions=[Action(type=ActionType.ALLOW)],
            priority=100,
        )

        pe.add_rule(
            name="rate-limit",
            conditions=[
                Condition(field="requests_per_min", op=Op.GT, value=100),
            ],
            actions=[Action(type=ActionType.REJECT, params="rate limit exceeded")],
            priority=50,
        )

        result = pe.evaluate({"role": "admin", "requests_per_min": 150})
        # → {"action": "allow"}  (higher priority matches first)
    """

    def __init__(self, mode: MatchMode = MatchMode.FIRST):
        self._rules: list[Rule] = []
        self._mode = mode
        self._rule_names: set[str] = set()

    # ---------- CRUD ----------

    def add_rule(
        self,
        name: str,
        conditions: list[Condition] | None = None,
        actions: list[Action] | None = None,
        priority: int = 0,
        enabled: bool = True,
        description: str = "",
    ) -> Rule:
        if name in self._rule_names:
            raise ValueError(f"Rule '{name}' already exists")
        rule = Rule(
            name=name,
            conditions=conditions or [],
            actions=actions or [],
            priority=priority,
            enabled=enabled,
            description=description,
        )
        self._rules.append(rule)
        self._rule_names.add(name)
        self._sort()
        return rule

    def remove_rule(self, name: str) -> bool:
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        self._rule_names.discard(name)
        return len(self._rules) < before

    def get_rule(self, name: str) -> Rule | None:
        for r in self._rules:
            if r.name == name:
                return r
        return None

    def enable_rule(self, name: str) -> bool:
        rule = self.get_rule(name)
        if rule:
            rule.enabled = True
            return True
        return False

    def disable_rule(self, name: str) -> bool:
        rule = self.get_rule(name)
        if rule:
            rule.enabled = False
            return True
        return False

    def _sort(self) -> None:
        self._rules.sort(key=lambda r: -r.priority)

    # ---------- evaluation ----------

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Evaluate rules against context."""
        results = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            if rule.matches(context):
                result = rule.evaluate(context)
                results.append({"rule": rule.name, "result": result})
                if self._mode == MatchMode.FIRST:
                    break
        if not results:
            return None
        if self._mode == MatchMode.FIRST:
            return results[0]
        return {"matches": results}

    def evaluate_all(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate all rules, return list of matches (ignores mode)."""
        matches = []
        for rule in self._rules:
            if rule.matches(context):
                result = rule.evaluate(context)
                if result:
                    matches.append({"rule": rule.name, "result": result})
        return matches

    # ---------- serialization ----------

    def to_dict(self) -> dict[str, Any]:
        return {"rules": [r.to_dict() for r in self._rules], "mode": self._mode.value}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PolicyEngine:
        pe = cls(mode=MatchMode(d.get("mode", "first")))
        for rule_d in d.get("rules", []):
            pe.add_rule(
                name=rule_d["name"],
                conditions=[Condition.from_dict(c) for c in rule_d.get("conditions", [])],
                actions=[Action.from_dict(a) for a in rule_d.get("actions", [])],
                priority=rule_d.get("priority", 0),
                enabled=rule_d.get("enabled", True),
                description=rule_d.get("description", ""),
            )
        return pe

    @classmethod
    def from_json(cls, json_str: str) -> PolicyEngine:
        return cls.from_dict(json.loads(json_str))

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)
