"""
Prompt Optimizer — DSPy-inspired automatic prompt improvement via
iterative refinement, few-shot bootstrapping, and multi-strategy optimization.
"""

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional


class OptimizationStrategy(str, Enum):
    """Available optimization approaches."""

    BOOTSTRAP_FEWSHOT = "bootstrap_fewshot"
    MIPRO = "mipro"          # Multi-prompt instruction proposal
    GRADIENT_FREE = "gradient_free"
    ENSEMBLE = "ensemble"
    CHAIN_OF_THOUGHT = "chain_of_thought"


@dataclass
class OptimizerConfig:
    """Configuration for prompt optimization runs."""

    strategy: OptimizationStrategy = OptimizationStrategy.BOOTSTRAP_FEWSHOT
    max_iterations: int = 10
    candidates_per_iteration: int = 4
    eval_samples: int = 20
    target_metric: str = "accuracy"
    target_threshold: float = 0.90
    temperature_range: tuple[float, float] = (0.1, 0.9)
    keep_top_k: int = 3
    early_stop_patience: int = 3
    seed: int = 42


@dataclass
class PromptCandidate:
    """A single prompt variant under evaluation."""

    id: str
    text: str
    score: float = 0.0
    metrics: dict[str, float] = field(default_factory=dict)
    generation: int = 0
    parent_id: str = ""


@dataclass
class OptimizationResult:
    """Final result after optimization converges or exhausts budget."""

    best_prompt: str
    best_score: float
    iterations: int
    candidates_evaluated: int
    strategy: OptimizationStrategy
    history: list[PromptCandidate] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PromptOptimizer:
    """Iteratively refines prompts using a pluggable scoring function.

    Usage::

        def score(prompt: str) -> float:
            # run your LLM eval and return metric
            return measure(prompt)

        opt = PromptOptimizer(config)
        result = opt.optimize(base_prompt, score_fn=score)
        print(result.best_prompt)
    """

    SEED_TEMPLATES = {
        OptimizationStrategy.BOOTSTRAP_FEWSHOT: [
            "{base}\n\nHere are some examples:\n{examples}",
            "Task: {base}\n\nIllustrative examples:\n{examples}",
            "{base}\n\nDemonstrations:\n{examples}",
        ],
        OptimizationStrategy.CHAIN_OF_THOUGHT: [
            "{base}\n\nLet's think step by step.",
            "{base}\n\nBreak this down logically:",
            "Solve step-by-step:\n{base}",
        ],
        OptimizationStrategy.ENSEMBLE: [
            "Consider multiple perspectives:\n{base}",
            "Review from different angles:\n{base}",
            "Analyze comprehensively:\n{base}",
        ],
    }

    def __init__(self, config: Optional[OptimizerConfig] = None):
        self.config = config or OptimizerConfig()
        random.seed(self.config.seed)

    def optimize(
        self,
        base_prompt: str,
        score_fn: Callable[[str], float],
        few_shot_examples: list[str] | None = None,
    ) -> OptimizationResult:
        """Run optimization and return the best prompt found."""
        best = PromptCandidate(
            id="base",
            text=base_prompt,
            score=score_fn(base_prompt),
            generation=0,
        )
        history = [best]
        no_improve = 0

        for iteration in range(1, self.config.max_iterations + 1):
            candidates = self._generate_candidates(
                best.text, iteration, few_shot_examples
            )
            for c in candidates:
                c.score = score_fn(c.text)
                history.append(c)

            # Select best from this iteration
            iteration_best = max(candidates, key=lambda c: c.score)
            if iteration_best.score > best.score:
                best = iteration_best
                no_improve = 0
            else:
                no_improve += 1

            # Keep top-K across all generations
            history.sort(key=lambda c: c.score, reverse=True)
            history = history[:self.config.keep_top_k * 2]

            if best.score >= self.config.target_threshold:
                break
            if no_improve >= self.config.early_stop_patience:
                break

        return OptimizationResult(
            best_prompt=best.text,
            best_score=best.score,
            iterations=iteration,
            candidates_evaluated=len(history),
            strategy=self.config.strategy,
            history=history[:self.config.keep_top_k],
        )

    def _generate_candidates(
        self,
        base: str,
        generation: int,
        examples: list[str] | None,
    ) -> list[PromptCandidate]:
        templates = self.SEED_TEMPLATES.get(
            self.config.strategy,
            self.SEED_TEMPLATES[OptimizationStrategy.BOOTSTRAP_FEWSHOT],
        )
        candidates: list[PromptCandidate] = []

        for i in range(self.config.candidates_per_iteration):
            tmpl = random.choice(templates)
            text = tmpl.format(
                base=base,
                examples=self._format_examples(examples) if examples else "",
            )
            # Add small perturbations
            if random.random() < 0.3 and generation > 1:
                text = self._perturb(text)

            candidates.append(PromptCandidate(
                id=f"gen{generation}_{i}",
                text=text,
                generation=generation,
                parent_id="base" if generation == 1 else f"gen{generation-1}_0",
            ))

        return candidates

    def _format_examples(self, examples: list[str]) -> str:
        return "\n".join(f"- {e}" for e in examples[:5])

    def _perturb(self, text: str) -> str:
        """Apply minor random perturbations."""
        perturbations = [
            lambda t: t.replace(".", ". Please be thorough."),
            lambda t: "Carefully: " + t,
            lambda t: t + "\nBe precise and concise.",
            lambda t: t.replace(":", ":\n"),
            lambda t: t.replace("the ", "the relevant "),
        ]
        return random.choice(perturbations)(text)
