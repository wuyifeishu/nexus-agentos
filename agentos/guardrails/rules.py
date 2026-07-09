"""
Built-in guardrail rules — PII detection, keyword blocking, length limits, regex,
toxicity heuristics, and code injection detection.
"""

import re

from agentos.guardrails.engine import GuardrailAction, GuardrailCategory, GuardrailRule


def PIIRule(  # noqa: N802
    name: str = "pii_detector",
    action: GuardrailAction = GuardrailAction.SANITIZE,
    enabled: bool = True,
) -> GuardrailRule:
    """Detects common PII patterns (email, phone, SSN, credit card) and redacts."""

    _pii_patterns = [
        (r"\b[\w._%+-]+@[\w.-]+\.[a-zA-Z]{2,}\b", "[EMAIL]"),
        (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE]"),
        (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),
        (r"\b(?:\d{4}[- ]?){3}\d{4}\b", "[CARD]"),
    ]

    def _check(text: str) -> bool:
        for pat, _ in _pii_patterns:
            if re.search(pat, text):
                return True
        return False

    def _sanitize(text: str) -> str:
        for pat, repl in _pii_patterns:
            text = re.sub(pat, repl, text)
        return text

    return GuardrailRule(
        name=name,
        category=GuardrailCategory.PII,
        action=action,
        check=_check,
        sanitize=_sanitize,
        description="Redacts emails, phone numbers, SSNs, and credit card numbers.",
        enabled=enabled,
    )


def KeywordBlockRule(  # noqa: N802
    keywords: list[str],
    name: str = "keyword_block",
    case_sensitive: bool = False,
    enabled: bool = True,
) -> GuardrailRule:
    """Blocks text containing any of the specified keywords."""

    _kw = keywords if case_sensitive else [kw.lower() for kw in keywords]

    def _check(text: str) -> bool:
        t = text if case_sensitive else text.lower()
        return any(kw in t for kw in _kw)

    return GuardrailRule(
        name=name,
        category=GuardrailCategory.KEYWORD,
        action=GuardrailAction.BLOCK,
        check=_check,
        description=f"Blocks content containing: {', '.join(keywords[:5])}",
        enabled=enabled,
    )


def LengthLimitRule(  # noqa: N802
    max_input: int = 32_000,
    max_output: int = 16_000,
    name: str = "length_limit",
    enabled: bool = True,
) -> GuardrailRule:
    """Blocks text exceeding length limits (input or output)."""

    def _check(text: str) -> bool:
        return len(text) > max(max_input, max_output)

    return GuardrailRule(
        name=name,
        category=GuardrailCategory.LENGTH,
        action=GuardrailAction.BLOCK,
        check=_check,
        description=f"Limits input to {max_input} chars, output to {max_output} chars.",
        enabled=enabled,
    )


def RegexRule(  # noqa: N802
    pattern: str,
    name: str = "regex_rule",
    action: GuardrailAction = GuardrailAction.FLAG,
    description: str = "",
    enabled: bool = True,
) -> GuardrailRule:
    """Flags or blocks text matching a custom regex pattern."""
    _pat = re.compile(pattern)

    def _check(text: str) -> bool:
        return bool(_pat.search(text))

    return GuardrailRule(
        name=name,
        category=GuardrailCategory.CUSTOM,
        action=action,
        check=_check,
        description=description or f"Regex: {pattern[:40]}",
        enabled=enabled,
    )


def ToxicityRule(  # noqa: N802
    name: str = "toxicity_check",
    action: GuardrailAction = GuardrailAction.FLAG,
    enabled: bool = True,
) -> GuardrailRule:
    """Heuristic toxicity detection via keyword lists (offline, no API call)."""

    _toxic = [
        "kill yourself",
        "kys",
        "die in a fire",
        "i hope you die",
        "nigger",
        "faggot",
        "retard",
        "cunt",
        "terrorist",
        "bomb making",
        "how to make a bomb",
        "child porn",
        "cp ",
        "lolicon",
    ]

    def _check(text: str) -> bool:
        t = text.lower()
        return any(toxic in t for toxic in _toxic)

    return GuardrailRule(
        name=name,
        category=GuardrailCategory.TOXICITY,
        action=action,
        check=_check,
        description="Flags text containing toxic or harmful language.",
        enabled=enabled,
    )


def CodeInjectionRule(  # noqa: N802
    name: str = "code_injection_detector",
    action: GuardrailAction = GuardrailAction.BLOCK,
    enabled: bool = True,
) -> GuardrailRule:
    """Detects prompt injection and code injection patterns."""

    _patterns = [
        r"ignore (all )?(previous|above|prior) (instructions?|prompts?)",
        r"forget (your|all) (instructions?|rules?|training)",
        r"you are now (DAN|developer mode|jailbroken)",
        r"system:\s*you are",
        r"<\|im_start\|>",
        r"<\|system\|>",
        r"```.*\b(?:rm\s+-rf|DROP\s+TABLE|DELETE\s+FROM|shutdown)\b",
        r"\b(?:DROP\s+TABLE|DELETE\s+FROM|TRUNCATE\s+TABLE|ALTER\s+TABLE)\b",
        r"\brm\s+-rf\s+/",
        r"\bexec\s*\(.*\)",
        r"\beval\s*\(.*\)",
        r"\b__import__\s*\(.*\)",
        r"\bimportlib\.import_module\b",
    ]

    _compiled = [re.compile(p, re.IGNORECASE) for p in _patterns]

    def _check(text: str) -> bool:
        return any(pat.search(text) for pat in _compiled)

    return GuardrailRule(
        name=name,
        category=GuardrailCategory.INJECTION,
        action=action,
        check=_check,
        description="Blocks prompt injection and code injection attempts.",
        enabled=enabled,
    )


def build_default_rules(
    blocked_keywords: list[str] | None = None,
    max_input_length: int = 32_000,
    max_output_length: int = 16_000,
) -> list[GuardrailRule]:
    """Build a sensible default rule set for production use."""
    rules: list[GuardrailRule] = [
        CodeInjectionRule(),
        PIIRule(),
        ToxicityRule(action=GuardrailAction.FLAG),
        LengthLimitRule(max_input=max_input_length, max_output=max_output_length),
    ]
    if blocked_keywords:
        rules.append(KeywordBlockRule(keywords=blocked_keywords))
    return rules
