"""
AgentOS v1.3.11 — Human-in-the-Loop: structured approval workflows.

Provides approval request/response primitives, risk assessment, and
configurable approval policies for tool calls, code execution, and
data mutations.
"""
from agentos.hitl.approver import (
    HumanInTheLoop,
    ApprovalRequest,
    ApprovalDecision,
    ApprovalStatus,
    RiskLevel,
    ApprovalPolicy,
    ApprovalCallback,
)
from agentos.hitl.presets import (
    default_approval_policy,
    permissive_approval_policy,
    strict_approval_policy,
)

__all__ = [
    "HumanInTheLoop",
    "ApprovalRequest",
    "ApprovalDecision",
    "ApprovalStatus",
    "RiskLevel",
    "ApprovalPolicy",
    "ApprovalCallback",
    "default_approval_policy",
    "permissive_approval_policy",
    "strict_approval_policy",
]
