"""
v1.9.4: LLM-as-Judge Result Fusion engine.

Aggregates multiple agent outputs with weighted fusion,
confidence scoring, and LLM-as-Judge quality arbitration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import json as _json
import math


_JUDGE_PROMPT = """You are an expert quality judge. Given a task and multiple candidate results,
select the best result or synthesize a combined result.

Task: {task}

Candidates:
{candidates}

Instructions:
1. Evaluate each candidate for correctness, completeness, and clarity
2. If one candidate is clearly best, output: {{"action": "select", "best_index": N, "reason": "..."}}
3. If candidates complement each other, output: {{"action": "merge", "merged": "...", "reason": "..."}}
4. If all candidates are poor, output: {{"action": "reject", "reason": "..."}}

Output ONLY the JSON object, no other text.
JSON:"""


@dataclass
class FusedResult:
    """Result of fusion operation."""

    merged: Any = None
    best_index: int = -1
    confidence: float = 0.0
    action: str = "none"  # select | merge | reject
    reason: str = ""
    individual_scores: dict[str, float] = field(default_factory=dict)
    all_outputs: dict[str, Any] = field(default_factory=dict)


class ResultFusion:
    """LLM-as-Judge result aggregation engine.

    Combines outputs from multiple agents with:
    - Weighted-vote aggregation
    - LLM-as-Judge for quality arbitration
    - Confidence scoring
    """

    def __init__(
        self,
        strategy: str = "auto",
        llm_model: str = "gpt-4o-mini",
    ):
        self._strategy = strategy
        self._llm_model = llm_model

    def fuse(
        self,
        task: str,
        outputs: dict[str, Any],
        weights: dict[str, float] | None = None,
    ) -> FusedResult:
        """Fuse multiple agent outputs into a single result.

        Args:
            task: Original task description
            outputs: Dict of agent_name -> agent_output
            weights: Optional dict of agent_name -> weight (default: equal)

        Returns:
            FusedResult with merged output and confidence
        """
        if not outputs:
            result = FusedResult(action="reject", reason="No outputs to fuse")
            result.individual_scores = {}
            result.all_outputs = {}
            return result

        if len(outputs) == 1:
            name, value = next(iter(outputs.items()))
            result = FusedResult(
                merged=value,
                best_index=0,
                confidence=0.7,
                action="select",
                reason="Single output",
                individual_scores={name: 0.7},
                all_outputs=outputs,
            )
            return result

        weights = weights or {k: 1.0 for k in outputs}

        # Step 1: Compute individual scores
        scores = self._compute_scores(outputs, weights)

        # Step 2: Try LLM judge for arbitration
        llm_result = self._llm_judge(task, outputs)
        if llm_result:
            return llm_result

        # Step 3: Fallback — weighted aggregation
        return self._weighted_aggregate(outputs, scores)

    def _compute_scores(
        self,
        outputs: dict[str, Any],
        weights: dict[str, float],
    ) -> dict[str, float]:
        """Score each output for quality heuristics."""
        scores: dict[str, float] = {}
        for name, output in outputs.items():
            base = float(weights.get(name, 1.0))
            quality = self._quality_heuristic(output)
            scores[name] = round(base * quality, 3)
        return scores

    def _quality_heuristic(self, output: Any) -> float:
        """Heuristic quality score based on output characteristics."""
        score = 0.5  # baseline

        text = str(output) if output is not None else ""

        if not text:
            return 0.1

        # Length heuristic: too short is suspicious, reasonable length is good
        length = len(text)
        if 100 < length < 2000:
            score += 0.15
        elif 50 <= length <= 100:
            score += 0.05
        elif length > 5000:
            score += 0.05

        # Error patterns
        error_keywords = ["error", "exception", "traceback", "failed", "错误", "失败"]
        for kw in error_keywords:
            if kw in text:
                score -= 0.15
                break

        # Structure bonus
        if any(marker in text for marker in ("```", "##", "# ", "**", "<table")):
            score += 0.1

        # Confidence keywords
        confidence_keywords = ["recommend", "建议", "recommendation", "conclusion"]
        for kw in confidence_keywords:
            if kw in text:
                score += 0.05

        return max(0.0, min(1.0, score))

    def _llm_judge(
        self, task: str, outputs: dict[str, Any]
    ) -> FusedResult | None:
        """Use LLM to judge and fuse results. Returns None on failure."""
        try:
            import os
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return None

            candidates_str = "\n".join(
                f"[{i}] {name}: {str(output)[:300]}"
                for i, (name, output) in enumerate(outputs.items())
            )

            prompt = _JUDGE_PROMPT.format(
                task=task,
                candidates=candidates_str,
            )

            import requests
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": self._llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 500,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                return None

            text = resp.json()["choices"][0]["message"]["content"]

            start = text.find("{")
            end = text.rfind("}") + 1
            if start == -1 or end == 0:
                return None

            data = _json.loads(text[start:end])
            action = data.get("action", "reject")

            agent_names = list(outputs.keys())

            result = FusedResult()
            result.action = action
            result.reason = data.get("reason", "")
            result.all_outputs = {
                k: str(v)[:200] for k, v in outputs.items()
            }
            result.individual_scores = {
                k: 0.5 for k in outputs
            }

            if action == "select":
                idx = int(data.get("best_index", 0))
                idx = max(0, min(idx, len(agent_names) - 1))
                result.best_index = idx
                result.merged = outputs[agent_names[idx]]
                result.confidence = 0.8
            elif action == "merge":
                result.merged = data.get("merged", "")
                result.confidence = 0.75
                result.best_index = -1
            else:  # reject
                result.merged = None
                result.confidence = 0.0

            return result
        except Exception:
            return None

    def _weighted_aggregate(
        self,
        outputs: dict[str, Any],
        scores: dict[str, float],
    ) -> FusedResult:
        """Weighted vote aggregation fallback."""
        max_score = max(scores.values()) if scores else 0.0
        if max_score == 0:
            return FusedResult(action="reject", reason="All outputs scored zero")

        # Find best candidate
        best_name = max(scores, key=scores.get)  # type: ignore[arg-type]

        # Normalize scores to confidence
        total = sum(scores.values())
        confidence = max_score / total if total > 0 else 0.3

        # Check for consensus: if all string outputs are similar, merge them
        all_str = [str(v) for v in outputs.values()]
        consensus = self._check_consensus(all_str)

        if consensus:
            return FusedResult(
                merged=outputs[best_name],
                best_index=list(outputs.keys()).index(best_name),
                confidence=confidence,
                action="select",
                reason="Consensus among outputs",
                individual_scores=scores,
                all_outputs={k: str(v)[:200] for k, v in outputs.items()},
            )

        return FusedResult(
            merged=outputs[best_name],
            best_index=list(outputs.keys()).index(best_name),
            confidence=confidence,
            action="select",
            reason="Weighted voting (no consensus)",
            individual_scores=scores,
            all_outputs={k: str(v)[:200] for k, v in outputs.items()},
        )

    def _check_consensus(self, outputs: list[str]) -> bool:
        """Check if string outputs are similar enough for consensus."""
        if len(outputs) < 2:
            return True

        # Simple overlap ratio
        words = [set(o.lower().split()) for o in outputs]
        if any(len(w) == 0 for w in words):
            return False

        overlaps = []
        for i, wi in enumerate(words):
            for j, wj in enumerate(words):
                if i >= j:
                    continue
                if len(wi | wj) == 0:
                    overlaps.append(0.0)
                else:
                    overlaps.append(len(wi & wj) / len(wi | wj))

        if not overlaps:
            return False

        avg_overlap = sum(overlaps) / len(overlaps)
        return avg_overlap > 0.4
