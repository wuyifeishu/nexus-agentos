"""
v1.9.5: Human-in-the-Loop (HITL) breakpoint system.

Enables task execution to pause at configurable checkpoints for human
review, approval, or intervention before continuing.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class BreakpointType(str, Enum):
    """Types of human-in-the-loop breakpoints."""

    BEFORE_TASK = "before_task"       # Before a sub-task starts
    AFTER_RESULT = "after_result"     # After a sub-task produces output
    ON_FAILURE = "on_failure"         # When a sub-task fails
    ON_LOW_CONFIDENCE = "on_low_confidence"  # When fusion confidence is low
    MANUAL = "manual"                 # Explicitly placed by developer


class HumanDecision(str, Enum):
    """Human responses at a breakpoint."""

    APPROVE = "approve"       # Approve and continue
    REJECT = "reject"         # Reject and skip/retry
    RETRY = "retry"           # Reject and retry with feedback
    MODIFY = "modify"         # Accept with modifications
    ABORT = "abort"           # Abort entire task


@dataclass
class Breakpoint:
    """A checkpoint where execution pauses for human input."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    type: BreakpointType = BreakpointType.MANUAL
    task_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    options: list[str] = field(default_factory=lambda: ["approve", "reject", "retry", "abort"])
    timeout: float = 0.0       # 0 = no timeout
    created_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0
    decision: HumanDecision | None = None
    feedback: str = ""
    resolved: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "task_id": self.task_id,
            "message": self.message,
            "options": self.options,
            "resolved": self.resolved,
            "decision": self.decision.value if self.decision else None,
        }


@dataclass
class HITLConfig:
    """Configuration for human-in-the-loop behavior."""

    enabled: bool = True
    break_on_failure: bool = True
    break_on_low_confidence: float = 0.3   # confidence below this triggers break
    break_on_first_task: bool = False      # break before first sub-task
    break_on_every_task: bool = False
    break_on_final_result: bool = False    # break before returning final result
    max_pending_breakpoints: int = 5       # queue limit
    default_timeout: float = 300.0         # 5 min default


class HITLManager:
    """Manages human-in-the-loop breakpoints during task execution.

    Usage:
        hitl = HITLManager(config=HITLConfig(break_on_failure=True))

        # Register a callback for human input
        hitl.register_handler(my_human_input_function)

        # During execution:
        decision = await hitl.request_decision(
            bp_type=BreakpointType.ON_FAILURE,
            task_id="task_1",
            message="Task failed. Retry?",
            context={"error": "...", "attempts": 2}
        )
        if decision == HumanDecision.RETRY:
            ...
    """

    def __init__(
        self,
        config: HITLConfig | None = None,
        handler: Callable | None = None,
    ):
        self.config = config or HITLConfig()
        self._handler = handler
        self._breakpoints: dict[str, Breakpoint] = {}
        self._pending: list[Breakpoint] = []
        self._decision_queue: asyncio.Queue = asyncio.Queue()

    def register_handler(self, handler: Callable[[Breakpoint], HumanDecision]) -> None:
        """
        Register a human input handler.

        Args:
            handler: Callable that receives a Breakpoint and returns a HumanDecision.
                     Can be sync or async.
        """
        self._handler = handler

    async def request_decision(
        self,
        bp_type: BreakpointType,
        task_id: str,
        message: str,
        context: dict | None = None,
        timeout: float | None = None,
        options: list[str] | None = None,
    ) -> tuple[HumanDecision, str]:
        """
        Pause execution and request human decision.

        Args:
            bp_type: Type of breakpoint
            task_id: Current task identifier
            message: Human-readable message explaining what's needed
            context: Additional context for the decision
            timeout: Max wait time (None = use config default)
            options: Available decision options

        Returns:
            Tuple of (decision, feedback text)
        """
        if not self.config.enabled:
            return HumanDecision.APPROVE, ""

        bp = Breakpoint(
            type=bp_type,
            task_id=task_id,
            context=context or {},
            message=message,
            options=options or ["approve", "reject", "retry", "abort"],
            timeout=timeout or self.config.default_timeout,
        )

        self._breakpoints[bp.id] = bp
        self._pending.append(bp)

        # If pending exceeds limit, auto-approve oldest
        if len(self._pending) > self.config.max_pending_breakpoints:
            oldest = self._pending.pop(0)
            oldest.decision = HumanDecision.APPROVE
            oldest.resolved = True
            oldest.resolved_at = time.time()

        # Call handler
        if self._handler:
            try:
                result = self._handler(bp)
                if asyncio.iscoroutine(result):
                    result = await result
                if isinstance(result, HumanDecision):
                    bp.decision = result
                elif isinstance(result, tuple) and len(result) == 2:
                    bp.decision, bp.feedback = result
                else:
                    bp.decision = HumanDecision.APPROVE
            except Exception:
                bp.decision = HumanDecision.APPROVE
        else:
            # No handler — wait on queue
            try:
                decision, feedback = await asyncio.wait_for(
                    self._decision_queue.get(),
                    timeout=bp.timeout,
                )
                bp.decision = decision
                bp.feedback = feedback
            except asyncio.TimeoutError:
                bp.decision = HumanDecision.APPROVE

        bp.resolved = True
        bp.resolved_at = time.time()

        # Remove from pending
        if bp in self._pending:
            self._pending.remove(bp)

        return bp.decision, bp.feedback

    def provide_decision(
        self,
        breakpoint_id: str,
        decision: HumanDecision,
        feedback: str = "",
    ) -> None:
        """Provide a decision for a pending breakpoint (alternative to handler)."""
        if breakpoint_id in self._breakpoints:
            bp = self._breakpoints[breakpoint_id]
            self._decision_queue.put_nowait((decision, feedback))

    async def should_break_before_task(
        self, task_id: str, task_name: str
    ) -> bool:
        """Check if we should break before a sub-task."""
        if not self.config.enabled:
            return False
        if self.config.break_on_first_task or self.config.break_on_every_task:
            decision, _ = await self.request_decision(
                bp_type=BreakpointType.BEFORE_TASK,
                task_id=task_id,
                message=f"About to execute: {task_name}\nProceed?",
                options=["approve", "abort", "modify"],
            )
            if decision == HumanDecision.ABORT:
                return False
        return True

    async def should_break_on_result(
        self, task_id: str, output: Any, confidence: float
    ) -> tuple[HumanDecision, str]:
        """Check if we should break after a result."""
        if not self.config.enabled:
            return HumanDecision.APPROVE, ""

        # Low confidence trigger
        if confidence < self.config.break_on_low_confidence:
            return await self.request_decision(
                bp_type=BreakpointType.ON_LOW_CONFIDENCE,
                task_id=task_id,
                message=(
                    f"Low confidence result (confidence: {confidence:.2f})\n"
                    f"Output: {str(output)[:300]}\n"
                    f"What would you like to do?"
                ),
                context={"confidence": confidence, "output": str(output)[:500]},
                options=["approve", "retry", "modify", "abort"],
            )

        # Final result break
        if self.config.break_on_final_result:
            return await self.request_decision(
                bp_type=BreakpointType.AFTER_RESULT,
                task_id=task_id,
                message=f"Result: {str(output)[:300]}\nApprove?",
                context={"output": str(output)[:500]},
                options=["approve", "retry", "modify"],
            )

        return HumanDecision.APPROVE, ""

    async def should_break_on_failure(
        self, task_id: str, error: str, attempt: int
    ) -> tuple[HumanDecision, str]:
        """Check if we should break on failure."""
        if not self.config.enabled or not self.config.break_on_failure:
            return HumanDecision.RETRY, ""

        return await self.request_decision(
            bp_type=BreakpointType.ON_FAILURE,
            task_id=task_id,
            message=(
                f"Task failed (attempt {attempt})\n"
                f"Error: {error[:300]}\n"
                f"Retry, skip, or abort?"
            ),
            context={"error": error, "attempt": attempt},
            options=["retry", "abort", "modify"],
        )

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def total_breakpoints(self) -> int:
        return len(self._breakpoints)
