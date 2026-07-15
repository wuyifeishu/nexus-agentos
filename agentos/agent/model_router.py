"""ModelRouter — intelligent model selection based on task complexity."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskComplexity(str, Enum):
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    EXPERT = "expert"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ModelSpec:
    name: str
    tier: Any = None  # ModelTier


@dataclass
class RequestSpec:
    estimated_input_tokens: int = 100
    estimated_output_tokens: int = 100
    complexity: TaskComplexity = TaskComplexity.SIMPLE
    priority: TaskPriority = TaskPriority.NORMAL
    task_id: str = ""
    session_id: str = ""


@dataclass
class RouteResult:
    success: bool = True
    model: ModelSpec = field(default_factory=lambda: ModelSpec(name="gpt-4o"))
    fallback_chain: list[str] = field(default_factory=list)
    estimated_cost: float = 0.0
    reason: str = ""


class ModelRouter:
    """Routes tasks to the best model based on complexity, budget, and availability."""

    def __init__(self, daily_budget_usd: float = 50.0) -> None:
        self._daily_budget_usd = daily_budget_usd
        self._used_today: float = 0.0
        self._requests: int = 0
        self._failures: int = 0

    @classmethod
    def with_defaults(cls, daily_budget_usd: float = 50.0) -> ModelRouter:
        return cls(daily_budget_usd=daily_budget_usd)

    def route(self, spec: RequestSpec) -> RouteResult:
        """Select the best model for the given request spec."""
        if self._used_today >= self._daily_budget_usd:
            return RouteResult(
                success=False,
                reason="budget exceeded",
            )

        # Simple model selection by complexity
        model_map = {
            TaskComplexity.TRIVIAL: "gpt-4o-mini",
            TaskComplexity.SIMPLE: "gpt-4o-mini",
            TaskComplexity.MODERATE: "gpt-4o",
            TaskComplexity.COMPLEX: "gpt-4o",
            TaskComplexity.EXPERT: "gpt-4o",
        }
        model_name = model_map.get(spec.complexity, "gpt-4o")
        estimated_cost = (spec.estimated_input_tokens + spec.estimated_output_tokens) * 0.000005

        return RouteResult(
            success=True,
            model=ModelSpec(name=model_name),
            estimated_cost=estimated_cost,
            reason="matched",
        )

    def record_request(
        self,
        model_name: str,
        success: bool,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
    ) -> None:
        """Record stats for a completed request."""
        self._requests += 1
        self._used_today += cost_usd
        if not success:
            self._failures += 1

    @property
    def daily_budget_remaining(self) -> float:
        return max(0.0, self._daily_budget_usd - self._used_today)

    def summary(self) -> dict[str, Any]:
        return {
            "budget_used": self._used_today,
            "budget_remaining": self.daily_budget_remaining,
            "total_requests": self._requests,
            "failures": self._failures,
        }
