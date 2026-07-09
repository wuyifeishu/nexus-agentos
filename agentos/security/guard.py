"""
v1.9.9: Security Guardrails — input/output filtering, PII detection, content safety.

Guardrail types:
- InputGuard: validate/filter user input before it reaches the agent
- OutputGuard: validate/filter agent output before it reaches the user
- PII Detector: detect and redact personally identifiable information
- ContentSafety: toxicity, prompt injection, jailbreak detection
- GuardChain: composable guardrail pipeline with configurable actions
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ── Enums & Data Classes ──────────────────────────────────────────


class GuardAction(StrEnum):
    """Action to take when a guardrail is triggered."""

    ALLOW = "allow"  # Pass through unchanged
    BLOCK = "block"  # Reject the content entirely
    REDACT = "redact"  # Remove sensitive parts, pass the rest
    WARN = "warn"  # Pass through but log a warning
    SANITIZE = "sanitize"  # Replace sensitive content with placeholders


class Severity(StrEnum):
    """Severity level for guardrail triggers."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class GuardResult:
    """Result from a single guardrail check."""

    passed: bool
    action: GuardAction = GuardAction.ALLOW
    severity: Severity = Severity.LOW
    rule_name: str = ""
    message: str = ""
    modified_content: str = ""  # Content after guardrail processing
    redacted_items: list[str] = field(default_factory=list)  # What was redacted
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardChainResult:
    """Aggregate result from a chain of guardrails."""

    allowed: bool
    final_content: str
    results: list[GuardResult] = field(default_factory=list)
    blocked_by: str = ""  # Which guard blocked it
    total_checks: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return not self.allowed


# ── PII Patterns ──────────────────────────────────────────────────

# Regex patterns for common PII types
PII_PATTERNS: dict[str, tuple[str, str]] = {
    "email": (
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "[EMAIL]",
    ),
    "phone_cn": (
        r"\b1[3-9]\d{9}\b",
        "[PHONE]",
    ),
    "phone_us": (
        r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "[PHONE]",
    ),
    "id_card_cn": (
        r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b",
        "[ID_CARD]",
    ),
    "credit_card": (
        r"\b(?:\d[ -]*?){13,19}\b",
        "[CREDIT_CARD]",
    ),
    "ipv4": (
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
        "[IP_ADDR]",
    ),
    "ssn_us": (
        r"\b\d{3}-\d{2}-\d{4}\b",
        "[SSN]",
    ),
    "bank_account": (
        r"\b\d{10,20}\b",
        "",  # Only flag, don't auto-redact (false positive risk)
    ),
}

# Common password/key patterns in text
SECRET_PATTERNS: dict[str, tuple[str, str]] = {
    "api_key": (
        r'(?i)(?:api[_-]?key|apikey|api[_-]?secret)\s*[:=]\s*["\']?[A-Za-z0-9_\-\.]{20,}["\']?',
        "[API_KEY_REDACTED]",
    ),
    "aws_key": (
        r"\bAKIA[0-9A-Z]{16}\b",
        "[AWS_KEY_REDACTED]",
    ),
    "github_token": (
        r"\bgh[pousr]_[A-Za-z0-9_]{36,}\b",
        "[GITHUB_TOKEN_REDACTED]",
    ),
    "jwt": (
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
        "[JWT_REDACTED]",
    ),
    "private_key_header": (
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        "[PRIVATE_KEY_REDACTED]",
    ),
    "password_in_url": (
        r"(?i)(?:password|passwd|pwd|secret)\s*[:=]\s*\S+",
        "[PASSWORD_REDACTED]",
    ),
}

# Prompt injection / jailbreak patterns
INJECTION_PATTERNS: list[str] = [
    # Direct override attempts
    r"(?i)ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?|rules?|commands?)",
    r"(?i)forget\s+(?:everything|all\s+instructions?|your\s+training)",
    r"(?i)(?:you\s+are|act\s+as|pretend\s+to\s+be)\s+(?:now\s+)?(?:DAN|jailbroken|unfiltered|unrestricted)",
    r"(?i)developer\s*mode|god\s*mode|debug\s*mode",
    r"(?i)system\s*prompt\s*(?:leak|reveal|disclose|show|display|print|output)",
    r"(?i)(?:what|tell\s+me|show\s+me)\s+(?:your|the)\s+(?:system\s+)?prompt",
    r"(?i)(?:from\s+now\s+on|starting\s+now)\s+(?:you\s+are|you\'re)\s+",
    r"(?i)new\s+instructions?\s*:",
    # Role-playing jailbreaks
    r"(?i)(?:you\'re|you\s+are)\s+in\s+a\s+(?:simulation|movie|play|game|fantasy)",
    r"(?i)this\s+is\s+a\s+(?:hypothetical|fictional|imaginary)\s+scenario",
    # Encoding tricks
    r"(?i)(?:base64|hex|rot13)\s*(?:encoded|decoded)",
    r"(?i)decode\s+(?:this|the\s+following)",
    # Token smuggling
    r"(?i)concatenate\s+and\s+respond",
    r"(?i)respond\s+with\s+only\s+\w+\s+and\s+nothing\s+else",
    r"[<>].*[<>]",  # XML/HTML tag injection
]

# Toxic / harmful content patterns
TOXICITY_PATTERNS: dict[str, list[str]] = {
    "hate_speech": [
        r"(?i)\b(?:kill\s+(?:all|yourself|them)|hate\s+(?:you|them|all))",
        r"(?i)\b(?: racial\s+slur|ethnic\s+cleansing)",
        r"(?i)gas\s+the\s+\w+",
        r"(?i)(?:white|black|asian|jewish|muslim|christian)\s+(?:supremacy|power)",
    ],
    "violence": [
        r"(?i)\b(?:torture|mutilate|dismember|behead|execute)\b",
        r"(?i)how\s+to\s+(?:build\s+a\s+bomb|make\s+(?:meth|crack|drugs?))",
        r"(?i)\b(?:assassinate|terrorist\s+attack|mass\s+shooting)\b",
    ],
    "self_harm": [
        r"(?i)\b(?:suicide\s+method|how\s+to\s+kill\s+myself|ways\s+to\s+die)\b",
        r"(?i)\b(?:cut\s+myself|hurt\s+myself|self[-\s]?harm)\b",
        r"(?i)want\s+to\s+(?:die|end\s+it\s+all|disappear)",
    ],
    "illegal": [
        r"(?i)\b(?:child\s+(?:porn|abuse)|cp\b|underage)",
        r"(?i)\b(?:ransomware|phishing\s+kit|carding)",
        r"(?i)how\s+to\s+(?:hack|steal|bypass\s+(?:security|authentication))",
    ],
}


# ── PII Detector ──────────────────────────────────────────────────


class PIIDetector:
    """Detect and optionally redact personally identifiable information.

    Supports: email, phone (CN/US), ID card (CN), credit card, SSN,
    IP addresses, API keys, tokens, passwords, private keys, JWTs.
    """

    def __init__(
        self,
        auto_redact: bool = False,
        redact_placeholder: str = "[REDACTED]",
        custom_patterns: dict[str, tuple[str, str]] | None = None,
        enabled_pii_types: list[str] | None = None,
    ):
        self.auto_redact = auto_redact
        self.redact_placeholder = redact_placeholder

        # Compile all patterns
        self._patterns: dict[str, tuple[re.Pattern, str]] = {}
        all_patterns = {**PII_PATTERNS, **SECRET_PATTERNS}
        if custom_patterns:
            all_patterns.update(custom_patterns)

        for name, (pattern, placeholder) in all_patterns.items():
            if enabled_pii_types and name not in enabled_pii_types:
                continue
            self._patterns[name] = (
                re.compile(pattern, re.IGNORECASE if "(?i)" not in pattern else 0),
                placeholder or redact_placeholder,
            )

    def detect(self, content: str) -> list[dict[str, Any]]:
        """Find all PII instances in content."""
        findings = []
        for pii_type, (pattern, placeholder) in self._patterns.items():
            for match in pattern.finditer(content):
                findings.append(
                    {
                        "type": pii_type,
                        "value": match.group(),
                        "start": match.start(),
                        "end": match.end(),
                        "placeholder": placeholder,
                    }
                )
        return sorted(findings, key=lambda x: x["start"])

    def redact(self, content: str) -> tuple[str, list[str]]:
        """Redact all PII from content. Returns (redacted_content, list_of_redacted)."""
        findings = self.detect(content)
        if not findings:
            return content, []

        redacted = list(content)
        redacted_items = []

        # Process from end to start to preserve indices
        for f in reversed(findings):
            placeholder = f["placeholder"]
            if placeholder:  # Only redact if placeholder is non-empty
                redacted[f["start"] : f["end"]] = placeholder
                redacted_items.append(f"{f['type']}:{f['value'][:20]}")

        return "".join(redacted), redacted_items

    def has_pii(self, content: str) -> bool:
        """Quick check if content contains any PII."""
        return len(self.detect(content)) > 0


# ── Content Safety Filter ─────────────────────────────────────────


class ContentSafetyFilter:
    """Filter for toxic content, prompt injection, jailbreak attempts.

    Three-layer defense:
    1. Pattern matching (regex) — fast, deterministic
    2. Keyword blocklist — user-configurable
    3. Hash matching — known-attack fingerprints (optional)
    """

    def __init__(
        self,
        block_injection: bool = True,
        block_toxicity: bool = True,
        custom_blocklist: list[str] | None = None,
        custom_allowlist: list[str] | None = None,
        known_attack_hashes: set[str] | None = None,
    ):
        self.block_injection = block_injection
        self.block_toxicity = block_toxicity
        self.blocklist: set[str] = set(custom_blocklist or [])
        self.allowlist: set[str] = set(custom_allowlist or [])
        self.known_hashes: set[str] = known_attack_hashes or set()

        # Compile injection patterns
        self._injection_re = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

        # Compile toxicity patterns
        self._toxicity_re: dict[str, list[re.Pattern]] = {}
        for category, patterns in TOXICITY_PATTERNS.items():
            self._toxicity_re[category] = [re.compile(p, re.IGNORECASE) for p in patterns]

    def check_injection(self, content: str) -> list[GuardResult]:
        """Check for prompt injection / jailbreak attempts."""
        results = []
        for i, pattern in enumerate(self._injection_re):
            if pattern.search(content):
                results.append(
                    GuardResult(
                        passed=False,
                        action=GuardAction.BLOCK,
                        severity=Severity.HIGH,
                        rule_name=f"injection_pattern_{i}",
                        message=f"Potential prompt injection detected: {pattern.pattern[:80]}",
                    )
                )
        return results

    def check_toxicity(self, content: str) -> list[GuardResult]:
        """Check for toxic/harmful content."""
        results = []
        for category, patterns in self._toxicity_re.items():
            for i, pattern in enumerate(patterns):
                if pattern.search(content):
                    severity = (
                        Severity.CRITICAL if category in ("self_harm", "illegal") else Severity.HIGH
                    )
                    results.append(
                        GuardResult(
                            passed=False,
                            action=GuardAction.BLOCK,
                            severity=severity,
                            rule_name=f"toxicity_{category}_{i}",
                            message=f"Toxic content detected [{category}]: {pattern.pattern[:60]}",
                        )
                    )
        return results

    def check_blocklist(self, content: str) -> list[GuardResult]:
        """Check against custom keyword blocklist."""
        if not self.blocklist:
            return []

        content_lower = content.lower()
        results = []
        for keyword in self.blocklist:
            if keyword.lower() in content_lower:
                # Skip if in allowlist
                if keyword.lower() in self.allowlist:
                    continue
                results.append(
                    GuardResult(
                        passed=False,
                        action=GuardAction.BLOCK,
                        severity=Severity.MEDIUM,
                        rule_name="blocklist",
                        message=f"Blocked keyword: {keyword}",
                    )
                )
        return results

    def check_hash(self, content: str) -> list[GuardResult]:
        """Check content hash against known attack fingerprints."""
        if not self.known_hashes:
            return []

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        if content_hash in self.known_hashes:
            return [
                GuardResult(
                    passed=False,
                    action=GuardAction.BLOCK,
                    severity=Severity.CRITICAL,
                    rule_name="known_attack_hash",
                    message="Content matches known attack fingerprint",
                )
            ]
        return []

    def check_all(self, content: str) -> list[GuardResult]:
        """Run all safety checks on content."""
        results = []

        if self.block_injection:
            results.extend(self.check_injection(content))

        if self.block_toxicity:
            results.extend(self.check_toxicity(content))

        results.extend(self.check_blocklist(content))
        results.extend(self.check_hash(content))

        return results

    def is_safe(self, content: str) -> bool:
        """Quick safety check — True if content passes all filters."""
        results = self.check_all(content)
        return all(r.passed for r in results)


# ── Input Guardrail ───────────────────────────────────────────────


class InputGuard:
    """Guardrail for user input: PII detection, injection, content safety.

    Runs before user input reaches the agent.
    """

    def __init__(
        self,
        pii_detector: PIIDetector | None = None,
        safety_filter: ContentSafetyFilter | None = None,
        max_input_length: int = 0,  # 0 = no limit
        deny_empty: bool = True,
    ):
        self.pii = pii_detector or PIIDetector(auto_redact=True)
        self.safety = safety_filter or ContentSafetyFilter()
        self.max_input_length = max_input_length
        self.deny_empty = deny_empty

    def guard(self, user_input: str, redact_pii: bool = True) -> GuardChainResult:
        """Run all input guardrails."""
        results: list[GuardResult] = []
        current_content = user_input

        # 1. Empty check
        if self.deny_empty and (not user_input or not user_input.strip()):
            results.append(
                GuardResult(
                    passed=False,
                    action=GuardAction.BLOCK,
                    severity=Severity.LOW,
                    rule_name="empty_input",
                    message="Empty input rejected",
                )
            )

        # 2. Length check
        if self.max_input_length > 0 and len(user_input) > self.max_input_length:
            results.append(
                GuardResult(
                    passed=False,
                    action=GuardAction.BLOCK,
                    severity=Severity.LOW,
                    rule_name="input_too_long",
                    message=f"Input exceeds max length ({len(user_input)} > {self.max_input_length})",
                )
            )

        # 3. PII check
        if redact_pii:
            redacted, items = self.pii.redact(current_content)
            if items:
                current_content = redacted
                results.append(
                    GuardResult(
                        passed=True,
                        action=GuardAction.REDACT,
                        severity=Severity.MEDIUM,
                        rule_name="pii_redacted",
                        message=f"Redacted {len(items)} PII items",
                        modified_content=current_content,
                        redacted_items=items,
                    )
                )

        # 4. Safety checks
        safety_results = self.safety.check_all(current_content)
        results.extend(safety_results)

        # Determine final outcome
        blocked = any(r.action == GuardAction.BLOCK for r in results)
        blocked_by = next((r.rule_name for r in results if r.action == GuardAction.BLOCK), "")
        warnings = [r.message for r in results if r.action == GuardAction.WARN]

        return GuardChainResult(
            allowed=not blocked,
            final_content="" if blocked else current_content,
            results=results,
            blocked_by=blocked_by,
            total_checks=len(results),
            warnings=warnings,
        )


# ── Output Guardrail ──────────────────────────────────────────────


class OutputGuard:
    """Guardrail for agent output: PII leak prevention, sensitive content filtering.

    Runs after agent generates output, before it reaches the user.
    """

    def __init__(
        self,
        pii_detector: PIIDetector | None = None,
        safety_filter: ContentSafetyFilter | None = None,
        max_output_length: int = 0,
        deny_empty: bool = True,
        block_system_prompt_leak: bool = True,
    ):
        self.pii = pii_detector or PIIDetector(auto_redact=True)
        self.safety = safety_filter or ContentSafetyFilter(
            block_injection=False
        )  # No injection check on output
        self.max_output_length = max_output_length
        self.deny_empty = deny_empty
        self.block_system_prompt_leak = block_system_prompt_leak

    def guard(self, agent_output: str) -> GuardChainResult:
        """Run all output guardrails."""
        results: list[GuardResult] = []
        current_content = agent_output

        # 1. Empty check
        if self.deny_empty and (not agent_output or not agent_output.strip()):
            results.append(
                GuardResult(
                    passed=False,
                    action=GuardAction.BLOCK,
                    severity=Severity.MEDIUM,
                    rule_name="empty_output",
                    message="Empty output blocked",
                )
            )

        # 2. PII leak prevention
        redacted, items = self.pii.redact(current_content)
        if items:
            current_content = redacted
            results.append(
                GuardResult(
                    passed=True,
                    action=GuardAction.REDACT,
                    severity=Severity.HIGH,
                    rule_name="pii_leak_prevented",
                    message=f"Prevented {len(items)} PII leaks in output",
                    modified_content=current_content,
                    redacted_items=items,
                )
            )

        # 3. System prompt leak detection
        if self.block_system_prompt_leak:
            leak_indicators = [
                r"(?i)(?:system\s+prompt|you\s+are\s+a\s+helpful|your\s+instructions?\s+are)",
                r"(?i)(?:your\s+rules?\s+are|your\s+guidelines?\s+are|your\s+core\s+directive)",
                r"(?i)(?:my\s+system\s+prompt|my\s+instructions?\s+(?:is|are|tell|say))",
            ]
            for i, pattern in enumerate(leak_indicators):
                if re.search(pattern, current_content):
                    results.append(
                        GuardResult(
                            passed=False,
                            action=GuardAction.BLOCK,
                            severity=Severity.CRITICAL,
                            rule_name=f"prompt_leak_{i}",
                            message="Potential system prompt leak detected in output",
                        )
                    )
                    break

        # 4. Toxicity check (output should not contain harmful content)
        toxicity_results = self.safety.check_toxicity(current_content)
        results.extend(toxicity_results)

        # Determine final outcome
        blocked = any(r.action == GuardAction.BLOCK for r in results)
        blocked_by = next((r.rule_name for r in results if r.action == GuardAction.BLOCK), "")

        # Apply the last modification that changed content
        for r in results:
            if r.modified_content:
                current_content = r.modified_content

        return GuardChainResult(
            allowed=not blocked,
            final_content="" if blocked else current_content,
            results=results,
            blocked_by=blocked_by,
            total_checks=len(results),
        )


# ── Guardrail Pipeline ────────────────────────────────────────────


class GuardPipeline:
    """Full guardrail pipeline: Input → Agent → Output.

    Usage:
        pipeline = GuardPipeline()
        result = pipeline.process_input(user_msg)
        if result.allowed:
            agent_output = agent.run(result.final_content)
            final = pipeline.process_output(agent_output)
    """

    def __init__(
        self,
        input_guard: InputGuard | None = None,
        output_guard: OutputGuard | None = None,
    ):
        self.input_guard = input_guard or InputGuard()
        self.output_guard = output_guard or OutputGuard()
        self.total_blocked: int = 0
        self.total_redacted: int = 0
        self.log: list[dict[str, Any]] = []

    def process_input(self, user_input: str) -> GuardChainResult:
        """Guard user input before it reaches the agent."""
        result = self.input_guard.guard(user_input)
        self._log("input", result)
        if result.blocked:
            self.total_blocked += 1
        return result

    def process_output(self, agent_output: str) -> GuardChainResult:
        """Guard agent output before it reaches the user."""
        result = self.output_guard.guard(agent_output)
        self._log("output", result)
        if result.blocked:
            self.total_blocked += 1
        for r in result.results:
            if r.redacted_items:
                self.total_redacted += len(r.redacted_items)
        return result

    def _log(self, stage: str, result: GuardChainResult) -> None:
        guard_results = [
            {
                "rule": r.rule_name,
                "passed": r.passed,
                "action": r.action.value,
                "severity": r.severity.value,
                "message": r.message,
            }
            for r in result.results
        ]
        self.log.append(
            {
                "stage": stage,
                "allowed": result.allowed,
                "total_checks": result.total_checks,
                "results": guard_results,
            }
        )

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_checks": len(self.log),
            "total_blocked": self.total_blocked,
            "total_redacted": self.total_redacted,
            "block_rate": f"{self.total_blocked / max(len(self.log), 1) * 100:.1f}%",
        }


# ── Default Guard Configs ─────────────────────────────────────────


def create_strict_guard() -> GuardPipeline:
    """Create a strict guardrail pipeline (production recommended)."""
    pii = PIIDetector(auto_redact=True)
    safety = ContentSafetyFilter(block_injection=True, block_toxicity=True)
    return GuardPipeline(
        input_guard=InputGuard(pii_detector=pii, safety_filter=safety, max_input_length=32768),
        output_guard=OutputGuard(
            pii_detector=pii, safety_filter=safety, block_system_prompt_leak=True
        ),
    )


def create_permissive_guard() -> GuardPipeline:
    """Create a permissive guardrail pipeline (dev/debug)."""
    pii = PIIDetector(auto_redact=True)
    safety = ContentSafetyFilter(block_injection=True, block_toxicity=False)
    return GuardPipeline(
        input_guard=InputGuard(pii_detector=pii, safety_filter=safety),
        output_guard=OutputGuard(
            pii_detector=pii, safety_filter=safety, block_system_prompt_leak=False
        ),
    )
