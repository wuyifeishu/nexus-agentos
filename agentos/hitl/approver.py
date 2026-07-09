"""
Human-in-the-Loop approval engine — request construction, risk assessment,
policy evaluation, and decision processing.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ApprovalStatus(StrEnum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


class RiskLevel(StrEnum):
    """Risk classification for approval decisions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ApprovalRequest:
    """A structured request for human approval."""

    request_id: str
    action: str
    description: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    data_affected: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalDecision:
    """Human decision on an approval request."""

    request_id: str
    status: ApprovalStatus
    reason: str = ""
    modified_args: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_approved(self) -> bool:
        return self.status in (ApprovalStatus.APPROVED, ApprovalStatus.MODIFIED)

    @property
    def is_rejected(self) -> bool:
        return self.status == ApprovalStatus.REJECTED


@dataclass
class ApprovalPolicy:
    """Configures which actions require human approval."""

    require_approval_for_risk: set[RiskLevel] = field(
        default_factory=lambda: {RiskLevel.HIGH, RiskLevel.CRITICAL}
    )
    auto_approve_domains: set[str] = field(default_factory=set)
    block_domains: set[str] = field(default_factory=set)
    max_auto_approve_cost_usd: float = 0.01
    require_approval_for_new_tools: bool = True
    timeout_seconds: int = 120
    max_pending_requests: int = 10
    cache_approval_seconds: int = 300


ApprovalCallback = Callable[[ApprovalRequest], ApprovalDecision]


class HumanInTheLoop:
    """Manages the human approval workflow for tool calls and mutations.

    Supports synchronous callbacks (CLI prompt, webhook, etc.) and
    configurable auto-approval rules based on risk and domain.
    """

    def __init__(
        self,
        policy: ApprovalPolicy | None = None,
        callback: ApprovalCallback | None = None,
    ):
        self.policy = policy or ApprovalPolicy()
        self.callback = callback
        self._pending: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self._history: list[tuple[ApprovalRequest, ApprovalDecision]] = []
        self._approval_cache: dict[str, tuple[float, ApprovalDecision]] = {}

    def request_approval(
        self,
        action: str,
        description: str = "",
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
        estimated_cost_usd: float = 0.0,
        data_affected: list[str] | None = None,
    ) -> ApprovalRequest:
        """Create an approval request and submit it for decision."""
        import time
        import uuid

        request_id = uuid.uuid4().hex[:12]
        req = ApprovalRequest(
            request_id=request_id,
            action=action,
            description=description,
            risk_level=risk_level,
            tool_name=tool_name,
            tool_args=tool_args or {},
            estimated_cost_usd=estimated_cost_usd,
            data_affected=data_affected or [],
        )

        # Check cache
        cache_key = f"{tool_name}:{action}"
        if cache_key in self._approval_cache:
            ts, decision = self._approval_cache[cache_key]
            if time.time() - ts < self.policy.cache_approval_seconds:
                self._decisions[request_id] = decision
                self._history.append((req, decision))
                return req

        # Evaluate auto-approval policy
        decision = self._evaluate_policy(req)
        if decision is not None:
            self._decisions[request_id] = decision
            self._history.append((req, decision))
            return req

        # Needs human input
        if len(self._pending) >= self.policy.max_pending_requests:
            decision = ApprovalDecision(
                request_id=request_id,
                status=ApprovalStatus.REJECTED,
                reason="Max pending requests exceeded.",
            )
            self._decisions[request_id] = decision
            self._history.append((req, decision))
            return req

        self._pending[request_id] = req
        return req

    def decide(self, request_id: str, decision: ApprovalDecision) -> None:
        """Record a human decision and remove from pending."""
        self._decisions[request_id] = decision
        if request_id in self._pending:
            req = self._pending.pop(request_id)
            self._history.append((req, decision))
            # Cache if approved
            if decision.is_approved:
                import time

                cache_key = f"{req.tool_name}:{req.action}"
                self._approval_cache[cache_key] = (time.time(), decision)

    def get_decision(self, request_id: str) -> ApprovalDecision | None:
        return self._decisions.get(request_id)

    def get_pending(self) -> list[ApprovalRequest]:
        return list(self._pending.values())

    def get_history(self) -> list[tuple[ApprovalRequest, ApprovalDecision]]:
        return self._history.copy()

    def clear_cache(self) -> None:
        self._approval_cache.clear()

    def _evaluate_policy(self, req: ApprovalRequest) -> ApprovalDecision | None:
        """Determine if the request can be auto-decided without human input."""

        # Blocked domains always rejected
        domain = req.tool_name.split(".")[0] if req.tool_name else ""
        if domain and domain in self.policy.block_domains:
            return ApprovalDecision(
                request_id=req.request_id,
                status=ApprovalStatus.REJECTED,
                reason=f"Domain '{domain}' is blocked by policy.",
            )

        # Auto-approve domains + low risk
        if domain and domain in self.policy.auto_approve_domains:
            if req.estimated_cost_usd <= self.policy.max_auto_approve_cost_usd:
                return ApprovalDecision(
                    request_id=req.request_id,
                    status=ApprovalStatus.APPROVED,
                    reason=f"Auto-approved: domain '{domain}' is trusted.",
                )

        # Risk level check
        if req.risk_level not in self.policy.require_approval_for_risk:
            return ApprovalDecision(
                request_id=req.request_id,
                status=ApprovalStatus.SKIPPED,
                reason=f"Risk level '{req.risk_level.value}' does not require approval.",
            )

        return None  # Needs human input

    def request_and_decide(
        self,
        action: str,
        description: str = "",
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
    ) -> tuple[ApprovalRequest, ApprovalDecision]:
        """Create request, attempt auto-decision, invoke callback if needed."""
        req = self.request_approval(
            action=action,
            description=description,
            risk_level=risk_level,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        decision = self.get_decision(req.request_id)
        if decision is not None:
            return req, decision

        if self.callback:
            decision = self.callback(req)
            self.decide(req.request_id, decision)
        else:
            decision = ApprovalDecision(
                request_id=req.request_id,
                status=ApprovalStatus.TIMED_OUT,
                reason="No human callback configured.",
            )

        return req, decision
