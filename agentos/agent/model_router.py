"""Model Router — intelligent model selection based on task complexity and budget.

Automatically selects the best LLM model for each task based on:
  - Task complexity (TRIVIAL → EXPERT)
  - Priority (LOW → CRITICAL)
  - Daily budget constraints
  - Model cost/performance tiers
  - Fallback chains when budget is tight
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "TaskComplexity",
    "TaskPriority",
    "ModelSpec",
    "RequestSpec",
    "RouteResult",
    "ModelRouter",
]


# ── Enums ──────────────────────────────────────────────────────────


class TaskComplexity(Enum):
    TRIVIAL = 0  # weather, time, simple calc
    SIMPLE = 1  # basic Q&A, short translation
    MODERATE = 2  # typical assistant tasks
    COMPLEX = 3  # code review, analysis, research
    EXPERT = 4  # deep research, architecture design


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


# ── Dataclasses ────────────────────────────────────────────────────


@dataclass
class ModelSpec:
    name: str
    provider: str
    cost_per_1k_input: float  # USD per 1k input tokens
    cost_per_1k_output: float  # USD per 1k output tokens
    max_tokens: int = 4096
    context_window: int = 128_000
    min_complexity: TaskComplexity = TaskComplexity.TRIVIAL
    tags: list[str] = field(default_factory=list)


@dataclass
class RequestSpec:
    estimated_input_tokens: int
    estimated_output_tokens: int
    complexity: TaskComplexity
    priority: TaskPriority
    task_id: str = ""
    session_id: str = ""


@dataclass
class RouteResult:
    success: bool
    model: ModelSpec
    reason: str = ""
    estimated_cost: float = 0.0
    fallback_chain: list[str] = field(default_factory=list)


# ── Model Registry ────────────────────────────────────────────────

DEFAULT_MODELS: list[ModelSpec] = [
    # GPT family
    ModelSpec(
        "gpt-4o",
        "openai",
        2.50,
        10.00,
        16384,
        128000,
        TaskComplexity.COMPLEX,
        ["gpt", "vision", "best"],
    ),
    ModelSpec(
        "gpt-4o-mini",
        "openai",
        0.15,
        0.60,
        16384,
        128000,
        TaskComplexity.SIMPLE,
        ["gpt", "cheap", "fast"],
    ),
    # Claude family
    ModelSpec(
        "claude-3.5-sonnet",
        "anthropic",
        3.00,
        15.00,
        8192,
        200000,
        TaskComplexity.COMPLEX,
        ["claude", "code", "best"],
    ),
    ModelSpec(
        "claude-3-haiku",
        "anthropic",
        0.25,
        1.25,
        4096,
        200000,
        TaskComplexity.TRIVIAL,
        ["claude", "cheap", "fast"],
    ),
    # DeepSeek
    ModelSpec(
        "deepseek-v3",
        "deepseek",
        0.27,
        1.10,
        8192,
        64000,
        TaskComplexity.MODERATE,
        ["deepseek", "value"],
    ),
    ModelSpec(
        "deepseek-r1",
        "deepseek",
        0.55,
        2.19,
        32768,
        128000,
        TaskComplexity.EXPERT,
        ["deepseek", "reasoning", "best"],
    ),
    # Gemini
    ModelSpec(
        "gemini-2.5-pro",
        "google",
        1.25,
        10.00,
        8192,
        1048576,
        TaskComplexity.EXPERT,
        ["gemini", "best", "context"],
    ),
    ModelSpec(
        "gemini-2.5-flash",
        "google",
        0.15,
        0.60,
        8192,
        1048576,
        TaskComplexity.SIMPLE,
        ["gemini", "cheap", "fast"],
    ),
    # Ollama / local
    ModelSpec(
        "llama3.2-3b", "ollama", 0.0, 0.0, 4096, 128000, TaskComplexity.TRIVIAL, ["local", "free"]
    ),
    ModelSpec(
        "qwen2.5-7b", "ollama", 0.0, 0.0, 8192, 128000, TaskComplexity.SIMPLE, ["local", "free"]
    ),
]


# ── Model Router ──────────────────────────────────────────────────


class ModelRouter:
    """Intelligent model router with budget-aware selection.

    Selects the best model for each task based on complexity, priority,
    and daily budget. Supports fallback chains when the preferred model
    would exceed budget limits.

    Usage:
        router = ModelRouter.with_defaults(daily_budget_usd=50.0)
        spec = RequestSpec(
            estimated_input_tokens=2000,
            estimated_output_tokens=500,
            complexity=TaskComplexity.COMPLEX,
            priority=TaskPriority.NORMAL,
        )
        result = router.route(spec)
        if result.success:
            print(f"Routed to {result.model.name}, cost ~${result.estimated_cost:.4f}")
    """

    def __init__(
        self,
        models: list[ModelSpec],
        daily_budget_usd: float = 50.0,
        complexity_cost_map: dict[TaskComplexity, float] | None = None,
    ):
        self.models = models
        self._daily_budget = daily_budget_usd
        self._daily_spent = 0.0
        self._day_start = time.time()
        self._request_count = 0
        self._route_cache: dict[str, str] = {}  # session_id → model_name

        # Complexity → max estimated cost multiplier
        self._complexity_budget: dict[TaskComplexity, float] = complexity_cost_map or {
            TaskComplexity.TRIVIAL: 0.002,
            TaskComplexity.SIMPLE: 0.01,
            TaskComplexity.MODERATE: 0.05,
            TaskComplexity.COMPLEX: 0.20,
            TaskComplexity.EXPERT: 0.50,
        }

        # Sort models by cost (cheapest first for fallback)
        self._by_cost = sorted(models, key=lambda m: m.cost_per_1k_input)

    # ── Factory ────────────────────────────────────────────────────

    @classmethod
    def with_defaults(cls, daily_budget_usd: float = 50.0) -> ModelRouter:
        """Create a ModelRouter with default model registry."""
        return cls(models=list(DEFAULT_MODELS), daily_budget_usd=daily_budget_usd)

    # ── Routing ────────────────────────────────────────────────────

    def route(self, spec: RequestSpec) -> RouteResult:
        """Select the best model for the given request spec."""
        self._request_count += 1
        self._maybe_reset_daily()

        # Check session affinity: if we've routed this session before, use same model
        if spec.session_id and spec.session_id in self._route_cache:
            model_name = self._route_cache[spec.session_id]
            model = next((m for m in self.models if m.name == model_name), None)
            if model:
                est_cost = self._estimate_cost(model, spec)
                if est_cost + self._daily_spent <= self._daily_budget:
                    return RouteResult(
                        success=True,
                        model=model,
                        reason=f"Session affinity → {model.name}",
                        estimated_cost=est_cost,
                    )

        # 1. Find candidate models that can handle this complexity
        candidates = [m for m in self.models if m.min_complexity.value <= spec.complexity.value]
        if not candidates:
            # Use cheapest as fallback
            candidates = [self._by_cost[0]]

        # 2. For high/critical priority, prefer top-tier
        if spec.priority in (TaskPriority.HIGH, TaskPriority.CRITICAL):
            # Filter to best-in-class models
            tier = [m for m in candidates if "best" in m.tags]
            if tier:
                candidates = tier

        # 3. Budget-aware selection
        max_budget = self._complexity_budget.get(spec.complexity, 0.05)

        # Try each candidate, falling back to cheaper ones if over budget
        fallback_chain: list[str] = []
        for model in sorted(candidates, key=lambda m: m.cost_per_1k_input):
            est_cost = self._estimate_cost(model, spec)
            if est_cost <= max_budget:
                if self._daily_spent + est_cost <= self._daily_budget:
                    # Cache session → model
                    if spec.session_id:
                        self._route_cache[spec.session_id] = model.name
                    return RouteResult(
                        success=True,
                        model=model,
                        reason=f"Best match within budget ({spec.complexity.name})",
                        estimated_cost=est_cost,
                        fallback_chain=fallback_chain,
                    )
            fallback_chain.append(model.name)

        # 4. No model fits budget — use cheapest as emergency fallback
        cheapest = self._by_cost[0]
        est_cost = self._estimate_cost(cheapest, spec)
        return RouteResult(
            success=True,
            model=cheapest,
            reason=f"Budget constrained — fallen back to {cheapest.name}",
            estimated_cost=est_cost,
            fallback_chain=fallback_chain,
        )

    def record_request(
        self,
        model_name: str,
        success: bool = True,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
    ):
        """Record actual usage for budget tracking.

        Args:
            model_name: The model that was actually used.
            success: Whether the request succeeded.
            tokens_used: Total tokens consumed (input + output).
            cost_usd: Actual cost in USD.
            latency_ms: Request latency in milliseconds.
        """
        self._daily_spent += cost_usd
        self._request_count += 1

    # ── Budget ─────────────────────────────────────────────────────

    @property
    def daily_budget_remaining(self) -> float:
        self._maybe_reset_daily()
        return max(0.0, self._daily_budget - self._daily_spent)

    @property
    def daily_budget_total(self) -> float:
        return self._daily_budget

    @property
    def daily_spent(self) -> float:
        self._maybe_reset_daily()
        return self._daily_spent

    # ── Summary ────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return router state summary."""
        return {
            "models_available": len(self.models),
            "daily_budget_usd": self._daily_budget,
            "daily_spent": round(self._daily_spent, 6),
            "daily_remaining": round(self.daily_budget_remaining, 4),
            "request_count": self._request_count,
            "cached_sessions": len(self._route_cache),
        }

    # ── Internal ───────────────────────────────────────────────────

    def _estimate_cost(self, model: ModelSpec, spec: RequestSpec) -> float:
        """Estimate USD cost for a request."""
        input_cost = (spec.estimated_input_tokens / 1000) * model.cost_per_1k_input
        output_cost = (spec.estimated_output_tokens / 1000) * model.cost_per_1k_output
        return input_cost + output_cost

    def _maybe_reset_daily(self):
        """Reset daily budget if a day has passed."""
        if time.time() - self._day_start > 86400:
            self._daily_spent = 0.0
            self._day_start = time.time()
            self._route_cache.clear()
