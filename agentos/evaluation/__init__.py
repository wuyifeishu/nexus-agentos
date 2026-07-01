"""Agent Evaluation Framework for AgentOS v2.

Golden dataset management, regression testing, CI exports,
statistical analysis, auto-scoring across multiple dimensions,
SWE-bench style eval, multi-round evaluation, hallucination detection.

Sub-modules:
- scorers: ROUGE-L, BLEU, Semantic, Exact, Contains scoring + CompositeScorer
- regression: RegressionRunner, StatisticalRunner, JUnit/JSON exports
- suite: EvalSuiteRunner, SWEBenchEvaluator, HallucinationDetector, Leaderboard (v2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import json
import os
import time


@dataclass
class GoldenCase:
    """A single golden test case for agent evaluation.

    Each case represents a known input with expected output.
    """
    id: str
    prompt: str
    expected: str = ""
    expected_tools: List[str] = field(default_factory=list)
    expected_files: List[str] = field(default_factory=list)
    category: str = "general"
    difficulty: str = "medium"  # easy | medium | hard
    tags: List[str] = field(default_factory=list)
    max_tokens: int = 2000
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GoldenDataset:
    """Collection of golden test cases."""
    name: str
    version: str = "1.0"
    description: str = ""
    cases: List[GoldenCase] = field(default_factory=list)

    @classmethod
    def from_json(cls, path: str) -> "GoldenDataset":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cases = [GoldenCase(**c) for c in data.get("cases", [])]
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            cases=cases,
        )

    def to_json(self, path: str):
        data = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "case_count": len(self.cases),
            "cases": [
                {
                    "id": c.id,
                    "prompt": c.prompt,
                    "expected": c.expected,
                    "expected_tools": c.expected_tools,
                    "expected_files": c.expected_files,
                    "category": c.category,
                    "difficulty": c.difficulty,
                    "tags": c.tags,
                    "max_tokens": c.max_tokens,
                    "context": c.context,
                }
                for c in self.cases
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_case(self, case: GoldenCase):
        self.cases.append(case)

    def filter(self, category: str = "", difficulty: str = "", tags: List[str] = None) -> List[GoldenCase]:
        result = self.cases
        if category:
            result = [c for c in result if c.category == category]
        if difficulty:
            result = [c for c in result if c.difficulty == difficulty]
        if tags:
            result = [c for c in result if any(t in c.tags for t in tags)]
        return result


@dataclass
class ScoreDetail:
    """Detailed scoring for a single evaluation case."""
    case_id: str
    passed: bool = False
    total_score: float = 0.0
    max_score: float = 100.0
    metrics: Dict[str, float] = field(default_factory=dict)
    details: str = ""
    duration_ms: float = 0.0
    actual_output: str = ""
    errors: List[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """Complete evaluation report."""
    dataset_name: str = ""
    dataset_version: str = ""
    timestamp: str = ""
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    avg_score: float = 0.0
    avg_duration_ms: float = 0.0
    results: List[ScoreDetail] = field(default_factory=list)
    summary_by_category: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    summary_by_difficulty: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_markdown(self) -> str:
        lines = [
            f"# Evaluation Report: {self.dataset_name}",
            f"**Version**: {self.dataset_version} | **Date**: {self.timestamp}",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Cases | {self.total_cases} |",
            f"| Passed | {self.passed} |",
            f"| Failed | {self.failed} |",
            f"| Pass Rate | {self.pass_rate:.1%} |",
            f"| Avg Score | {self.avg_score:.1f} |",
            f"| Avg Duration | {self.avg_duration_ms:.0f}ms |",
            "",
        ]

        if self.summary_by_category:
            lines.append("## By Category")
            lines.append("| Category | Cases | Passed | Pass Rate | Avg Score |")
            lines.append("|----------|-------|--------|-----------|-----------|")
            for cat, info in sorted(self.summary_by_category.items()):
                lines.append(
                    f"| {cat} | {info['total']} | {info['passed']} | "
                    f"{info['pass_rate']:.0%} | {info['avg_score']:.1f} |"
                )
            lines.append("")

        if self.summary_by_difficulty:
            lines.append("## By Difficulty")
            lines.append("| Difficulty | Cases | Passed | Pass Rate | Avg Score |")
            lines.append("|------------|-------|--------|-----------|-----------|")
            for diff in ["easy", "medium", "hard"]:
                if diff in self.summary_by_difficulty:
                    info = self.summary_by_difficulty[diff]
                    lines.append(
                        f"| {diff} | {info['total']} | {info['passed']} | "
                        f"{info['pass_rate']:.0%} | {info['avg_score']:.1f} |"
                    )
            lines.append("")

        if self.results:
            lines.append("## Detailed Results")
            lines.append("| Case ID | Passed | Score | Duration | Details |")
            lines.append("|---------|--------|-------|----------|---------|")
            for r in self.results:
                status = "PASS" if r.passed else "FAIL"
                lines.append(
                    f"| {r.case_id} | {status} | {r.total_score:.0f} | "
                    f"{r.duration_ms:.0f}ms | {r.details[:80]} |"
                )

        return "\n".join(lines)


# --- Scoring Functions ---


class Scorer:
    """Collection of scoring functions for evaluation metrics."""

    @staticmethod
    def exact_match(expected: str, actual: str) -> float:
        """Strict exact match scoring."""
        return 100.0 if expected.strip() == actual.strip() else 0.0

    @staticmethod
    def contains_match(expected: str, actual: str) -> float:
        """Check if actual contains expected substring."""
        if not expected:
            return 100.0
        return 100.0 if expected.strip().lower() in actual.strip().lower() else 0.0

    @staticmethod
    def fuzzy_match(expected: str, actual: str, threshold: float = 0.8) -> float:
        """Fuzzy ratio-based matching using SequenceMatcher."""
        from difflib import SequenceMatcher
        if not expected and not actual:
            return 100.0
        if not expected or not actual:
            return 0.0
        ratio = SequenceMatcher(None, expected.lower(), actual.lower()).ratio()
        return 100.0 if ratio >= threshold else ratio * 100.0

    @staticmethod
    def semantic_match(expected: str, actual: str) -> float:
        """Semantic similarity using token overlap (no embedding required)."""
        if not expected and not actual:
            return 100.0
        import re

        expected_tokens = set(re.findall(r'\w+', expected.lower()))
        actual_tokens = set(re.findall(r'\w+', actual.lower()))

        if not expected_tokens:
            return 100.0

        overlap = len(expected_tokens & actual_tokens)
        return (overlap / len(expected_tokens)) * 100.0

    @staticmethod
    def keyword_match(expected_keywords: List[str], actual: str) -> float:
        """Check how many expected keywords appear in actual text."""
        if not expected_keywords:
            return 100.0
        actual_lower = actual.lower()
        hits = sum(1 for kw in expected_keywords if kw.lower() in actual_lower)
        return (hits / len(expected_keywords)) * 100.0

    @staticmethod
    def tool_usage_match(expected_tools: List[str], actual_tools: List[str]) -> float:
        """Match expected tool usage."""
        if not expected_tools:
            return 100.0
        actual_set = set(actual_tools)
        hits = sum(1 for t in expected_tools if t in actual_set)
        return (hits / len(expected_tools)) * 100.0


# --- Runner ---


@dataclass
class EvalConfig:
    """Configuration for evaluation runs."""
    parallel: bool = False
    max_parallel: int = 4
    timeout_per_case: float = 60.0
    retry_failed: int = 0
    metrics: List[str] = field(default_factory=lambda: ["semantic", "keyword"])
    score_threshold: float = 60.0  # minimum score to pass


class Evaluator:
    """Run agent evaluation against golden datasets.

    Usage:
        evaluator = Evaluator(dataset, run_fn=my_agent_run)
        report = await evaluator.run()
    """

    def __init__(
        self,
        dataset: GoldenDataset,
        run_fn: Callable[[str], Any],
        config: Optional[EvalConfig] = None,
    ):
        self.dataset = dataset
        self.run_fn = run_fn
        self.config = config or EvalConfig()

    async def run(self) -> EvalReport:
        """Run all cases and produce an evaluation report."""
        results = []
        passed = 0

        for case in self.dataset.cases:
            result = await self._run_case(case)
            results.append(result)
            if result.passed:
                passed += 1

        total = len(results)
        avg_score = sum(r.total_score for r in results) / max(total, 1)
        avg_dur = sum(r.duration_ms for r in results) / max(total, 1)

        # Build summaries
        by_category = self._summarize_by(results, lambda r: self._find_case(r).category)
        by_difficulty = self._summarize_by(results, lambda r: self._find_case(r).difficulty)

        return EvalReport(
            dataset_name=self.dataset.name,
            dataset_version=self.dataset.version,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            total_cases=total,
            passed=passed,
            failed=total - passed,
            pass_rate=passed / max(total, 1),
            avg_score=round(avg_score, 1),
            avg_duration_ms=round(avg_dur, 1),
            results=results,
            summary_by_category=by_category,
            summary_by_difficulty=by_difficulty,
        )

    async def _run_case(self, case: GoldenCase) -> ScoreDetail:
        """Run a single golden case and score it."""
        result = ScoreDetail(case_id=case.id)
        result.errors = []

        t0 = time.perf_counter()

        try:
            actual = await self._run_with_timeout(case)
            result.actual_output = str(actual) if actual else ""
        except TimeoutError:
            result.errors.append("Timeout")
            result.total_score = 0.0
            result.duration_ms = self.config.timeout_per_case * 1000
            return result
        except Exception as e:
            result.errors.append(f"Error: {str(e)}")
            result.total_score = 0.0
            result.duration_ms = (time.perf_counter() - t0) * 1000
            return result

        result.duration_ms = (time.perf_counter() - t0) * 1000

        # Score across multiple metrics
        scores = {}
        for metric in self.config.metrics:
            score = self._score_metric(metric, case, result.actual_output)
            scores[metric] = score

        result.metrics = scores

        # Weighted average of metrics
        if scores:
            result.total_score = sum(scores.values()) / len(scores)
        else:
            result.total_score = 0.0

        result.passed = result.total_score >= self.config.score_threshold

        # Generate details
        detail_parts = []
        for m, s in scores.items():
            detail_parts.append(f"{m}={s:.0f}")
        result.details = ", ".join(detail_parts)

        return result

    async def _run_with_timeout(self, case: GoldenCase):
        """Run with timeout protection."""
        import asyncio

        prompt = case.prompt
        if case.context:
            prompt = f"{case.context.get('prefix', '')}{prompt}{case.context.get('suffix', '')}"

        return await asyncio.wait_for(
            asyncio.ensure_future(self._call_run_fn(prompt)),
            timeout=self.config.timeout_per_case,
        )

    async def _call_run_fn(self, prompt: str):
        """Call the run function - supports both sync and async."""
        import inspect
        result = self.run_fn(prompt)
        if inspect.iscoroutine(result) or inspect.isawaitable(result):
            return await result
        return result

    def _score_metric(self, metric: str, case: GoldenCase, actual: str) -> float:
        """Score a single metric."""
        if metric == "exact":
            return Scorer.exact_match(case.expected, actual)
        elif metric == "contains":
            return Scorer.contains_match(case.expected, actual)
        elif metric == "fuzzy":
            return Scorer.fuzzy_match(case.expected, actual)
        elif metric == "semantic":
            return Scorer.semantic_match(case.expected, actual)
        elif metric == "keyword":
            # keywords from expected (delimited by commas or semicolons)
            keywords = [k.strip() for k in case.expected.replace(";", ",").split(",") if k.strip()]
            return Scorer.keyword_match(keywords, actual)
        else:
            return 0.0

    def _find_case(self, result: ScoreDetail) -> GoldenCase:
        for c in self.dataset.cases:
            if c.id == result.case_id:
                return c
        return GoldenCase(id=result.case_id, prompt="")

    def _summarize_by(
        self,
        results: List[ScoreDetail],
        key_fn: Callable[[ScoreDetail], str],
    ) -> Dict[str, Dict[str, Any]]:
        """Summarize results by a grouping key."""
        groups: Dict[str, List[ScoreDetail]] = {}
        for r in results:
            k = key_fn(r)
            groups.setdefault(k, []).append(r)

        summary = {}
        for k, group in groups.items():
            total = len(group)
            passed = sum(1 for r in group if r.passed)
            avg = sum(r.total_score for r in group) / max(total, 1)
            summary[k] = {
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": passed / max(total, 1),
                "avg_score": round(avg, 1),
            }
        return summary


# --- Quick Helpers ---


def load_dataset(path: str) -> GoldenDataset:
    """Load a golden dataset from JSON."""
    return GoldenDataset.from_json(path)


def save_dataset(dataset: GoldenDataset, path: str):
    """Save a golden dataset to JSON."""
    dataset.to_json(path)


def quick_eval(
    dataset_path: str,
    run_fn: Callable[[str], Any],
    metrics: Optional[List[str]] = None,
) -> "EvalReport":
    """Quick synchronous evaluation (blocking wrapper)."""
    import asyncio

    dataset = GoldenDataset.from_json(dataset_path)
    evaluator = Evaluator(
        dataset,
        run_fn,
        config=EvalConfig(metrics=metrics or ["semantic", "keyword"]),
    )

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(evaluator.run())
    finally:
        loop.close()


# ── EvalSuite v2 imports ────────────────────────────────────────────

from agentos.evaluation.suite import (
    EvalSuiteRunner,
    SWEBenchEvaluator,
    HallucinationDetector,
    Leaderboard,
    MultiRoundEvaluator,
)

__all__ = [
    "GoldenCase", "GoldenDataset", "ScoreDetail", "EvalReport",
    "Scorer", "EvalConfig", "Evaluator",
    "load_dataset", "save_dataset", "quick_eval",
    # Suite v2
    "EvalSuiteRunner", "SWEBenchEvaluator", "HallucinationDetector",
    "Leaderboard", "MultiRoundEvaluator",
]
