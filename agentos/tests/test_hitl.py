"""
Tests for HITL (Human-in-the-Loop) approval module.
"""

import pytest
from agentos.hitl.approver import (
    HumanInTheLoop,
    ApprovalRequest,
    ApprovalDecision,
    ApprovalStatus,
    RiskLevel,
    ApprovalPolicy,
)
from agentos.hitl.presets import (
    default_approval_policy,
    permissive_approval_policy,
    strict_approval_policy,
)


class TestApprovalRequest:
    def test_create_request(self):
        req = ApprovalRequest(
            request_id="abc-123",
            action="delete_file",
            description="Delete /tmp/test.txt",
            risk_level=RiskLevel.HIGH,
            tool_name="file.delete",
        )
        assert req.request_id == "abc-123"
        assert req.risk_level == RiskLevel.HIGH
        assert req.tool_name == "file.delete"


class TestApprovalDecision:
    def test_approved(self):
        d = ApprovalDecision(request_id="x", status=ApprovalStatus.APPROVED)
        assert d.is_approved
        assert not d.is_rejected

    def test_modified_is_approved(self):
        d = ApprovalDecision(request_id="x", status=ApprovalStatus.MODIFIED, modified_args={"force": True})
        assert d.is_approved

    def test_rejected(self):
        d = ApprovalDecision(request_id="x", status=ApprovalStatus.REJECTED, reason="too risky")
        assert d.is_rejected
        assert not d.is_approved


class TestHumanInTheLoop:
    def test_low_risk_auto_skipped(self):
        hitl = HumanInTheLoop(policy=default_approval_policy())
        req, decision = hitl.request_and_decide(
            action="read_file",
            description="Read config.yaml",
            risk_level=RiskLevel.LOW,
            tool_name="file.read",
        )
        assert decision.status == ApprovalStatus.SKIPPED

    def test_high_risk_needs_approval(self):
        hitl = HumanInTheLoop(policy=default_approval_policy())
        hitl.callback = lambda r: ApprovalDecision(
            request_id=r.request_id,
            status=ApprovalStatus.APPROVED,
            reason="OK",
        )
        req, decision = hitl.request_and_decide(
            action="delete_all",
            description="Delete production database",
            risk_level=RiskLevel.HIGH,
            tool_name="db.drop",
        )
        assert decision.is_approved

    def test_auto_approve_domain(self):
        policy = permissive_approval_policy()
        hitl = HumanInTheLoop(policy=policy)
        req, decision = hitl.request_and_decide(
            action="search",
            description="Search web",
            risk_level=RiskLevel.MEDIUM,
            tool_name="read.web_search",
        )
        assert decision.status == ApprovalStatus.APPROVED

    def test_blocked_domain(self):
        policy = strict_approval_policy()
        hitl = HumanInTheLoop(policy=policy)
        req, decision = hitl.request_and_decide(
            action="format",
            description="Format disk",
            risk_level=RiskLevel.CRITICAL,
            tool_name="delete.format_disk",
        )
        assert decision.status == ApprovalStatus.REJECTED

    def test_rejected_decision(self):
        hitl = HumanInTheLoop()
        hitl.callback = lambda r: ApprovalDecision(
            request_id=r.request_id,
            status=ApprovalStatus.REJECTED,
            reason="User said no",
        )
        _, decision = hitl.request_and_decide(
            action="delete", risk_level=RiskLevel.CRITICAL
        )
        assert decision.is_rejected

    def test_history(self):
        hitl = HumanInTheLoop()
        hitl.callback = lambda r: ApprovalDecision(
            request_id=r.request_id,
            status=ApprovalStatus.APPROVED,
        )
        hitl.request_and_decide(action="a1", risk_level=RiskLevel.HIGH)
        hitl.request_and_decide(action="a2", risk_level=RiskLevel.LOW)
        assert len(hitl.get_history()) == 2

    def test_pending_queue(self):
        hitl = HumanInTheLoop(policy=ApprovalPolicy(require_approval_for_risk={
            RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL
        }))
        req = hitl.request_approval(action="x", risk_level=RiskLevel.LOW)
        assert len(hitl.get_pending()) == 1

        decision = ApprovalDecision(request_id=req.request_id, status=ApprovalStatus.APPROVED)
        hitl.decide(req.request_id, decision)
        assert len(hitl.get_pending()) == 0
        assert hitl.get_decision(req.request_id).is_approved

    def test_approval_cache(self):
        hitl = HumanInTheLoop(policy=ApprovalPolicy(cache_approval_seconds=60))
        hitl.callback = lambda r: ApprovalDecision(
            request_id=r.request_id,
            status=ApprovalStatus.APPROVED,
        )
        # First call triggers callback
        req1, d1 = hitl.request_and_decide(
            action="read", tool_name="file.read", risk_level=RiskLevel.HIGH
        )
        assert d1.is_approved
        # Second call should use cache (same tool+action)
        req2, d2 = hitl.request_and_decide(
            action="read", tool_name="file.read", risk_level=RiskLevel.HIGH
        )
        assert d2.is_approved
        assert len(hitl.get_history()) == 2

    def test_critical_blocked_automatically(self):
        policy = strict_approval_policy()
        hitl = HumanInTheLoop(policy=policy)
        # No callback set, critical risk with blocked domain
        req, decision = hitl.request_and_decide(
            action="format",
            risk_level=RiskLevel.CRITICAL,
            tool_name="delete.format_disk",
        )
        assert decision.status == ApprovalStatus.REJECTED

    def test_max_pending(self):
        policy = ApprovalPolicy(
            require_approval_for_risk={RiskLevel.LOW},
            max_pending_requests=2,
        )
        hitl = HumanInTheLoop(policy=policy)
        hitl.request_approval(action="a1", risk_level=RiskLevel.LOW)
        hitl.request_approval(action="a2", risk_level=RiskLevel.LOW)
        req3 = hitl.request_approval(action="a3", risk_level=RiskLevel.LOW)
        d = hitl.get_decision(req3.request_id)
        assert d.status == ApprovalStatus.REJECTED
        assert "Max pending" in d.reason


class TestApprovalPresets:
    def test_default(self):
        p = default_approval_policy()
        assert RiskLevel.HIGH in p.require_approval_for_risk
        assert RiskLevel.LOW not in p.require_approval_for_risk

    def test_permissive(self):
        p = permissive_approval_policy()
        assert RiskLevel.CRITICAL in p.require_approval_for_risk
        assert RiskLevel.HIGH not in p.require_approval_for_risk

    def test_strict(self):
        p = strict_approval_policy()
        assert RiskLevel.MEDIUM in p.require_approval_for_risk
        assert "delete" in p.block_domains
