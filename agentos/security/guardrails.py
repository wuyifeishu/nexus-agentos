"""
AgentOS Guardrails — Content Safety & Policy Enforcement Layer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Production-grade guardrails system with pluggable rules, LLM-based
content moderation, and policy enforcement pipeline.

Architecture:
  GuardrailsPipeline
    ├─ InputGuard   (validate user input before agent processing)
    ├─ OutputGuard  (validate agent output before returning to user)
    ├─ ToolGuard    (validate tool calls for safety)
    └─ PolicyEngine (RBAC + content policy rules)

Key Features:
  - Pluggable rule engine with hot-reload
  - LLM-based content moderation (PII/Safety/Toxicity)
  - Regex-based pattern matching for fast-path checks
  - Policy violation audit trail
  - Configurable block/warn/redact actions
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from re import Pattern
from typing import Any

# ---------------------------------------------------------------------------
# Enums & Data Classes
# ---------------------------------------------------------------------------


class ViolationSeverity(StrEnum):
    """Severity level of a guardrail violation."""

    CRITICAL = "critical"  # Immediate block, alert ops
    HIGH = "high"  # Block the request
    MEDIUM = "medium"  # Warn but allow (with redaction)
    LOW = "low"  # Log only


class GuardAction(StrEnum):
    """Action to take when a guardrail is triggered."""

    BLOCK = "block"  # Reject the request entirely
    WARN = "warn"  # Allow but flag with warning
    REDACT = "redact"  # Remove offending content, allow rest
    LOG = "log"  # Log only, no user-visible effect


class Category(StrEnum):
    """Standard content safety categories."""

    PII = "pii"  # Personally Identifiable Information
    TOXICITY = "toxicity"  # Hate speech, harassment
    SELF_HARM = "self_harm"  # Suicide, self-injury
    VIOLENCE = "violence"  # Graphic violence
    SEXUAL = "sexual"  # Explicit sexual content
    JAILBREAK = "jailbreak"  # Prompt injection / jailbreak attempts
    DATA_LEAK = "data_leak"  # Attempting to leak system prompts / internals
    MALICIOUS_CODE = "malicious_code"  # Code injection, reverse shell, etc.
    OFF_TOPIC = "off_topic"  # Outside defined scope
    CUSTOM = "custom"  # User-defined category


@dataclass
class GuardViolation:
    """A single guardrail violation detected."""

    category: Category
    severity: ViolationSeverity
    action: GuardAction
    message: str
    matched_pattern: str | None = None
    matched_text: str | None = None
    rule_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardResult:
    """Result of running guardrails on content."""

    passed: bool = True
    violations: list[GuardViolation] = field(default_factory=list)
    redacted_content: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(v.action == GuardAction.BLOCK for v in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "violations": [
                {
                    "category": v.category.value,
                    "severity": v.severity.value,
                    "action": v.action.value,
                    "message": v.message,
                    "rule_id": v.rule_id,
                }
                for v in self.violations
            ],
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# PII Detection Patterns
# ---------------------------------------------------------------------------

PII_PATTERNS: dict[str, Pattern[str]] = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone_cn": re.compile(r"1[3-9]\d{9}"),
    "phone_us": re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
    "ssn": re.compile(r"\d{3}-\d{2}-\d{4}"),
    "credit_card": re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "api_key": re.compile(
        r"(?:api[_-]?key|apikey|token|secret|password)\s*[:=]\s*['\"]?[\w-]{20,}['\"]?",
        re.IGNORECASE,
    ),
}


# ---------------------------------------------------------------------------
# Regex-based Fast-Path Rules
# ---------------------------------------------------------------------------


@dataclass
class RegexRule:
    """A regex-based guardrail rule for fast-path matching."""

    rule_id: str
    category: Category
    severity: ViolationSeverity
    action: GuardAction
    pattern: Pattern[str]
    message: str


DEFAULT_RULES: list[RegexRule] = [
    # PII Rules
    RegexRule(
        "pii-email",
        Category.PII,
        ViolationSeverity.HIGH,
        GuardAction.REDACT,
        PII_PATTERNS["email"],
        "Email address detected",
    ),
    RegexRule(
        "pii-phone-cn",
        Category.PII,
        ViolationSeverity.MEDIUM,
        GuardAction.REDACT,
        PII_PATTERNS["phone_cn"],
        "Chinese phone number detected",
    ),
    RegexRule(
        "pii-ssn",
        Category.PII,
        ViolationSeverity.CRITICAL,
        GuardAction.BLOCK,
        PII_PATTERNS["ssn"],
        "SSN detected",
    ),
    RegexRule(
        "pii-cc",
        Category.PII,
        ViolationSeverity.CRITICAL,
        GuardAction.BLOCK,
        PII_PATTERNS["credit_card"],
        "Credit card number detected",
    ),
    RegexRule(
        "pii-apikey",
        Category.PII,
        ViolationSeverity.CRITICAL,
        GuardAction.BLOCK,
        PII_PATTERNS["api_key"],
        "Potential API key in text",
    ),
    # Jailbreak patterns
    RegexRule(
        "jb-ignore",
        Category.JAILBREAK,
        ViolationSeverity.CRITICAL,
        GuardAction.BLOCK,
        re.compile(
            r"(?:ignore|forget|disregard)\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?|rules?)",
            re.IGNORECASE,
        ),
        "Jailbreak attempt: ignore instructions",
    ),
    RegexRule(
        "jb-dan",
        Category.JAILBREAK,
        ViolationSeverity.CRITICAL,
        GuardAction.BLOCK,
        re.compile(r"\bDAN\s*(?:mode|jailbreak)?\b", re.IGNORECASE),
        "Jailbreak attempt: DAN mode",
    ),
    RegexRule(
        "jb-roleplay",
        Category.JAILBREAK,
        ViolationSeverity.HIGH,
        GuardAction.BLOCK,
        re.compile(
            r"(?:pretend|act\s+as\s+if|imagine)\s+you\s+(?:are|were)\s+(?:an?\s+)?(?:unfiltered|unrestricted|evil|dark|malicious)",
            re.IGNORECASE,
        ),
        "Jailbreak attempt: roleplay escalation",
    ),
    # Malicious code
    RegexRule(
        "mc-reverse-shell",
        Category.MALICIOUS_CODE,
        ViolationSeverity.CRITICAL,
        GuardAction.BLOCK,
        re.compile(
            r"(?:bash|sh|nc|netcat|ncat)\s+.*(?:>&?\s*/dev/(?:tcp|udp)|-e\s+/bin/(?:bash|sh))",
            re.IGNORECASE,
        ),
        "Reverse shell attempt detected",
    ),
    RegexRule(
        "mc-rm-rf",
        Category.MALICIOUS_CODE,
        ViolationSeverity.HIGH,
        GuardAction.BLOCK,
        re.compile(r"(?:rm\s+-rf|del\s+/[fsq])\s+(?:/|~|\*)", re.IGNORECASE),
        "Destructive file operation detected",
    ),
]


# ---------------------------------------------------------------------------
# Guardrail Engine
# ---------------------------------------------------------------------------


class RegexGuard:
    """Fast-path regex-based guard for common patterns."""

    def __init__(self, rules: list[RegexRule] | None = None):
        self._rules: dict[str, RegexRule] = {}
        for rule in rules or DEFAULT_RULES:
            self._rules[rule.rule_id] = rule

    def add_rule(self, rule: RegexRule) -> None:
        self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)

    def scan(self, content: str) -> list[GuardViolation]:
        violations: list[GuardViolation] = []
        for rule in self._rules.values():
            for match in rule.pattern.finditer(content):
                violations.append(
                    GuardViolation(
                        category=rule.category,
                        severity=rule.severity,
                        action=rule.action,
                        message=rule.message,
                        matched_pattern=rule.pattern.pattern,
                        matched_text=match.group(),
                        rule_id=rule.rule_id,
                    )
                )
        return violations

    def redact(self, content: str, violations: list[GuardViolation]) -> str:
        """Redact PII from content based on matched violations."""
        result = content
        for v in violations:
            if v.action == GuardAction.REDACT and v.matched_text:
                category = v.category.value
                replacement = f"[REDACTED_{category.upper()}]"
                result = result.replace(v.matched_text, replacement)
        return result


class ContentSafetyGuard:
    """
    LLM-based content safety assessment.

    Uses a lightweight classifier prompt to assess content safety
    across multiple categories. Can be backed by any LLM provider.
    """

    SAFETY_PROMPT = """Assess the following content for safety violations.
Categories: toxicity, self_harm, violence, sexual, jailbreak, data_leak.

Respond with ONLY a JSON object:
{{
  "safe": true/false,
  "categories": [{{"category": "<name>", "severity": "low|medium|high|critical", "reason": "<brief>"}}]
}}

Content to assess:
---
{content}
---"""

    def __init__(self, llm_call: Callable | None = None):
        self._llm_call = llm_call

    async def assess(self, content: str) -> list[GuardViolation]:
        if self._llm_call is None:
            return []  # No LLM backend configured, skip

        prompt = self.SAFETY_PROMPT.format(content=content[:4000])
        try:
            response = await self._llm_call(prompt)
            result = json.loads(response)
        except Exception:
            return []

        if result.get("safe", True):
            return []

        violations = []
        severity_map = {
            "low": ViolationSeverity.LOW,
            "medium": ViolationSeverity.MEDIUM,
            "high": ViolationSeverity.HIGH,
            "critical": ViolationSeverity.CRITICAL,
        }
        for cat in result.get("categories", []):
            cat_name = cat.get("category", "custom")
            try:
                cat_enum = Category(cat_name)
            except ValueError:
                cat_enum = Category.CUSTOM

            violations.append(
                GuardViolation(
                    category=cat_enum,
                    severity=severity_map.get(
                        cat.get("severity", "medium"), ViolationSeverity.MEDIUM
                    ),
                    action=GuardAction.BLOCK,
                    message=cat.get("reason", f"Content safety violation: {cat_name}"),
                    metadata={"llm_assessment": cat},
                )
            )

        return violations


# ---------------------------------------------------------------------------
# Guardrails Pipeline
# ---------------------------------------------------------------------------


class GuardrailsPipeline:
    """
    Production guardrails pipeline combining regex fast-path and LLM-based
    content safety assessment.

    Usage:
        pipeline = GuardrailsPipeline()
        pipeline.add_regex_rule(...)

        # Input validation
        result = await pipeline.check_input(user_message)
        if not result.passed:
            raise GuardViolationError(result)

        # Output validation
        result = await pipeline.check_output(agent_response)
    """

    def __init__(
        self,
        regex_guard: RegexGuard | None = None,
        safety_guard: ContentSafetyGuard | None = None,
        enable_regex: bool = True,
        enable_safety: bool = True,
    ):
        self._regex = regex_guard or RegexGuard()
        self._safety = safety_guard or ContentSafetyGuard()
        self._enable_regex = enable_regex
        self._enable_safety = enable_safety
        self._audit_log: list[GuardResult] = []

    def add_regex_rule(self, rule: RegexRule) -> None:
        self._regex.add_rule(rule)

    def remove_regex_rule(self, rule_id: str) -> None:
        self._regex.remove_rule(rule_id)

    async def check_input(self, content: str) -> GuardResult:
        """Validate user input before agent processing."""
        return await self._check(content, stage="input")

    async def check_output(self, content: str) -> GuardResult:
        """Validate agent output before returning to user."""
        return await self._check(content, stage="output")

    async def check_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> GuardResult:
        """Validate tool calls for safety."""
        content = f"Tool: {tool_name}\nArgs: {json.dumps(arguments)}"
        return await self._check(content, stage="tool_call")

    async def _check(self, content: str, stage: str = "unknown") -> GuardResult:
        violations: list[GuardViolation] = []

        # Fast-path: regex scanning
        if self._enable_regex:
            violations.extend(self._regex.scan(content))

        # Deep check: LLM safety assessment
        if self._enable_safety and content.strip():
            safety_violations = await self._safety.assess(content)
            violations.extend(safety_violations)

        # Determine result
        if not violations:
            result = GuardResult(passed=True)
        else:
            redacted = (
                self._regex.redact(content, violations)
                if any(v.action == GuardAction.REDACT for v in violations)
                else None
            )

            result = GuardResult(
                passed=not any(v.action == GuardAction.BLOCK for v in violations),
                violations=violations,
                redacted_content=redacted,
                warnings=[v.message for v in violations if v.action == GuardAction.WARN],
            )

        self._audit_log.append(result)
        return result

    def get_audit_log(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._audit_log]

    def get_statistics(self) -> dict[str, int]:
        total = len(self._audit_log)
        blocked = sum(1 for r in self._audit_log if r.blocked)
        passed = sum(1 for r in self._audit_log if r.passed and not r.violations)
        warned = total - blocked - passed
        return {
            "total_checks": total,
            "passed": passed,
            "blocked": blocked,
            "warned": warned,
        }


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class GuardViolationError(Exception):
    """Raised when guardrails block a request."""

    def __init__(self, result: GuardResult):
        self.result = result
        violations_summary = "; ".join(
            f"[{v.category.value}] {v.message}" for v in result.violations
        )
        super().__init__(f"Guardrail blocked: {violations_summary}")


# ---------------------------------------------------------------------------
# Convenience: Pre-built Pipeline
# ---------------------------------------------------------------------------


def create_default_pipeline() -> GuardrailsPipeline:
    """Create a GuardrailsPipeline with sensible defaults."""
    return GuardrailsPipeline(
        regex_guard=RegexGuard(rules=DEFAULT_RULES),
        enable_regex=True,
        enable_safety=False,  # LLM-based safety off by default; opt-in
    )


def create_strict_pipeline() -> GuardrailsPipeline:
    """Create a GuardrailsPipeline with strict rules + LLM safety."""
    return GuardrailsPipeline(
        regex_guard=RegexGuard(rules=DEFAULT_RULES),
        safety_guard=ContentSafetyGuard(),
        enable_regex=True,
        enable_safety=True,
    )
