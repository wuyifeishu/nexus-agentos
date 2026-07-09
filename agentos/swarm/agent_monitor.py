"""
v1.9.6: Agent Self-Monitoring & Quality Gates.

Each agent execution passes through configurable quality checks before
results are accepted. Failed checks trigger automatic fallback or retry.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


class GateAction(StrEnum):
    ACCEPT = "accept"  # Accept result as-is
    RETRY = "retry"  # Retry the task
    FALLBACK = "fallback"  # Use fallback result
    ABORT = "abort"  # Abort the task
    WARN = "warn"  # Accept but flag warning


@dataclass
class GateResult:
    """Result of a single quality gate check."""

    name: str
    status: GateStatus = GateStatus.PASS
    action: GateAction = GateAction.ACCEPT
    score: float = 1.0
    threshold: float = 0.7
    detail: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "action": self.action.value,
            "score": self.score,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass
class MonitorReport:
    """Complete self-monitoring report for a task execution."""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    task_name: str = ""
    gates: list[GateResult] = field(default_factory=list)
    overall_status: GateStatus = GateStatus.PASS
    overall_action: GateAction = GateAction.ACCEPT
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    warned: int = 0
    duration_ms: float = 0.0
    retries_used: int = 0
    max_retries: int = 3
    fallback_used: bool = False
    output_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "gates": [g.to_dict() for g in self.gates],
            "overall_status": self.overall_status.value,
            "overall_action": self.overall_action.value,
            "total_checks": self.total_checks,
            "passed": self.passed,
            "failed": self.failed,
            "warned": self.warned,
            "duration_ms": f"{self.duration_ms:.1f}",
            "retries_used": self.retries_used,
            "fallback_used": self.fallback_used,
            "output_summary": self.output_summary[:200],
        }


class QualityGate:
    """A single quality check that validates agent output.

    Built-in gate types: output_not_empty, output_length, confidence_min,
    schema_valid, no_error, latency_max.
    """

    def __init__(
        self,
        name: str,
        check_fn: Callable[[Any, dict], tuple[bool, str, float]],
        threshold: float = 0.7,
        on_fail: GateAction = GateAction.RETRY,
        on_warn: GateAction = GateAction.ACCEPT,
        max_retries: int = 1,
    ):
        """
        Args:
            name: Gate name for reporting
            check_fn: (output, context) → (passed, detail, score)
            threshold: Score threshold for pass (0-1)
            on_fail: Action when gate fails
            on_warn: Action when gate warns
            max_retries: Max retries for this specific gate
        """
        self.name = name
        self._check = check_fn
        self.threshold = threshold
        self.on_fail = on_fail
        self.on_warn = on_warn
        self.max_retries = max_retries

    def evaluate(self, output: Any, context: dict | None = None) -> GateResult:
        """Run the quality check."""
        ctx = context or {}
        try:
            passed, detail, score = self._check(output, ctx)
        except Exception as e:
            return GateResult(
                name=self.name,
                status=GateStatus.FAIL,
                action=self.on_fail,
                score=0.0,
                threshold=self.threshold,
                detail=f"Gate check error: {e}",
            )

        if score >= self.threshold and passed:
            return GateResult(
                name=self.name,
                status=GateStatus.PASS,
                action=GateAction.ACCEPT,
                score=score,
                threshold=self.threshold,
                detail=detail,
            )
        elif score >= self.threshold * 0.6:
            return GateResult(
                name=self.name,
                status=GateStatus.WARN,
                action=self.on_warn,
                score=score,
                threshold=self.threshold,
                detail=detail,
            )
        else:
            return GateResult(
                name=self.name,
                status=GateStatus.FAIL,
                action=self.on_fail,
                score=score,
                threshold=self.threshold,
                detail=detail,
            )


class AgentMonitor:
    """
    Self-monitoring pipeline for agent task execution.

    Runs each task output through a chain of quality gates. Based on gate results,
    decides whether to accept, retry, fallback, or abort.

    Usage:
        monitor = AgentMonitor()
        monitor.add_gate(output_not_empty_gate)
        monitor.add_gate(confidence_min_gate)

        result = await monitor.monitor_execution(
            task_fn=lambda: agent.run(task),
            task_name="research_query",
        )
        if result.overall_action == GateAction.ACCEPT:
            ...
    """

    def __init__(self, max_retries: int = 3, default_fallback: Any = None):
        self._gates: list[QualityGate] = []
        self.max_retries = max_retries
        self.default_fallback = default_fallback

    def add_gate(self, gate: QualityGate) -> AgentMonitor:
        """Add a quality gate to the pipeline."""
        self._gates.append(gate)
        return self

    def add_gates(self, gates: list[QualityGate]) -> AgentMonitor:
        """Add multiple quality gates."""
        self._gates.extend(gates)
        return self

    async def monitor_execution(
        self,
        task_fn: Callable[[], Any],
        task_name: str = "",
        context: dict | None = None,
        fallback_fn: Callable[[], Any] | None = None,
    ) -> tuple[Any, MonitorReport]:
        """Execute a task with full monitoring and quality gating.

        Args:
            task_fn: Async/sync function that executes the task
            context: Additional context for gate evaluation
            fallback_fn: Fallback function to call if gates fail with FALLBACK action

        Returns:
            Tuple of (final_output, monitor_report)
        """
        import asyncio

        report = MonitorReport(task_name=task_name)
        ctx = context or {}
        start = time.time()

        output = None
        retries = 0

        while retries <= self.max_retries:
            # Execute task
            try:
                result = task_fn()
                if asyncio.iscoroutine(result):
                    output = await result
                else:
                    output = result
            except Exception as e:
                report.gates.append(
                    GateResult(
                        name="execution_error",
                        status=GateStatus.FAIL,
                        action=GateAction.RETRY,
                        score=0.0,
                        detail=str(e),
                    )
                )
                retries += 1
                if retries > self.max_retries:
                    report.overall_status = GateStatus.FAIL
                    report.overall_action = GateAction.FALLBACK
                    break
                continue

            # Run gates
            report.gates = []
            any_fail = False
            worst_action = GateAction.ACCEPT
            action_prio = {
                GateAction.ACCEPT: 0,
                GateAction.WARN: 1,
                GateAction.RETRY: 2,
                GateAction.FALLBACK: 3,
                GateAction.ABORT: 4,
            }

            for gate in self._gates:
                gr = gate.evaluate(output, ctx)
                report.gates.append(gr)

                if gr.status == GateStatus.FAIL:
                    any_fail = True
                if action_prio.get(gr.action, 0) > action_prio.get(worst_action, 0):
                    worst_action = gr.action

            # Tally
            report.total_checks = len(report.gates)
            report.passed = sum(1 for g in report.gates if g.status == GateStatus.PASS)
            report.failed = sum(1 for g in report.gates if g.status == GateStatus.FAIL)
            report.warned = sum(1 for g in report.gates if g.status == GateStatus.WARN)

            if not any_fail:
                report.overall_status = GateStatus.PASS
                report.overall_action = worst_action
                report.retries_used = retries
                report.output_summary = self._summarize(output)
                report.duration_ms = (time.time() - start) * 1000
                return output, report

            # Handle failure
            if worst_action == GateAction.ABORT:
                report.overall_status = GateStatus.FAIL
                report.overall_action = GateAction.ABORT
                report.retries_used = retries
                report.duration_ms = (time.time() - start) * 1000
                return output, report

            if worst_action == GateAction.FALLBACK:
                report.overall_status = GateStatus.FAIL
                report.overall_action = GateAction.FALLBACK
                report.retries_used = retries
                report.fallback_used = True
                report.duration_ms = (time.time() - start) * 1000

                if fallback_fn:
                    fb_result = fallback_fn()
                    if asyncio.iscoroutine(fb_result):
                        output = await fb_result
                    else:
                        output = fb_result
                elif self.default_fallback is not None:
                    output = self.default_fallback

                report.output_summary = self._summarize(output)
                return output, report

            # RETRY or WARN — continue loop
            retries += 1

        # Exhausted retries
        report.overall_status = GateStatus.FAIL if report.failed > 0 else GateStatus.WARN
        report.overall_action = GateAction.FALLBACK
        report.retries_used = retries
        report.duration_ms = (time.time() - start) * 1000

        if fallback_fn:
            fb_result = fallback_fn()
            if asyncio.iscoroutine(fb_result):
                output = await fb_result
            else:
                output = fb_result
        elif self.default_fallback is not None:
            output = self.default_fallback

        report.output_summary = self._summarize(output)
        return output, report

    def _summarize(self, output: Any) -> str:
        """Create a brief summary of output for reporting."""
        if output is None:
            return "None"
        s = str(output)
        if len(s) > 200:
            return s[:197] + "..."
        return s


# ── Built-in Quality Gates ────────────────────────────────────────


def output_not_empty(
    min_length: int = 1,
    threshold: float = 0.9,
) -> QualityGate:
    """Gate: output must not be empty."""

    def check(output: Any, ctx: dict) -> tuple[bool, str, float]:
        s = str(output).strip() if output else ""
        score = min(1.0, len(s) / max(min_length, 1))
        if not s:
            return False, "Output is empty", 0.0
        if len(s) < min_length:
            return False, f"Output too short ({len(s)} < {min_length})", score
        return True, f"Output length {len(s)} OK", 1.0

    return QualityGate("output_not_empty", check, threshold, on_fail=GateAction.RETRY)


def output_length_range(
    min_len: int = 10,
    max_len: int = 10000,
    threshold: float = 0.8,
) -> QualityGate:
    """Gate: output length must be in range."""

    def check(output: Any, ctx: dict) -> tuple[bool, str, float]:
        s = str(output).strip() if output else ""
        length = len(s)
        if length < min_len:
            return False, f"Output too short: {length} < {min_len}", length / max(min_len, 1)
        if length > max_len:
            return False, f"Output too long: {length} > {max_len}", max_len / length
        return True, f"Output length {length} OK", 1.0

    return QualityGate("output_length", check, threshold, on_fail=GateAction.WARN)


def no_error_output(threshold: float = 0.95) -> QualityGate:
    """Gate: output must not contain error/exception patterns."""
    ERROR_PATTERNS = [  # noqa: N806
        "Traceback (most recent call last)",
        "Error:",
        "Exception:",
        "failed to",
        "cannot be",
        "invalid",
        "permission denied",
    ]

    def check(output: Any, ctx: dict) -> tuple[bool, str, float]:
        s = str(output).lower()
        hits = [p for p in ERROR_PATTERNS if p.lower() in s]
        if hits:
            score = 1.0 - (len(hits) / len(ERROR_PATTERNS))
            return False, f"Error patterns found: {hits[:3]}", max(0, score)
        return True, "No error patterns", 1.0

    return QualityGate("no_error", check, threshold, on_fail=GateAction.RETRY)


def contains_keywords(
    keywords: list[str],
    min_hits: int = 1,
    threshold: float = 0.7,
) -> QualityGate:
    """Gate: output must contain at least N keywords."""

    def check(output: Any, ctx: dict) -> tuple[bool, str, float]:
        s = str(output).lower()
        hits = [kw for kw in keywords if kw.lower() in s]
        score = min(1.0, len(hits) / max(min_hits, 1))
        if len(hits) < min_hits:
            missing = [kw for kw in keywords if kw.lower() not in s]
            return False, f"Missing keywords: {missing[:5]}", score
        return True, f"Found {len(hits)}/{len(keywords)} keywords", 1.0

    return QualityGate("keywords", check, threshold, on_fail=GateAction.WARN)


def latency_max(max_ms: float, threshold: float = 0.9) -> QualityGate:
    """Gate: execution must complete within time limit (ms)."""

    def check(output: Any, ctx: dict) -> tuple[bool, str, float]:
        elapsed = ctx.get("_latency_ms", 0)
        score = max(0, 1.0 - (elapsed / max_ms))
        if elapsed > max_ms:
            return False, f"Latency {elapsed:.0f}ms > {max_ms}ms", score
        return True, f"Latency {elapsed:.0f}ms OK", 1.0

    return QualityGate("latency", check, threshold, on_fail=GateAction.WARN)


def confidence_min(min_confidence: float = 0.5, threshold: float = 0.8) -> QualityGate:
    """Gate: fused confidence must meet minimum."""

    def check(output: Any, ctx: dict) -> tuple[bool, str, float]:
        confidence = ctx.get("_confidence", 0.0)
        score = min(1.0, confidence / max(min_confidence, 0.01))
        if confidence < min_confidence:
            return False, f"Confidence {confidence:.2f} < {min_confidence}", score
        return True, f"Confidence {confidence:.2f} OK", 1.0

    return QualityGate("confidence", check, threshold, on_fail=GateAction.RETRY)
