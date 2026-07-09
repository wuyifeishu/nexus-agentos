"""Pre-built HITL approval policies for common deployment scenarios."""

from agentos.hitl.approver import ApprovalPolicy, RiskLevel


def default_approval_policy() -> ApprovalPolicy:
    """Balanced policy: auto-approve low risk, require human for high/critical."""
    return ApprovalPolicy(
        require_approval_for_risk={RiskLevel.HIGH, RiskLevel.CRITICAL},
        auto_approve_domains=set(),
        block_domains=set(),
        max_auto_approve_cost_usd=0.01,
        require_approval_for_new_tools=True,
        timeout_seconds=120,
        max_pending_requests=10,
        cache_approval_seconds=300,
    )


def permissive_approval_policy() -> ApprovalPolicy:
    """Permissive policy: only require human for critical actions."""
    return ApprovalPolicy(
        require_approval_for_risk={RiskLevel.CRITICAL},
        auto_approve_domains={"read", "search", "fetch"},
        block_domains=set(),
        max_auto_approve_cost_usd=0.10,
        require_approval_for_new_tools=False,
        timeout_seconds=60,
        max_pending_requests=20,
        cache_approval_seconds=600,
    )


def strict_approval_policy() -> ApprovalPolicy:
    """Strict policy: require human for medium/high/critical actions."""
    return ApprovalPolicy(
        require_approval_for_risk={RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL},
        auto_approve_domains=set(),
        block_domains={"delete", "format", "exec"},
        max_auto_approve_cost_usd=0.0,
        require_approval_for_new_tools=True,
        timeout_seconds=300,
        max_pending_requests=5,
        cache_approval_seconds=0,
    )
