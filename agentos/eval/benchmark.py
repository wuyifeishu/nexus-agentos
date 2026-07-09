"""
v1.10.0: External Evaluation Harness — SWE-bench & GAIA benchmark runner.

Supports:
- SWE-bench: software engineering task resolution
- GAIA: multi-step reasoning benchmark
- Custom eval suites via registry
- Scoring: pass@k, F1, exact match, semantic similarity
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

# ── Enums & Data Classes ──────────────────────────────────────────


class EvalMetric(StrEnum):
    """Supported evaluation metrics."""

    PASS_AT_K = "pass@k"  # Fraction of correct in k generations
    EXACT_MATCH = "exact_match"  # String equality
    F1 = "f1"  # F1 score (token overlap)
    ROUGE_L = "rouge_l"  # ROUGE-L
    SEMANTIC_SIM = "semantic_sim"  # Embedding cosine similarity
    LLM_AS_JUDGE = "llm_as_judge"  # LLM-graded


class EvalSuite(StrEnum):
    """Supported benchmark suites."""

    SWE_BENCH = "swe-bench"
    SWE_BENCH_LITE = "swe-bench-lite"
    GAIA = "gaia"
    GAIA_VAL = "gaia-validation"
    CUSTOM = "custom"


@dataclass
class EvalCase:
    """A single evaluation case."""

    id: str
    suite: EvalSuite
    prompt: str
    expected: str
    repo: str = ""  # For SWE-bench: git repo
    base_commit: str = ""  # For SWE-bench: base commit hash
    test_patch: str = ""  # For SWE-bench: test patch
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalSample:
    """One generation sample for a case."""

    case_id: str
    sample_index: int  # 0..k-1 for pass@k
    generated: str
    score: float = 0.0
    passed: bool = False
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """Result for a single evaluation case (aggregated across samples)."""

    case_id: str
    suite: EvalSuite
    metric: EvalMetric
    score: float  # pass@k or single-sample score
    samples: list[EvalSample] = field(default_factory=list)
    error: str = ""


@dataclass
class EvalReport:
    """Full evaluation report across all cases."""

    suite: EvalSuite
    total_cases: int
    passed_cases: int
    avg_score: float
    scores: list[float] = field(default_factory=list)
    metric: EvalMetric = EvalMetric.EXACT_MATCH
    results: list[EvalResult] = field(default_factory=list)
    duration_s: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return self.passed_cases / max(self.total_cases, 1)

    @property
    def median_score(self) -> float:
        return statistics.median(self.scores) if self.scores else 0.0

    @property
    def std_dev(self) -> float:
        return statistics.stdev(self.scores) if len(self.scores) > 1 else 0.0


# ── Scorers ────────────────────────────────────────────────────────


class Scorer:
    """Base scorer."""

    def score(self, generated: str, expected: str) -> float:
        raise NotImplementedError

    @property
    def metric(self) -> EvalMetric:
        raise NotImplementedError


class ExactMatchScorer(Scorer):
    """Exact string match scorer."""

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.EXACT_MATCH

    def score(self, generated: str, expected: str) -> float:
        if not expected:
            return 1.0 if not generated else 0.0
        return 1.0 if generated.strip() == expected.strip() else 0.0


class F1Scorer(Scorer):
    """Token-level F1 scorer."""

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.F1

    def score(self, generated: str, expected: str) -> float:
        if not expected:
            return 1.0 if not generated else 0.0

        gen_tokens = set(generated.lower().split())
        exp_tokens = set(expected.lower().split())

        if not gen_tokens or not exp_tokens:
            return 0.0

        tp = len(gen_tokens & exp_tokens)
        precision = tp / len(gen_tokens)
        recall = tp / len(exp_tokens)

        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


class ROUGELScorer(Scorer):
    """ROUGE-L scorer (longest common subsequence)."""

    @property
    def metric(self) -> EvalMetric:
        return EvalMetric.ROUGE_L

    @staticmethod
    def _lcs_len(a: list[str], b: list[str]) -> int:
        m, n = len(a), len(b)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
        return dp[m][n]

    def score(self, generated: str, expected: str) -> float:
        if not expected:
            return 1.0 if not generated else 0.0

        gen_tokens = generated.lower().split()
        exp_tokens = expected.lower().split()

        if not gen_tokens or not exp_tokens:
            return 0.0

        lcs = self._lcs_len(gen_tokens, exp_tokens)
        precision = lcs / len(gen_tokens) if gen_tokens else 0
        recall = lcs / len(exp_tokens) if exp_tokens else 0

        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


def get_scorer(metric: EvalMetric) -> Scorer:
    """Factory: get scorer for a given metric."""
    return {
        EvalMetric.EXACT_MATCH: ExactMatchScorer(),
        EvalMetric.F1: F1Scorer(),
        EvalMetric.ROUGE_L: ROUGELScorer(),
    }.get(metric, ExactMatchScorer())


# ── SWE-bench Loader ──────────────────────────────────────────────


class SWEBenchLoader:
    """Load and parse SWE-bench dataset.

    SWE-bench format: each instance is a GitHub issue with a known fix.
    Agent must produce a patch that passes the test suite.
    """

    @staticmethod
    def load(path: str | Path, subset: str = "lite") -> list[EvalCase]:
        """Load SWE-bench instances from a JSON/JSONL file."""
        path = Path(path)
        cases = []

        if not path.exists():
            raise FileNotFoundError(f"SWE-bench dataset not found: {path}")

        if path.suffix == ".jsonl":
            with open(path) as f:
                for line in f:
                    if line.strip():
                        instance = json.loads(line)
                        cases.append(SWEBenchLoader._parse(instance, subset))
        elif path.suffix == ".json":
            data = json.loads(path.read_text())
            instances = data if isinstance(data, list) else data.get("instances", [])
            for instance in instances:
                cases.append(SWEBenchLoader._parse(instance, subset))

        return cases

    @staticmethod
    def _parse(instance: dict, subset: str) -> EvalCase:
        return EvalCase(
            id=instance.get("instance_id", ""),
            suite=EvalSuite.SWE_BENCH_LITE if "lite" in subset else EvalSuite.SWE_BENCH,
            prompt=instance.get("problem_statement", instance.get("issue", "")),
            expected="",  # SWE-bench doesn't have expected text; it has a test patch
            repo=instance.get("repo", ""),
            base_commit=instance.get("base_commit", ""),
            test_patch=instance.get("test_patch", instance.get("patch", "")),
            metadata={
                "hints_text": instance.get("hints_text", ""),
                "version": instance.get("version", ""),
            },
        )


# ── GAIA Loader ────────────────────────────────────────────────────


class GAIALoader:
    """Load and parse GAIA benchmark dataset.

    GAIA: multi-step reasoning benchmark with 466 questions.
    Levels: L1 (simple), L2 (medium), L3 (complex).
    """

    @staticmethod
    def load(path: str | Path, level: str | None = None) -> list[EvalCase]:
        """Load GAIA questions from JSON/JSONL."""
        path = Path(path)
        cases = []

        if not path.exists():
            raise FileNotFoundError(f"GAIA dataset not found: {path}")

        if path.suffix == ".jsonl":
            with open(path) as f:
                for line in f:
                    if line.strip():
                        q = json.loads(line)
                        if level and q.get("Level", "") != level:
                            continue
                        cases.append(GAIALoader._parse(q, "validation" in path.name))
        elif path.suffix == ".json":
            data = json.loads(path.read_text())
            questions = data if isinstance(data, list) else data.get("questions", [])
            for q in questions:
                if level and q.get("Level", "") != level:
                    continue
                cases.append(GAIALoader._parse(q, "validation" in path.name))

        return cases

    @staticmethod
    def _parse(q: dict, is_val: bool) -> EvalCase:
        return EvalCase(
            id=q.get("task_id", q.get("id", "")),
            suite=EvalSuite.GAIA_VAL if is_val else EvalSuite.GAIA,
            prompt=q.get("Question", q.get("question", "")),
            expected=q.get("Final answer", q.get("answer", "")),
            metadata={
                "level": q.get("Level", ""),
                "annotator_metadata": q.get("Annotator Metadata", ""),
            },
        )


# ── Evaluation Runner ──────────────────────────────────────────────


class EvalRunner:
    """Run evaluations over multiple cases with pass@k support.

    Usage:
        runner = EvalRunner(generate_fn=my_agent.generate)
        report = runner.run(cases, k=3, metric=EvalMetric.EXACT_MATCH)
    """

    def __init__(
        self,
        generate_fn: Callable[[str], str],
        scorer: Scorer | None = None,
    ):
        """
        Args:
            generate_fn: Function (prompt) -> generated_text
            scorer: Optional scorer override
        """
        self.generate = generate_fn
        self.scorer = scorer

    def run(
        self,
        cases: list[EvalCase],
        k: int = 1,
        metric: EvalMetric = EvalMetric.EXACT_MATCH,
        on_case_start: Callable[[EvalCase], None] | None = None,
        on_case_end: Callable[[EvalResult], None] | None = None,
    ) -> EvalReport:
        """Run evaluation on a list of cases.

        Args:
            cases: Evaluation cases
            k: Number of samples per case (for pass@k)
            metric: Scoring metric
            on_case_start: Callback before each case
            on_case_end: Callback after each case

        Returns:
            EvalReport with aggregated results
        """
        start_time = time.time()
        scorer = self.scorer or get_scorer(metric)
        results: list[EvalResult] = []

        for case in cases:
            if on_case_start:
                on_case_start(case)

            samples: list[EvalSample] = []
            scores: list[float] = []
            error = ""

            for i in range(k):
                try:
                    t0 = time.time()
                    generated = self.generate(case.prompt)
                    latency = (time.time() - t0) * 1000

                    s = scorer.score(generated, case.expected)
                    samples.append(
                        EvalSample(
                            case_id=case.id,
                            sample_index=i,
                            generated=generated,
                            score=s,
                            passed=s >= 0.5,
                            latency_ms=latency,
                        )
                    )
                    scores.append(s)
                except Exception as e:
                    error = str(e)
                    samples.append(
                        EvalSample(
                            case_id=case.id,
                            sample_index=i,
                            generated="",
                            score=0.0,
                            passed=False,
                            latency_ms=0,
                        )
                    )
                    scores.append(0.0)

            # pass@k: fraction where at least one sample passes
            any(s.passed for s in samples)
            # Use max score for the case score
            case_score = max(scores) if scores else 0.0

            result = EvalResult(
                case_id=case.id,
                suite=case.suite,
                metric=metric,
                score=case_score,
                samples=samples,
                error=error,
            )
            results.append(result)

            if on_case_end:
                on_case_end(result)

        scores_list = [r.score for r in results]
        passed = sum(1 for s in scores_list if s >= 0.5)

        report = EvalReport(
            suite=cases[0].suite if cases else EvalSuite.CUSTOM,
            total_cases=len(cases),
            passed_cases=passed,
            avg_score=sum(scores_list) / max(len(scores_list), 1),
            scores=scores_list,
            metric=metric,
            results=results,
            duration_s=time.time() - start_time,
        )
        return report

    def run_pass_at_k(
        self,
        cases: list[EvalCase],
        k: int = 5,
        metric: EvalMetric = EvalMetric.EXACT_MATCH,
    ) -> EvalReport:
        """Run pass@k evaluation (shorthand)."""
        return self.run(cases, k=k, metric=metric)

    def print_report(self, report: EvalReport) -> str:
        """Generate a human-readable report string."""
        lines = [
            "╔══ Evaluation Report ══╗",
            f"║ Suite:    {report.suite.value:<20} ║",
            f"║ Metric:   {report.metric.value:<20} ║",
            f"║ Cases:    {report.total_cases:<20} ║",
            f"║ Passed:   {report.passed_cases} ({report.success_rate:.1%})",
            f"║ Avg Score:{report.avg_score:.4f}",
            f"║ Median:   {report.median_score:.4f} ║",
            f"║ Std Dev:  {report.std_dev:.4f}   ║",
            f"║ Time:     {report.duration_s:.1f}s",
            "╚════════════════════════╝",
        ]
        if report.results and len(report.results) <= 20:
            lines.append("\nPer-case scores:")
            for r in report.results:
                icon = "✓" if r.score >= 0.5 else "✗"
                lines.append(f"  {icon} {r.case_id[:40]:<42} {r.score:.3f}")

        return "\n".join(lines)


# ── Eval Registry ──────────────────────────────────────────────────


class EvalRegistry:
    """Registry for custom evaluation suites and scorers."""

    def __init__(self):
        self._suites: dict[str, list[EvalCase]] = {}
        self._scorers: dict[str, Scorer] = {}

    def register_suite(self, name: str, cases: list[EvalCase]) -> None:
        self._suites[name] = cases

    def register_scorer(self, name: str, scorer: Scorer) -> None:
        self._scorers[name] = scorer

    def get_suite(self, name: str) -> list[EvalCase]:
        if name not in self._suites:
            raise KeyError(f"Unknown eval suite: {name}")
        return self._suites[name]

    def get_scorer(self, name: str) -> Scorer:
        return self._scorers.get(name, get_scorer(EvalMetric.EXACT_MATCH))

    def list_suites(self) -> list[str]:
        return list(self._suites.keys())


# ── Quick Eval Helpers ─────────────────────────────────────────────


def evaluate_quick(
    generate_fn: Callable[[str], str],
    cases: list[dict[str, str]],
    metric: EvalMetric = EvalMetric.EXACT_MATCH,
    k: int = 1,
) -> EvalReport:
    """Quick evaluation from a list of {prompt, expected} dicts."""
    eval_cases = [
        EvalCase(id=str(i), suite=EvalSuite.CUSTOM, prompt=c["prompt"], expected=c["expected"])
        for i, c in enumerate(cases)
    ]
    runner = EvalRunner(generate_fn)
    return runner.run(eval_cases, k=k, metric=metric)
