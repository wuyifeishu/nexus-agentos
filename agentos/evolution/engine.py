"""
Evolution Engine for NexusAgent.

Approval-based self-evolution system. Agents can propose
improvements, but changes require human approval before
being applied.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EvolutionStatus(StrEnum):
    """Status of an evolution proposal."""

    PENDING = "pending"  # Waiting for approval
    APPROVED = "approved"  # Approved, ready to apply
    REJECTED = "rejected"  # Rejected by human
    APPLIED = "applied"  # Successfully applied
    FAILED = "failed"  # Failed to apply


@dataclass
class EvolutionProposal:
    """
    A proposed evolution/improvement.

    Attributes:
        id: Unique identifier
        agent_name: Name of agent to evolve
        change_type: Type of change (prompt/tools/params)
        description: Human-readable description
        old_value: Current value
        new_value: Proposed new value
        status: Approval status
        created_at: Creation timestamp
        approved_at: Approval timestamp
        approved_by: Who approved
        applied_at: Application timestamp
        metadata: Additional metadata
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_name: str = ""
    change_type: str = "prompt"  # prompt, tools, params, behavior
    description: str = ""
    old_value: Any = None
    new_value: Any = None
    confidence: float = 0.0
    risk_level: str = "low"
    target_files: list[str] = field(default_factory=list)
    status: EvolutionStatus = EvolutionStatus.PENDING
    created_at: float = field(default_factory=time.time)
    approved_at: float | None = None
    approved_by: str | None = None
    applied_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "change_type": self.change_type,
            "description": self.description,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "status": self.status.value,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "applied_at": self.applied_at,
            "metadata": self.metadata,
        }


class EvolutionEngine:
    """
    Approval-based self-evolution engine.

    Manages the lifecycle of evolution proposals:
    1. Agent proposes improvement
    2. Human reviews and approves/rejects
    3. Approved changes are applied

    Usage:
        engine = EvolutionEngine()

        # Agent proposes improvement
        proposal = engine.propose(
            agent_name="SupportAgent",
            change_type="prompt",
            description="Improve greeting",
            old_value="Hello!",
            new_value="Hi there! How can I help?",
        )

        # Human approves
        engine.approve(proposal.id, approved_by="human")

        # Apply changes
        engine.apply(proposal.id)
    """

    def __init__(self):
        """Initialize evolution engine."""
        self._proposals: dict[str, EvolutionProposal] = {}
        self._approvers: dict[str, Callable[[EvolutionProposal], bool]] = {}

    def propose(
        self,
        agent_name: str,
        change_type: str,
        description: str,
        old_value: Any = None,
        new_value: Any = None,
        confidence: float = 0.0,
        risk_level: str = "low",
        target_files: list[str] | None = None,
        **metadata,
    ) -> EvolutionProposal:
        """
        Create a new evolution proposal.

        Args:
            agent_name: Name of agent to evolve
            change_type: Type of change
            description: Human-readable description
            old_value: Current value
            new_value: Proposed new value
            confidence: Confidence score (0-1)
            risk_level: Risk assessment (low/medium/high)
            target_files: Files to modify
            **metadata: Additional metadata

        Returns:
            Created EvolutionProposal
        """
        proposal = EvolutionProposal(
            agent_name=agent_name,
            change_type=change_type,
            description=description,
            old_value=old_value,
            new_value=new_value,
            confidence=confidence,
            risk_level=risk_level,
            target_files=target_files or [],
            metadata=metadata,
        )

        self._proposals[proposal.id] = proposal

        return proposal

    def get_proposal(self, proposal_id: str) -> EvolutionProposal | None:
        """
        Get a proposal by ID.

        Args:
            proposal_id: Proposal ID

        Returns:
            EvolutionProposal if found, None otherwise
        """
        return self._proposals.get(proposal_id)

    def list_proposals(
        self,
        status: EvolutionStatus | None = None,
        agent_name: str | None = None,
    ) -> list[EvolutionProposal]:
        """
        List proposals.

        Args:
            status: Filter by status
            agent_name: Filter by agent name

        Returns:
            List of matching proposals
        """
        proposals = list(self._proposals.values())

        if status:
            proposals = [p for p in proposals if p.status == status]

        if agent_name:
            proposals = [p for p in proposals if p.agent_name == agent_name]

        return proposals

    def approve(
        self,
        proposal_id: str,
        approved_by: str = "human",
    ) -> bool:
        """
        Approve a proposal.

        Args:
            proposal_id: Proposal ID
            approved_by: Who approved

        Returns:
            True if approved, False if not found
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            return False

        if proposal.status != EvolutionStatus.PENDING:
            return False

        proposal.status = EvolutionStatus.APPROVED
        proposal.approved_at = time.time()
        proposal.approved_by = approved_by

        return True

    def reject(
        self,
        proposal_id: str,
        reason: str = "",
    ) -> bool:
        """
        Reject a proposal.

        Args:
            proposal_id: Proposal ID
            reason: Reason for rejection

        Returns:
            True if rejected, False if not found
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            return False

        if proposal.status != EvolutionStatus.PENDING:
            return False

        proposal.status = EvolutionStatus.REJECTED
        proposal.metadata["rejection_reason"] = reason

        return True

    def apply(self, proposal_id: str) -> bool:
        """
        Apply an approved proposal. Performs actual file modifications.

        Args:
            proposal_id: Proposal ID

        Returns:
            True if applied, False otherwise
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            return False

        if proposal.status != EvolutionStatus.APPROVED:
            return False

        try:
            target_files = proposal.target_files or []
            old_val = proposal.old_value
            new_val = proposal.new_value

            if target_files and old_val is not None and new_val is not None:
                for fpath in target_files:
                    if not os.path.exists(fpath):
                        continue
                    with open(fpath) as f:
                        content = f.read()
                    old_str = str(old_val)
                    new_str = str(new_val)
                    if old_str in content:
                        content = content.replace(old_str, new_str, 1)
                        with open(fpath, "w") as f:
                            f.write(content)
                        proposal.metadata["modified_file"] = fpath

            proposal.status = EvolutionStatus.APPLIED
            proposal.applied_at = time.time()
            return True
        except Exception as e:
            proposal.status = EvolutionStatus.FAILED
            proposal.metadata["error"] = str(e)
            return False

    def register_approver(
        self,
        agent_name: str,
        approver: Callable[[EvolutionProposal], bool],
    ) -> None:
        """
        Register an approver for an agent.

        Args:
            agent_name: Agent name
            approver: Approval function
        """
        self._approvers[agent_name] = approver

    def auto_approve(self, proposal_id: str) -> bool:
        """
        Auto-approve using registered approver.

        Args:
            proposal_id: Proposal ID

        Returns:
            True if approved, False otherwise
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            return False

        approver = self._approvers.get(proposal.agent_name)
        if not approver:
            return False

        if approver(proposal):
            return self.approve(proposal_id, approved_by="auto")

        return False

    def get_stats(self) -> dict[str, Any]:
        """
        Get evolution statistics.

        Returns:
            Dict with proposal counts by status
        """
        stats = {
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "applied": 0,
            "failed": 0,
            "total": len(self._proposals),
        }

        for proposal in self._proposals.values():
            stats[proposal.status.value] += 1

        return stats
