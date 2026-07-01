"""
AgentOS — Human-in-the-Loop: structured approval workflows + Gradio Dashboard.

Provides approval request/response primitives, risk assessment,
configurable approval policies, and a real-time Gradio approval UI.
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
from agentos.hitl.gradio_ui import (
    ApprovalDashboard,
    ApprovalQueue,
    HITLUIBridge,
    ApprovalStatus as UIApprovalStatus,
    RiskLevelUI,
    ApprovalRequestUI,
    ApprovalHistory,
    AgentStatusSnapshot,
    create_hitl_dashboard,
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
    # Gradio UI (v1.14.2)
    "ApprovalDashboard",
    "ApprovalQueue",
    "HITLUIBridge",
    "UIApprovalStatus",
    "RiskLevelUI",
    "ApprovalRequestUI",
    "ApprovalHistory",
    "AgentStatusSnapshot",
    "create_hitl_dashboard",
]
