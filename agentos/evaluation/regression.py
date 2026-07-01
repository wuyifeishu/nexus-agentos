"""Evaluation regression testing for AgentOS.

Compare evaluation runs, detect regressions, generate CI artifacts.
Builds on top of agentos.evaluation core (GoldenDataset, Evaluator, EvalReport).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import json
import math
import time
import xml.etree.ElementTree as ET

from agentos.evaluation import GoldenDataset, Evaluator, EvalConfig, EvalReport, ScoreDetail


@dataclass
class RegressionCheck:
    """A single regression check result."""
    case_id: str
    baseline_score: float
    current_score: float
    delta: float
    regression: bool = False
    severity: str = "none"  # none | minor | moderate | severe
    details: str = ""


@dataclass
class RegressionReport:
    """Comparison report between baseline and current evaluation."""
    baseline_label: str = "baseline"
    current_label: str = "current"
    baseline: EvalReport = None
    current: EvalReport = None
    checks: List[RegressionCheck] = field(default_factory=list)
    total_regressions: int = 0
    total_improvements: int = 0
    pass_delta: float = 0.0
    score_delta: float = 0.0
    verdict: str = "OK"  # OK | WARN | FAIL

    def to_markdown(self) -> str:
        lines = [
            f"# Regression Report: {self.baseline_label} → {self.current_label}",
            "",
            f"**Verdict**: `{self.verdict}`",
            f"**Pass Rate**: {self.baseline.pass_rate:.1%} → {self.current.pass_rate:.1%} (Δ={self.pass_delta:+.1%})",
            f"**Avg Score**: {self.baseline.avg_score:.1f} → {self.current.avg_score:.1f} (Δ={self.score_delta:+.1f})",
            f"**Regressions**: {self.total_regressions} | **Improvements**: {self.total_improvements}",
            "",
        ]

        if self.checks:
            lines.append("## Detail")
            lines.append("| Case ID | Baseline | Current | Δ | Verdict |")
            lines.append("|---------|----------|---------|---|---------|")
            for c in self.checks:
                icon = "RECRESSION" if c.regression else "IMPROVED" if c.delta > 0 else "SAME"
                lines.append(
                    f"| {c.case_id} | {c.baseline_score:.1f} | {c.current_score:.1f} | "
                    f"{c.delta:+.1f} | {icon} |"
                )

        return "\n".join(lines)


class RegressionRunner:
    """Detect regressions by comparing baseline and current evaluation runs.

    Usage:
        runner = RegressionRunner(evaluator, baseline=report)
        report = await runner.check(current_report)
        # or sync:
        report = runner.check_sync(current_report)
    """

    def __init__(
        self,
        evaluator: Evaluator,
        baseline: Optional[EvalReport] = None,
        threshold: float = 5.0,
        severe_threshold: float = 20.0,
    ):
        self.evaluator = evaluator
        self.baseline = baseline
        self.threshold = threshold
        self.severe_threshold = severe_threshold

    async def run_baseline(self) -> EvalReport:
        """Run and store the baseline."""
        self.baseline = await self.evaluator.run()
        return self.baseline

    async def check(self, current: Optional[EvalReport] = None) -> RegressionReport:
        """Compare current against baseline. If current not given, run it."""
        if current is None:
            current = await self.evaluator.run()
        return self._compare(current)

    def check_sync(self, current: EvalReport) -> RegressionReport:
        """Synchronous version for testing."""
        return self._compare(current)

    def _compare(self, current: EvalReport) -> RegressionReport:

        if self.baseline is None:
            raise ValueError("No baseline set. Call run_baseline() first.")

        report = RegressionReport(
            baseline=self.baseline,
            current=current,
            pass_delta=current.pass_rate - self.baseline.pass_rate,
            score_delta=current.avg_score - self.baseline.avg_score,
        )

        # Build lookup from baseline results
        baseline_map: Dict[str, ScoreDetail] = {
            r.case_id: r for r in self.baseline.results
        }

        for current_result in current.results:
            cid = current_result.case_id
            baseline_result = baseline_map.get(cid)

            if baseline_result is None:
                # New case, no baseline comparison
                report.checks.append(RegressionCheck(
                    case_id=cid,
                    baseline_score=0,
                    current_score=current_result.total_score,
                    delta=0,
                    details="new case",
                ))
                continue

            delta = current_result.total_score - baseline_result.total_score
            regression = delta < -self.threshold

            severity = "none"
            if delta < -self.severe_threshold:
                severity = "severe"
            elif delta < -self.threshold:
                severity = "moderate"
            elif delta < 0:
                severity = "minor"

            if regression:
                report.total_regressions += 1
            elif delta > self.threshold:
                report.total_improvements += 1

            report.checks.append(RegressionCheck(
                case_id=cid,
                baseline_score=baseline_result.total_score,
                current_score=current_result.total_score,
                delta=round(delta, 1),
                regression=regression,
                severity=severity,
            ))

        # Verdict
        if report.total_regressions > 0:
            has_severe = any(c.severity == "severe" for c in report.checks)
            report.verdict = "FAIL" if has_severe else "WARN"

        return report


# --- Statistical Runner ---


@dataclass
class StatResult:
    """Statistical summary of N evaluation runs."""
    trials: int = 0
    pass_rates: List[float] = field(default_factory=list)
    avg_scores: List[float] = field(default_factory=list)
    mean_pass_rate: float = 0.0
    std_pass_rate: float = 0.0
    mean_score: float = 0.0
    std_score: float = 0.0
    ci95_pass_rate: Tuple[float, float] = (0.0, 0.0)
    ci95_score: Tuple[float, float] = (0.0, 0.0)

    def to_dict(self) -> dict:
        return {
            "trials": self.trials,
            "mean_pass_rate": round(self.mean_pass_rate, 4),
            "std_pass_rate": round(self.std_pass_rate, 4),
            "ci95_pass_rate": [round(x, 4) for x in self.ci95_pass_rate],
            "mean_score": round(self.mean_score, 2),
            "std_score": round(self.std_score, 2),
            "ci95_score": [round(x, 2) for x in self.ci95_score],
        }


class StatisticalRunner:
    """Run evaluation N times and compute statistics.

    Usage:
        srunner = StatisticalRunner(evaluator, trials=10)
        stats = await srunner.run()
    """

    def __init__(self, evaluator: Evaluator, trials: int = 5):
        self.evaluator = evaluator
        self.trials = max(trials, 2)

    async def run(self) -> StatResult:
        pass_rates = []
        avg_scores = []

        for i in range(self.trials):
            report = await self.evaluator.run()
            pass_rates.append(report.pass_rate)
            avg_scores.append(report.avg_score)

        return self._compute(pass_rates, avg_scores)

    def _compute(self, pass_rates: List[float], avg_scores: List[float]) -> StatResult:
        n = len(pass_rates)
        mean_pr = sum(pass_rates) / n
        var_pr = sum((x - mean_pr) ** 2 for x in pass_rates) / (n - 1)
        std_pr = math.sqrt(var_pr) if var_pr > 0 else 0

        mean_s = sum(avg_scores) / n
        var_s = sum((x - mean_s) ** 2 for x in avg_scores) / (n - 1)
        std_s = math.sqrt(var_s) if var_s > 0 else 0

        # 95% CI using t-distribution approximation (z for simplicity)
        z = 1.96
        ci_pr = (
            max(0, mean_pr - z * std_pr / math.sqrt(n)),
            min(1, mean_pr + z * std_pr / math.sqrt(n)),
        )
        ci_s = (
            mean_s - z * std_s / math.sqrt(n),
            mean_s + z * std_s / math.sqrt(n),
        )

        return StatResult(
            trials=n,
            pass_rates=pass_rates,
            avg_scores=avg_scores,
            mean_pass_rate=round(mean_pr, 4),
            std_pass_rate=round(std_pr, 4),
            mean_score=round(mean_s, 2),
            std_score=round(std_s, 2),
            ci95_pass_rate=(round(ci_pr[0], 4), round(ci_pr[1], 4)),
            ci95_score=(round(ci_s[0], 2), round(ci_s[1], 2)),
        )


# --- CI Exports ---


def to_junit_xml(report: EvalReport, suite_name: str = "AgentOS Eval") -> str:
    """Convert evaluation report to JUnit XML for CI integration (GitHub Actions, Jenkins, etc.)."""
    total = len(report.results)
    failed_count = sum(1 for r in report.results if not r.passed)
    total_time = sum(r.duration_ms for r in report.results) / 1000

    suite = ET.Element("testsuite", {
        "name": suite_name,
        "tests": str(total),
        "failures": str(failed_count),
        "errors": "0",
        "skipped": "0",
        "time": f"{total_time:.3f}",
        "timestamp": report.timestamp or "",
    })

    for result in report.results:
        testcase = ET.SubElement(suite, "testcase", {
            "classname": f"AgentOS.{report.dataset_name}",
            "name": result.case_id,
            "time": f"{result.duration_ms / 1000:.3f}",
        })

        if not result.passed:
            failure = ET.SubElement(testcase, "failure", {
                "type": "ScoreBelowThreshold",
                "message": f"Score {result.total_score:.1f}: {result.details}",
            })
            failure.text = f"Actual: {result.actual_output[:500]}\nErrors: {result.errors}"

        # Add score as property
        props = ET.SubElement(testcase, "properties")
        ET.SubElement(props, "property", {
            "name": "score", "value": f"{result.total_score:.1f}"
        })
        ET.SubElement(props, "property", {
            "name": "metrics", "value": json.dumps(result.metrics)
        })

    return ET.tostring(suite, encoding="unicode")


def to_json(report: EvalReport, indent: int = 2) -> str:
    """Serialize EvalReport to JSON string."""
    import dataclasses

    class ReportEncoder(json.JSONEncoder):
        def default(self, obj):
            if dataclasses.is_dataclass(obj):
                return dataclasses.asdict(obj)
            return super().default(obj)

    return json.dumps(report, cls=ReportEncoder, indent=indent, ensure_ascii=False)


def save_report(report: EvalReport, path: str, format: str = "markdown"):
    """Save evaluation report to file (markdown / json / junit)."""
    if format == "markdown":
        content = report.to_markdown()
    elif format == "json":
        content = to_json(report)
    elif format == "junit":
        content = to_junit_xml(report)
    else:
        raise ValueError(f"Unknown format: {format}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
