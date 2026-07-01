"""
智能路由策略 — 按任务复杂度自动选择模型。
"""

from __future__ import annotations

from enum import Enum


class Complexity(str, Enum):

    """复杂度评估结果。"""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX_REASONING = "complex_reasoning"
    LARGE_CODEBASE = "large_codebase"
    CRITICAL = "critical"


class Budget(str, Enum):

    """成本预算配置。"""

    UNLIMITED = "unlimited"
    NORMAL = "normal"
    TIGHT = "tight"


ROUTING_TABLE: dict[tuple[Complexity, Budget], str] = {
    (Complexity.SIMPLE, Budget.TIGHT): "minimax-m2.7",
    (Complexity.SIMPLE, Budget.NORMAL): "deepseek-v3.1",
    (Complexity.SIMPLE, Budget.UNLIMITED): "deepseek-v3.1",
    (Complexity.MODERATE, Budget.TIGHT): "deepseek-v3.1",
    (Complexity.MODERATE, Budget.NORMAL): "kimi-k2.6",
    (Complexity.MODERATE, Budget.UNLIMITED): "kimi-k2.6",
    (Complexity.COMPLEX_REASONING, Budget.TIGHT): "deepseek-r1",
    (Complexity.COMPLEX_REASONING, Budget.NORMAL): "deepseek-r1",
    (Complexity.COMPLEX_REASONING, Budget.UNLIMITED): "claude-opus-4.8",
    (Complexity.LARGE_CODEBASE, Budget.TIGHT): "qwen-3.6-plus",
    (Complexity.LARGE_CODEBASE, Budget.NORMAL): "qwen-3.6-plus",
    (Complexity.LARGE_CODEBASE, Budget.UNLIMITED): "qwen-3.6-plus",
    (Complexity.CRITICAL, Budget.TIGHT): "kimi-k2.6",
    (Complexity.CRITICAL, Budget.NORMAL): "kimi-k2.6",
    (Complexity.CRITICAL, Budget.UNLIMITED): "claude-opus-4.8",
}

# 简单启发式的复杂度与预算判定规则
SIMPLE_KEYWORDS = ["list", "show", "display", "read", "what is", "how to", "print"]
COMPLEX_KEYWORDS = ["analyze", "debug", "optimize", "refactor", "design", "architecture", "research"]
LARGE_KEYWORDS = ["entire codebase", "all files", "monorepo", "whole project"]
CRITICAL_KEYWORDS = ["production", "critical", "must not fail", "urgent"]

TIGHT_BUDGET_KEYWORDS = ["cheapest", "save cost", "budget mode", "最便宜", "省钱"]


class RoutingStrategy:
    """根据任务描述自动决定使用哪个模型。"""

    @staticmethod
    def assess_complexity(task: str) -> Complexity:
        task_lower = task.lower()
        if any(kw in task_lower for kw in CRITICAL_KEYWORDS):
            return Complexity.CRITICAL
        if any(kw in task_lower for kw in LARGE_KEYWORDS):
            return Complexity.LARGE_CODEBASE
        if any(kw in task_lower for kw in COMPLEX_KEYWORDS):
            return Complexity.COMPLEX_REASONING
        if any(kw in task_lower for kw in SIMPLE_KEYWORDS):
            return Complexity.SIMPLE
        return Complexity.MODERATE

    @staticmethod
    def assess_budget(task: str) -> Budget:
        task_lower = task.lower()
        if any(kw in task_lower for kw in TIGHT_BUDGET_KEYWORDS):
            return Budget.TIGHT
        return Budget.NORMAL

    @classmethod
    def route(cls, task: str, budget: Budget | None = None) -> str:
        complexity = cls.assess_complexity(task)
        if budget is None:
            budget = cls.assess_budget(task)
        return ROUTING_TABLE.get((complexity, budget), "kimi-k2.6")
