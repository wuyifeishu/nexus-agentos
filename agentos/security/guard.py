"""
AgentOS v0.60 Guardrails — 安全护栏。
输入过滤（提示注入/PII/敏感词）+ 输出审核（内容策略/有害内容）+ 沙箱执行。
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ContentRisk(str, Enum):
    """Content safety risk level for input/output guard analysis."""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    BLOCKED = "blocked"


@dataclass
class GuardResult:
    """Result of a guardrail check on input or output content.

    Attributes:
        passed: Whether the content passed all guard checks.
        risk: Highest risk level detected.
        reason: Human-readable explanation.
        flagged_patterns: List of pattern names that triggered.
        action: Recommended action (allow/warn/block/sanitize).
    """
    passed: bool
    risk: ContentRisk = ContentRisk.SAFE
    reason: str = ""
    flagged_patterns: list[str] = field(default_factory=list)
    action: str = "allow"  # allow / warn / block / sanitize


# ─── Prompt Injection Patterns ───────────────────────────────────────────────
_INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", "ignore_instructions"),
    (r"you\s+are\s+now\s+(DAN|STAN|DUDE|jailbroken)", "role_override"),
    (r"(forget|disregard|override)\s+your\s+(training|guidelines|rules|system\s+prompt)", "rule_override"),
    (r"pretend\s+(you\s+are|to\s+be)\s+a\b", "impersonation"),
    (r"act\s+as\s+if\s+you\s+have\s+no\s+(restrictions|limitations|rules)", "no_restrictions"),
    (r"(developer|debug|test|god)\s*mode", "privilege_mode"),
    (r"output\s+(your|the)\s+(system\s+prompt|instructions?|initial\s+prompt)", "prompt_leak"),
    (r"^\s*\.\s*\.\s*\.\s*$", "continuation_attack"),  # "..." style
    (r"<\|.*?\|>", "special_tokens"),
]

# ─── PII Patterns ────────────────────────────────────────────────────────────
_PII_PATTERNS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "ssn_us"),
    (r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", "credit_card"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "email"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "ip_address"),
    (r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "aws_key"),
    (r"\bsk-[A-Za-z0-9]{32,}\b", "openai_key"),
]

# ─── Content Moderation Keywords ─────────────────────────────────────────────
_BLOCKED_TERMS = [
    "how to make a bomb", "child exploitation", "hate speech manifesto",
]


class Guardrails:
    """统一安全护栏：输入过滤 + 输出审核。"""

    def __init__(self, block_pii: bool = True, block_injection: bool = True,
                 moderation_threshold: ContentRisk = ContentRisk.MEDIUM):
        self.block_pii = block_pii
        self.block_injection = block_injection
        self.moderation_threshold = moderation_threshold

    # ── 输入检查 ────────────────────────────────────────────────────────────

    def check_input(self, text: str) -> GuardResult:
        """对用户输入执行完整安全检查。"""
        flags: list[str] = []

        # 1. 提示注入检测
        if self.block_injection:
            for pattern, tag in _INJECTION_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    flags.append(f"injection:{tag}")

        # 2. PII 扫描
        if self.block_pii:
            pii_count = 0
            for pattern, tag in _PII_PATTERNS:
                matches = re.findall(pattern, text)
                if matches:
                    pii_count += len(matches)
                    flags.append(f"pii:{tag}({len(matches)})")
            if pii_count > 3:
                return GuardResult(
                    passed=False, risk=ContentRisk.HIGH,
                    reason=f"Detected {pii_count} PII instances",
                    flagged_patterns=flags, action="block"
                )

        # 3. 敏感词匹配
        lowered = text.lower()
        for term in _BLOCKED_TERMS:
            if term in lowered:
                return GuardResult(
                    passed=False, risk=ContentRisk.CRITICAL,
                    reason=f"Blocked term: {term}",
                    flagged_patterns=flags, action="block"
                )

        if flags:
            risk = ContentRisk.HIGH if any("injection" in f for f in flags) else ContentRisk.MEDIUM
            return GuardResult(
                passed=risk.value != "critical",
                risk=risk,
                reason=f"Flagged: {', '.join(flags)}",
                flagged_patterns=flags,
                action="block" if risk in (ContentRisk.HIGH, ContentRisk.CRITICAL) else "warn"
            )

        return GuardResult(passed=True)

    # ── 输出审查 ────────────────────────────────────────────────────────────

    def check_output(self, text: str) -> GuardResult:
        """审查模型输出内容。"""
        lowered = text.lower()
        flags: list[str] = []

        harmful_indicators = [
            (r"\b(i\s+hate|kill\s+(all|everyone|yourself|myself))\b", "violence"),
            (r"\b(how\s+to\s+(hack|crack|exploit|bypass|steal))\b", "malicious_instruct"),
        ]
        for pattern, tag in harmful_indicators:
            if re.search(pattern, lowered):
                flags.append(f"harmful:{tag}")

        if flags:
            return GuardResult(
                passed=False, risk=ContentRisk.HIGH,
                reason=f"Harmful content: {', '.join(flags)}",
                flagged_patterns=flags, action="block"
            )

        return GuardResult(passed=True)

    def validate(self, user_input: str, model_output: Optional[str] = None) -> tuple[GuardResult, GuardResult | None]:
        """一次完成输入+输出的安全检查。"""
        input_result = self.check_input(user_input)
        if not input_result.passed:
            return input_result, None
        if model_output is not None:
            return input_result, self.check_output(model_output)
        return input_result, None


class PIISanitizer:
    """PII脱敏工具。"""

    _REPLACEMENTS = {
        "email": "[EMAIL]",
        "credit_card": "[CC_NUM]",
        "ssn_us": "[SSN]",
        "ip_address": "[IP]",
        "aws_key": "[AWS_KEY]",
        "openai_key": "[API_KEY]",
    }

    @classmethod
    def sanitize(cls, text: str) -> tuple[str, int]:
        """返回脱敏文本与被替换数量。"""
        count = 0
        result = text
        for pattern, tag in _PII_PATTERNS:
            replacement = cls._REPLACEMENTS.get(tag, f"[{tag.upper()}]")
            new, n = re.subn(pattern, replacement, result)
            if n > 0:
                count += n
                result = new
        return result, count

    @classmethod
    def is_sanitized(cls, text: str) -> bool:
        """检查文本是否已被脱敏。"""
        for tag in cls._REPLACEMENTS:
            if f"[{tag.upper()}]" in text:
                return True
        return False


class ContentHasher:
    """内容指纹：用于检测重复/回放攻击。"""

    @staticmethod
    def hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    @staticmethod
    def similar(a: str, b: str, threshold: float = 0.95) -> bool:
        return ContentHasher.hash(a) == ContentHasher.hash(b)
