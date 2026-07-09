"""
AgentOS Task Router — Intelligent Multi-Model Task Routing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Production-grade task routing engine that decides which language model
to use per-request based on:
  - Task complexity classification (simple/medium/complex)
  - Latency budget constraints
  - Cost optimization (cheapest model that meets quality bar)
  - Fallback chains (primary → fallback → degraded)
  - Model capability registry (tool-calling, vision, reasoning, etc.)

Architecture:
  TaskClassifier    → classify task complexity from prompt analysis
  ModelRegistry     → register model capabilities and routing weights
  RouteDecision     → immutable routing decision with reasoning
  TaskRouter        → orchestrates classification + model selection
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agentos.core.cost_tracker import CostTracker

# ---------------------------------------------------------------------------
# Task Complexity
# ---------------------------------------------------------------------------


class TaskComplexity(StrEnum):
    """Estimated complexity of a user task."""

    SIMPLE = "simple"  # Single-step, well-defined (translate, summarize)
    MEDIUM = "medium"  # Multi-step reasoning (analysis, code review)
    COMPLEX = "complex"  # Multi-agent orchestration, long-form generation


class TaskCategory(StrEnum):
    """Semantic category of the task."""

    CHAT = "chat"
    CODE = "code"
    REASONING = "reasoning"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    TOOL_USE = "tool_use"
    VISION = "vision"
    TRANSLATION = "translation"


# ---------------------------------------------------------------------------
# Model Capability
# ---------------------------------------------------------------------------


@dataclass
class ModelSpec:
    """Specification of a model's capabilities and routing profile."""

    model_id: str
    provider: str
    tier: str  # "premium" / "standard" / "budget" / "fallback"
    max_tokens: int = 128000
    latency_category: str = "medium"  # "fast" / "medium" / "slow"

    # Capability flags
    supports_tool_calling: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    supports_code: bool = False
    supports_function_calling: bool = False

    # Routing weights (higher = more likely to be selected for that category)
    category_weights: dict[TaskCategory, float] = field(default_factory=dict)

    # Quality bar: tasks of this complexity must use this model or better
    min_complexity: TaskComplexity = TaskComplexity.SIMPLE

    # Cost consideration (relative cost multiplier, GPT-4o-mini = 1.0 baseline)
    cost_multiplier: float = 1.0

    # Excluded task categories
    excluded_categories: set[TaskCategory] = field(default_factory=set)


# Default model registry
DEFAULT_MODEL_SPECS: list[ModelSpec] = [
    ModelSpec(
        model_id="gpt-4o",
        provider="openai",
        tier="premium",
        supports_tool_calling=True,
        supports_vision=True,
        supports_function_calling=True,
        min_complexity=TaskComplexity.COMPLEX,
        cost_multiplier=4.5,
        latency_category="medium",
        category_weights={
            TaskCategory.REASONING: 0.9,
            TaskCategory.ANALYSIS: 0.85,
            TaskCategory.CODE: 0.8,
            TaskCategory.TOOL_USE: 0.95,
        },
    ),
    ModelSpec(
        model_id="gpt-4o-mini",
        provider="openai",
        tier="standard",
        supports_tool_calling=True,
        supports_function_calling=True,
        min_complexity=TaskComplexity.MEDIUM,
        cost_multiplier=1.0,
        latency_category="fast",
        category_weights={
            TaskCategory.CHAT: 1.0,
            TaskCategory.TRANSLATION: 0.9,
            TaskCategory.CODE: 0.7,
        },
    ),
    ModelSpec(
        model_id="claude-sonnet-4-20250514",
        provider="anthropic",
        tier="premium",
        max_tokens=200000,
        supports_tool_calling=True,
        supports_reasoning=True,
        supports_code=True,
        min_complexity=TaskComplexity.COMPLEX,
        cost_multiplier=3.0,
        latency_category="medium",
        category_weights={
            TaskCategory.CODE: 1.0,
            TaskCategory.REASONING: 0.95,
            TaskCategory.ANALYSIS: 0.9,
            TaskCategory.CREATIVE: 0.85,
        },
    ),
    ModelSpec(
        model_id="claude-haiku-3-5-sonnet-20241022",
        provider="anthropic",
        tier="standard",
        supports_tool_calling=True,
        latency_category="fast",
        min_complexity=TaskComplexity.MEDIUM,
        cost_multiplier=0.8,
        category_weights={
            TaskCategory.CHAT: 0.9,
            TaskCategory.TRANSLATION: 0.8,
        },
    ),
    ModelSpec(
        model_id="deepseek-v3",
        provider="deepseek",
        tier="standard",
        supports_tool_calling=False,
        min_complexity=TaskComplexity.COMPLEX,
        cost_multiplier=0.25,
        latency_category="fast",
        category_weights={
            TaskCategory.CODE: 0.85,
            TaskCategory.REASONING: 0.8,
            TaskCategory.CHAT: 0.7,
        },
    ),
    ModelSpec(
        model_id="gemini-2.5-flash",
        provider="google",
        tier="standard",
        supports_tool_calling=True,
        supports_vision=True,
        min_complexity=TaskComplexity.MEDIUM,
        cost_multiplier=0.15,
        latency_category="fast",
        category_weights={
            TaskCategory.CHAT: 0.85,
            TaskCategory.VISION: 0.95,
            TaskCategory.TRANSLATION: 0.7,
        },
    ),
    ModelSpec(
        model_id="llama-4-maverick",
        provider="meta",
        tier="budget",
        min_complexity=TaskComplexity.SIMPLE,
        cost_multiplier=0.1,
        latency_category="fast",
        category_weights={
            TaskCategory.CHAT: 0.6,
        },
    ),
]


# ---------------------------------------------------------------------------
# Task Classifier
# ---------------------------------------------------------------------------


class TaskClassifier:
    """
    Classify task complexity based on prompt heuristics.

    Heuristics (no LLM call needed):
      - Length: > 500 tokens → MEDIUM+; > 2000 tokens → COMPLEX
      - Multi-step indicators: "first"/"then"/"next"/"finally" → MEDIUM+
      - Agent keywords: "plan"/"orchestrate"/"coordinate"/"multi-agent" → COMPLEX
      - Code: code blocks, "function"/"class"/"import" → MEDIUM+
      - Reasoning: "why"/"explain"/"analyze"/"compare" → MEDIUM+
      - Tool use: "search"/"fetch"/"call"/"run"/"execute" → MEDIUM+
    """

    # Token estimate: ~1.3 tokens per word (rough heuristic)
    TOKENS_PER_WORD = 1.3

    SIMPLE_THRESHOLD_TOKENS = 500
    COMPLEX_THRESHOLD_TOKENS = 2000

    MULTI_STEP_PATTERNS = [
        re.compile(r"\b(first|then|next|finally|after that|step \d)\b", re.IGNORECASE),
        re.compile(r"\d+\.\s+\w+"),  # Numbered list
    ]

    AGENT_PATTERNS = [
        re.compile(
            r"\b(plan|orchestrate|coordinate|multi.agent|dispatch|delegate)\b", re.IGNORECASE
        ),
    ]

    CODE_PATTERNS = [
        re.compile(r"```"),
        re.compile(r"\b(def |class |import |function |const |let |var )", re.IGNORECASE),
    ]

    REASONING_PATTERNS = [
        re.compile(r"\b(analy[sz]e|explain|compare|contrast|evaluate|assess|why)\b", re.IGNORECASE),
    ]

    TOOL_PATTERNS = [
        re.compile(r"\b(search|fetch|call|run|execute|invoke|download|upload)\b", re.IGNORECASE),
    ]

    def classify(
        self,
        prompt: str,
        available_tools: list[str] | None = None,
    ) -> tuple[TaskComplexity, list[TaskCategory]]:
        """
        Classify a task from its prompt.

        Returns (complexity, categories).
        """
        words = prompt.split()
        estimated_tokens = max(1, int(len(words) * self.TOKENS_PER_WORD))

        # Determine categories
        categories: set[TaskCategory] = set()
        categories.add(TaskCategory.CHAT)  # Default

        if self._match_any(self.CODE_PATTERNS, prompt):
            categories.add(TaskCategory.CODE)

        if self._match_any(self.REASONING_PATTERNS, prompt):
            categories.add(TaskCategory.REASONING)
            categories.add(TaskCategory.ANALYSIS)

        if self._match_any(self.TOOL_PATTERNS, prompt) or available_tools:
            categories.add(TaskCategory.TOOL_USE)

        # Determine complexity
        is_multi_step = self._match_any(self.MULTI_STEP_PATTERNS, prompt)
        is_agent = self._match_any(self.AGENT_PATTERNS, prompt)

        if estimated_tokens > self.COMPLEX_THRESHOLD_TOKENS or is_agent:
            complexity = TaskComplexity.COMPLEX
        elif (
            estimated_tokens > self.SIMPLE_THRESHOLD_TOKENS or is_multi_step or len(categories) > 2
        ):
            complexity = TaskComplexity.MEDIUM
        else:
            complexity = TaskComplexity.SIMPLE

        return complexity, list(categories)

    @staticmethod
    def _match_any(patterns: list[re.Pattern], text: str) -> bool:
        """Check if any pattern matches the text."""
        return any(p.search(text) for p in patterns)


# ---------------------------------------------------------------------------
# Route Decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouteDecision:
    """Immutable routing decision."""

    selected_model: str
    provider: str
    complexity: TaskComplexity
    categories: list[TaskCategory]
    fallback_models: list[str]
    reasoning: str
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_model": self.selected_model,
            "provider": self.provider,
            "complexity": self.complexity.value,
            "categories": [c.value for c in self.categories],
            "fallback_models": self.fallback_models,
            "reasoning": self.reasoning,
            "latency_ms": round(self.latency_ms * 1000, 2),
        }


# ---------------------------------------------------------------------------
# Task Router
# ---------------------------------------------------------------------------


class TaskRouter:
    """
    Routes tasks to the optimal model based on task analysis.

    Strategy (in order):
      1. Classify task complexity and categories
      2. Filter models by capability requirements (tool-calling, vision, etc.)
      3. Filter by min_complexity (only use models that meet quality bar)
      4. Score remaining models by category weight × (1 / cost_multiplier)
      5. Select top model + 2 fallbacks
    """

    def __init__(
        self,
        model_specs: list[ModelSpec] | None = None,
        cost_tracker: CostTracker | None = None,
    ):
        self._models = model_specs or DEFAULT_MODEL_SPECS
        self._classifier = TaskClassifier()
        self._cost_tracker = cost_tracker
        self._decision_log: list[RouteDecision] = []

    @property
    def models(self) -> list[ModelSpec]:
        return list(self._models)

    def register_model(self, spec: ModelSpec) -> None:
        """Register a new model for routing."""
        self._models.append(spec)

    def route(
        self,
        prompt: str,
        *,
        required_capabilities: set[str] | None = None,
        latency_budget_ms: int | None = None,
        available_tools: list[str] | None = None,
    ) -> RouteDecision:
        """
        Route a task to the best model.

        Args:
            prompt: The user's task prompt
            required_capabilities: Set of required capabilities (e.g., {"tool_calling", "vision"})
            latency_budget_ms: Maximum acceptable latency in ms
            available_tools: Tools available for this task

        Returns:
            RouteDecision with selected model and fallbacks
        """
        start = time.time()

        complexity, categories = self._classifier.classify(prompt, available_tools)

        # Filter candidates
        candidates = self._filter_candidates(complexity, categories, required_capabilities)

        if not candidates:
            # Fallback: drop min_complexity constraint
            candidates = self._filter_candidates(
                complexity, categories, required_capabilities, relax_complexity=True
            )

        if not candidates:
            # Ultimate fallback: cheapest model
            cheapest = min(self._models, key=lambda m: m.cost_multiplier)
            candidates = [cheapest]

        # Score and rank
        ranked = self._rank_candidates(candidates, categories, latency_budget_ms)
        selected = ranked[0]
        fallbacks = [r.model_id for r in ranked[1:3]] if len(ranked) > 1 else []

        decision = RouteDecision(
            selected_model=selected.model_id,
            provider=selected.provider,
            complexity=complexity,
            categories=categories,
            fallback_models=fallbacks,
            reasoning=self._build_reasoning(selected, complexity, categories),
            latency_ms=time.time() - start,
        )
        self._decision_log.append(decision)
        return decision

    def _filter_candidates(
        self,
        complexity: TaskComplexity,
        categories: list[TaskCategory],
        required_capabilities: set[str] | None = None,
        relax_complexity: bool = False,
    ) -> list[ModelSpec]:
        """Filter models by complexity bar, category exclusion, and capabilities."""
        caps = required_capabilities or set()
        candidates: list[ModelSpec] = []

        for model in self._models:
            # Complexity bar (can relax if no candidates)
            if not relax_complexity:
                complexity_levels = {
                    TaskComplexity.SIMPLE: 0,
                    TaskComplexity.MEDIUM: 1,
                    TaskComplexity.COMPLEX: 2,
                }
                model_level = complexity_levels[model.min_complexity]
                task_level = complexity_levels[complexity]
                if model_level < task_level:
                    continue

            # Category exclusion
            if any(cat in model.excluded_categories for cat in categories):
                continue

            # Capability requirements
            if "tool_calling" in caps and not model.supports_tool_calling:
                continue
            if "vision" in caps and not model.supports_vision:
                continue
            if "reasoning" in caps and not model.supports_reasoning:
                continue

            candidates.append(model)

        return candidates

    def _rank_candidates(
        self,
        candidates: list[ModelSpec],
        categories: list[TaskCategory],
        latency_budget_ms: int | None = None,
    ) -> list[ModelSpec]:
        """Score and rank candidates by category weight / cost."""
        LATENCY_SCORES = {"fast": 1.2, "medium": 1.0, "slow": 0.7}  # noqa: N806

        def score(model: ModelSpec) -> float:
            # Category affinity
            cat_score = sum(model.category_weights.get(cat, 0.0) for cat in categories) / max(
                1, len(categories)
            )

            # Cost efficiency (inverse)
            cost_score = 1.0 / max(0.01, model.cost_multiplier)

            # Latency bonus
            latency_score = LATENCY_SCORES.get(model.latency_category, 1.0)

            # Final: weighted sum
            return cat_score * 0.5 + cost_score * 0.3 + latency_score * 0.2

        ranked = sorted(candidates, key=score, reverse=True)

        # Filter by latency budget if specified
        if latency_budget_ms is not None:
            SLOW_THRESHOLD_MS = 2000  # noqa: N806
            if latency_budget_ms < SLOW_THRESHOLD_MS:
                ranked = [m for m in ranked if m.latency_category != "slow"]

        return ranked

    def _build_reasoning(
        self,
        selected: ModelSpec,
        complexity: TaskComplexity,
        categories: list[TaskCategory],
    ) -> str:
        """Build human-readable reasoning for the routing decision."""
        cat_names = ", ".join(c.value for c in categories)
        return (
            f"Task complexity: {complexity.value}. Categories: {cat_names}. "
            f"Selected {selected.model_id} ({selected.provider}, {selected.tier} tier) "
            f"for optimal quality/cost balance."
        )

    def get_decision_log(self) -> list[RouteDecision]:
        return list(self._decision_log)

    def clear_log(self) -> None:
        self._decision_log.clear()

    def get_statistics(self) -> dict[str, Any]:
        """Return routing statistics."""
        if not self._decision_log:
            return {}

        model_counts: dict[str, int] = {}
        complexity_counts: dict[str, int] = {}
        total_latency = 0.0

        for d in self._decision_log:
            model_counts[d.selected_model] = model_counts.get(d.selected_model, 0) + 1
            complexity_counts[d.complexity.value] = complexity_counts.get(d.complexity.value, 0) + 1
            total_latency += d.latency_ms

        return {
            "total_requests": len(self._decision_log),
            "model_distribution": model_counts,
            "complexity_distribution": complexity_counts,
            "avg_latency_ms": round(total_latency * 1000 / len(self._decision_log), 2),
        }
