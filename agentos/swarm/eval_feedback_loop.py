"""
v1.9.4: Eval-Feedback Loop — closes the gap between CompositeScorer and AutoPilot.

Wires evaluation scores back into the execution layer, creating a true
execute → evaluate → feedback → retry 闭环 (closed loop).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FeedbackSignal:
    """A signal derived from evaluation that triggers self-healing."""

    source: str  # Which scorer produced this
    metric: str  # metric name (e.g. "rouge_l", "bleu", "judge")
    score: float  # raw score
    threshold: float  # expected threshold
    passed: bool  # did it meet threshold?
    detail: str = ""  # human-readable detail
    suggestion: str = ""  # what to improve


@dataclass
class RetryConfig:
    """Configuration for the retry loop."""

    max_retries: int = 3
    backoff_base: float = 1.0  # seconds
    backoff_multiplier: float = 2.0
    score_improvement_min: float = 0.05  # min score gain to consider improvement
    timeout: float = 60.0  # total loop timeout (seconds)


@dataclass
class LoopResult:
    """Result of a feedback loop execution."""

    task: str
    final_output: Any = None
    scores: dict[str, float] = field(default_factory=dict)
    attempts: int = 0
    best_score: float = 0.0
    converged: bool = False
    duration: float = 0.0
    history: list[dict] = field(default_factory=list)  # each attempt trace


class EvalFeedbackLoop:
    """Connects evaluation scores to AutoPilot-style retry with incremental
    prompt refinement.

    Usage:
        loop = EvalFeedbackLoop(scorer, RetryConfig(max_retries=3))
        result = await loop.run(task, executor_fn, expected_output)
    """

    def __init__(
        self,
        scorer: Any = None,  # CompositeScorer / CompositeScorerV2
        config: RetryConfig | None = None,
        reflection_prompt: str | None = None,
    ):
        self._scorer = scorer
        self._config = config or RetryConfig()
        self._reflection_prompt = reflection_prompt or (
            "The previous attempt scored {score:.3f} (threshold: {threshold:.3f}). "
            "Weak metrics: {weak_metrics}. "
            "Please improve the output focusing on these weaknesses."
        )

    async def run(
        self,
        task: str,
        executor: Callable[[str], Any],
        expected: str = "",
        strategy: str = "general",
    ) -> LoopResult:
        """Execute task with evaluation-driven retry loop.

        Args:
            task: original task description
            executor: async/sync callable (task_str) → output
            expected: expected/reference output for scoring
            strategy: scoring strategy (qa/code/summary/translation)

        Returns:
            LoopResult with final output and convergence info
        """
        start = time.time()
        result = LoopResult(task=task)
        previous_score = 0.0

        for attempt in range(1, self._config.max_retries + 1):
            # Execute
            output = executor(task)
            if asyncio.iscoroutine(output):
                output = await output

            attempt_trace = {"attempt": attempt, "output": str(output)[:500]}

            # Score
            scores = self._score(output, expected, strategy)
            attempt_trace["scores"] = scores
            score = scores.get("weighted", 0.0)
            passed = scores.get("passed", False)
            attempt_trace["passed"] = passed

            result.history.append(attempt_trace)

            # Track best
            if score > result.best_score:
                result.best_score = score
                result.final_output = output

            # Emit feedback signal
            signals = self._signals_from_scores(scores, strategy)
            attempt_trace["signals"] = [
                {"metric": s.metric, "score": s.score, "passed": s.passed} for s in signals
            ]

            # Check convergence
            if passed:
                result.converged = True
                result.attempts = attempt
                result.scores = scores
                result.duration = time.time() - start
                return result

            # Improvement check
            if attempt > 1 and (score - previous_score) < self._config.score_improvement_min:
                result.converged = False
                result.attempts = attempt
                result.scores = scores
                result.final_output = output
                result.duration = time.time() - start
                return result

            previous_score = score

            # Refine task prompt for next attempt
            task = self._refine_task(task, signals, score, attempt)
            attempt_trace["refined_task"] = task

            # Backoff
            wait = self._config.backoff_base * (self._config.backoff_multiplier ** (attempt - 1))
            if (time.time() - start + wait) > self._config.timeout:
                break
            await asyncio.sleep(wait)

        result.attempts = self._config.max_retries
        result.scores = scores
        result.duration = time.time() - start
        return result

    def _score(self, output: str, expected: str, strategy: str) -> dict[str, Any]:
        """Score output against expected using CompositeScorer."""
        if not self._scorer or not expected:
            # Heuristic scoring when no scorer/reference available
            return self._heuristic_score(output, expected)

        try:
            result = self._scorer.score(
                reference=expected,
                candidate=str(output),
                task=strategy,
            )
            return {
                "weighted": result.weighted_score,
                "passed": result.passed,
                "details": result.details,
                "raw_scores": result.scores,
            }
        except Exception:
            return self._heuristic_score(output, expected)

    def _heuristic_score(self, output: str, expected: str) -> dict:
        """Fallback scoring when no scorer is available."""
        if not expected:
            # No reference — score based on output quality heuristics
            text = str(output) if output else ""
            quality = 0.5
            if len(text) > 50:
                quality += 0.1
            if len(text) > 200:
                quality += 0.1
            if any(kw in text.lower() for kw in ("conclusion", "result", "answer")):
                quality += 0.1
            return {"weighted": min(quality, 1.0), "passed": quality >= 0.5, "details": "heuristic"}

        # Check contains match
        contains = 1.0 if expected.lower() in str(output).lower() else 0.0
        return {"weighted": contains * 0.5, "passed": contains > 0, "details": "contains_heuristic"}

    def _signals_from_scores(self, scores: dict, strategy: str) -> list[FeedbackSignal]:
        """Convert score dict to FeedbackSignal list."""
        raw = scores.get("raw_scores", {})
        thresholds = {
            "qa": {"rouge_l": 0.3, "contains": 0.5, "judge": 0.55},
            "code": {"rouge_l": 0.1, "exact": 0.3, "contains": 0.5, "judge": 0.55},
            "summary": {"rouge_l": 0.5, "semantic": 0.4, "judge": 0.55},
            "translation": {"bleu": 0.3, "rouge_l": 0.3, "judge": 0.55},
        }
        strat_thresholds = thresholds.get(strategy, {"rouge_l": 0.3, "contains": 0.5})

        signals = []
        for metric, score in raw.items():
            threshold = strat_thresholds.get(metric, 0.5)
            passed = score >= threshold
            detail = f"{metric}={score:.3f} vs {threshold:.3f}"
            suggestion = ""
            if not passed:
                suggestion = self._suggestion_for_metric(metric, score, threshold)
            signals.append(
                FeedbackSignal(
                    source=strategy,
                    metric=metric,
                    score=score,
                    threshold=threshold,
                    passed=passed,
                    detail=detail,
                    suggestion=suggestion,
                )
            )
        return signals

    def _suggestion_for_metric(self, metric: str, score: float, threshold: float) -> str:
        """Generate improvement suggestion based on weak metric."""
        gap = threshold - score
        suggestions = {
            "rouge_l": "Make output more comprehensive; include key phrases from expected answer.",
            "bleu": "Improve translation accuracy; check terminology and phrasing.",
            "exact": "Output format doesn't match expected; check structure and delimiters.",
            "contains": f"Missing key concepts; include: (gap: {gap:.2f})",
            "semantic": "Semantic meaning differs; rephrase to be closer to expected intent.",
            "judge": "Output quality below LLM-judge threshold; improve clarity and completeness.",
        }
        return suggestions.get(metric, f"Improve {metric} by at least {gap:.2f}")

    def _refine_task(
        self,
        task: str,
        signals: list[FeedbackSignal],
        current_score: float,
        attempt: int,
    ) -> str:
        """Enrich task prompt with feedback for next attempt."""
        weak = [s for s in signals if not s.passed]
        if not weak:
            return task

        weak_metrics = ", ".join(f"{s.metric}({s.score:.2f} < {s.threshold:.2f})" for s in weak)
        suggestions = "; ".join(s.suggestion for s in weak)

        reflection = (
            f"[Retry #{attempt} feedback — score {current_score:.3f}] "
            f"Weak: {weak_metrics}. {suggestions}"
        )

        # Append reflection to task
        if "---" in task:
            base, _ = task.split("---", 1)
            return f"{base.strip()}\n---\n{reflection}"
        return f"{task}\n---\n{reflection}"
