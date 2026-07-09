"""
AgentOS — Human-in-the-Loop: structured approval workflows + Gradio Dashboard.

Provides approval request/response primitives, risk assessment,
configurable approval policies, and a real-time Gradio approval UI.
"""

from agentos.hitl.approver import (
    ApprovalCallback,
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStatus,
    HumanInTheLoop,
    RiskLevel,
)
from agentos.hitl.gradio_ui import (
    AgentStatusSnapshot,
    ApprovalDashboard,
    ApprovalHistory,
    ApprovalQueue,
    ApprovalRequestUI,
    HITLUIBridge,
    RiskLevelUI,
    create_hitl_dashboard,
)
from agentos.hitl.gradio_ui import (
    ApprovalStatus as UIApprovalStatus,
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
