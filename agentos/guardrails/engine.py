"""
Guardrail engine — rule registry, evaluation, and result aggregation.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Sequence


class GuardrailAction(str, Enum):
    """Guardrail disposition for a single rule match."""

    BLOCK = "block"
    FLAG = "flag"
    SANITIZE = "sanitize"
    PASS = "pass"


class GuardrailCategory(str, Enum):
    """Semantic category of a guardrail rule."""

    PII = "pii"
    TOXICITY = "toxicity"
    INJECTION = "injection"
    KEYWORD = "keyword"
    LENGTH = "length"
    CUSTOM = "custom"


@dataclass
class GuardrailResult:
    """Aggregate result after all guardrails have been evaluated."""

    passed: bool
    action: GuardrailAction
    violations: list[str] = field(default_factory=list)
    sanitized_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.action == GuardrailAction.BLOCK


@dataclass
class GuardrailRule:
    """A single guardrail rule definition."""

    name: str
    category: GuardrailCategory
    action: GuardrailAction
    check: Callable[[str], bool]
    sanitize: Callable[[str], str] | None = None
    description: str = ""
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class InputGuardrail:
    """Validates user prompts before they reach the LLM."""

    def __init__(self, rules: Optional[list[GuardrailRule]] = None):
        self._rules: dict[str, GuardrailRule] = {}
        if rules:
            for r in rules:
                self.add_rule(r)

    def add_rule(self, rule: GuardrailRule) -> None:
        self._rules[rule.name] = rule

    def remove_rule(self, name: str) -> None:
        self._rules.pop(name, None)

    def evaluate(self, text: str) -> GuardrailResult:
        """Run all enabled input rules against the text."""
        violations: list[str] = []
        worst_action = GuardrailAction.PASS
        sanitized = text
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if rule.check(sanitized):
                violations.append(f"{rule.name}: {rule.description or rule.category.value}")
                if rule.sanitize:
                    sanitized = rule.sanitize(sanitized)
                if _action_priority(rule.action) > _action_priority(worst_action):
                    worst_action = rule.action

        passed = worst_action != GuardrailAction.BLOCK
        return GuardrailResult(
            passed=passed,
            action=worst_action,
            violations=violations,
            sanitized_text=sanitized if sanitized != text else None,
        )


class OutputGuardrail:
    """Validates LLM outputs before they reach the user."""

    def __init__(self, rules: Optional[list[GuardrailRule]] = None):
        self._rules: dict[str, GuardrailRule] = {}
        if rules:
            for r in rules:
                self.add_rule(r)

    def add_rule(self, rule: GuardrailRule) -> None:
        self._rules[rule.name] = rule

    def remove_rule(self, name: str) -> None:
        self._rules.pop(name, None)

    def evaluate(self, text: str) -> GuardrailResult:
        """Run all enabled output rules against the text."""
        violations: list[str] = []
        worst_action = GuardrailAction.PASS
        sanitized = text
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if rule.check(sanitized):
                violations.append(f"{rule.name}: {rule.description or rule.category.value}")
                if rule.sanitize:
                    sanitized = rule.sanitize(sanitized)
                if _action_priority(rule.action) > _action_priority(worst_action):
                    worst_action = rule.action

        passed = worst_action != GuardrailAction.BLOCK
        return GuardrailResult(
            passed=passed,
            action=worst_action,
            violations=violations,
            sanitized_text=sanitized if sanitized != text else None,
        )


class GuardrailEngine:
    """Unified guardrail engine managing both input and output pipelines."""

    def __init__(
        self,
        input_rules: Optional[list[GuardrailRule]] = None,
        output_rules: Optional[list[GuardrailRule]] = None,
    ):
        self.input = InputGuardrail(input_rules)
        self.output = OutputGuardrail(output_rules)

    def check_input(self, prompt: str) -> GuardrailResult:
        return self.input.evaluate(prompt)

    def check_output(self, response: str) -> GuardrailResult:
        return self.output.evaluate(response)

    def check(self, prompt: str, response: str = "") -> tuple[GuardrailResult, GuardrailResult]:
        """Evaluate input and output guardrails. Empty response skips output check."""
        inp = self.input.evaluate(prompt)
        out = self.output.evaluate(response) if response else GuardrailResult(
            passed=True, action=GuardrailAction.PASS
        )
        return inp, out


def _action_priority(action: GuardrailAction) -> int:
    return {GuardrailAction.PASS: 0, GuardrailAction.FLAG: 1, GuardrailAction.SANITIZE: 2, GuardrailAction.BLOCK: 3}[action]
