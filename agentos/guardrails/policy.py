"""
Guardrail policy enforcement — cumulative violation tracking, rate limiting,
and session-scoped policy decisions.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

from agentos.guardrails.engine import GuardrailAction, GuardrailCategory, GuardrailResult


class PolicyViolation(str, Enum):
    """Policy-level violation reasons."""

    SESSION_BLOCKED = "session_blocked"
    RATE_LIMITED = "rate_limited"
    CUMULATIVE_VIOLATIONS = "cumulative_violations"
    CATEGORY_BANNED = "category_banned"


@dataclass
class GuardrailPolicy:
    """Session-scoped policy configuration."""

    max_total_violations: int = 5
    max_violations_per_category: dict[str, int] = field(default_factory=dict)
    window_seconds: int = 300
    auto_block_on: set[GuardrailCategory] = field(default_factory=set)
    on_session_block: str = "reject"  # reject / warn
    monitoring_callback: Callable[[str, Dict[str, Any]], None] | None = None

    def __post_init__(self):
        if not self.max_violations_per_category:
            self.max_violations_per_category = {
                GuardrailCategory.INJECTION.value: 2,
                GuardrailCategory.TOXICITY.value: 3,
                GuardrailCategory.KEYWORD.value: 3,
            }


class PolicyEnforcer:
    """Tracks violations per session and enforces cumulative policy."""

    def __init__(self, policy: Optional[GuardrailPolicy] = None):
        self.policy = policy or GuardrailPolicy()
        self._violation_count: int = 0
        self._category_counts: Dict[str, int] = {}
        self._session_blocked: bool = False
        self._violation_log: list[tuple[float, str, str]] = []

    def evaluate(self, result: GuardrailResult, category: str = "") -> PolicyViolation | None:
        """Evaluate a guardrail result against the current policy.

        Returns None if no policy violation, or the reason for violation.
        """
        if self._session_blocked:
            return PolicyViolation.SESSION_BLOCKED

        if result.action == GuardrailAction.PASS:
            return None

        import time
        now = time.time()

        self._violation_count += 1
        if category:
            self._category_counts[category] = self._category_counts.get(category, 0) + 1
        self._violation_log.append((now, category, result.action.value))

        # Clean old entries outside window
        cutoff = now - self.policy.window_seconds
        self._violation_log = [(t, c, a) for t, c, a in self._violation_log if t > cutoff]

        # Check cumulative violations
        if self._violation_count >= self.policy.max_total_violations:
            self._session_blocked = True
            self._emit("session_blocked", {"total_violations": self._violation_count})
            return PolicyViolation.CUMULATIVE_VIOLATIONS

        # Check per-category limits
        if category and category in self.policy.max_violations_per_category:
            limit = self.policy.max_violations_per_category[category]
            if self._category_counts[category] >= limit:
                self._emit("category_blocked", {"category": category, "count": self._category_counts[category]})
                return PolicyViolation.CATEGORY_BANNED

        return None

    def reset(self) -> None:
        """Reset all violation counters for a new session."""
        self._violation_count = 0
        self._category_counts.clear()
        self._session_blocked = False
        self._violation_log.clear()

    @property
    def is_blocked(self) -> bool:
        return self._session_blocked

    @property
    def total_violations(self) -> int:
        return self._violation_count

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        if self.policy.monitoring_callback:
            try:
                self.policy.monitoring_callback(event, data)
            except Exception:
                pass
