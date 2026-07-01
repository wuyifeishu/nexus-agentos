"""
v1.10.0: Cost Tracker — token counting & pricing across all providers.

Tracks token usage and cost for: OpenAI, Anthropic, Google, DeepSeek, Groq.
Features: per-request tracking, budget management, usage reporting.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ── Data Classes ──────────────────────────────────────────────────

class ProviderPricing(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    DEEPSEEK = "deepseek"
    GROQ = "groq"
    CUSTOM = "custom"


@dataclass
class TokenPricing:
    """Pricing per 1M tokens (input/output)."""
    provider: ProviderPricing
    model: str
    input_price_per_1m: float       # USD per 1M input tokens
    output_price_per_1m: float      # USD per 1M output tokens
    cache_write_price_per_1m: float = 0.0
    cache_read_price_per_1m: float = 0.0

    def cost(self, input_tokens: int, output_tokens: int,
             cache_write: int = 0, cache_read: int = 0) -> float:
        return (
            (input_tokens / 1_000_000) * self.input_price_per_1m
            + (output_tokens / 1_000_000) * self.output_price_per_1m
            + (cache_write / 1_000_000) * self.cache_write_price_per_1m
            + (cache_read / 1_000_000) * self.cache_read_price_per_1m
        )


@dataclass
class TokenUsage:
    """Token usage for a single API call."""
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    timestamp: str = ""

    def __post_init__(self):
        if not self.total_tokens:
            self.total_tokens = self.input_tokens + self.output_tokens
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class Budget:
    """Spending budget configuration."""
    name: str
    limit: float                        # USD
    period: str = "monthly"             # daily / weekly / monthly / total
    current_spend: float = 0.0
    alert_threshold: float = 0.8        # Alert at 80% of limit
    hard_stop: bool = False             # Block requests when exceeded

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.current_spend)

    @property
    def pct_used(self) -> float:
        return (self.current_spend / self.limit * 100) if self.limit > 0 else 0.0

    @property
    def exceeded(self) -> bool:
        return self.current_spend >= self.limit

    @property
    def should_alert(self) -> bool:
        return self.pct_used >= self.alert_threshold * 100


# ── Default Pricing (as of 2025-07) ────────────────────────────────

DEFAULT_PRICING: dict[str, TokenPricing] = {
    # OpenAI
    "gpt-4o": TokenPricing(ProviderPricing.OPENAI, "gpt-4o", 2.50, 10.00),
    "gpt-4o-mini": TokenPricing(ProviderPricing.OPENAI, "gpt-4o-mini", 0.15, 0.60),
    "gpt-4-turbo": TokenPricing(ProviderPricing.OPENAI, "gpt-4-turbo", 10.00, 30.00),
    "gpt-3.5-turbo": TokenPricing(ProviderPricing.OPENAI, "gpt-3.5-turbo", 0.50, 1.50),
    "o3-mini": TokenPricing(ProviderPricing.OPENAI, "o3-mini", 1.10, 4.40),
    # Anthropic
    "claude-3-5-sonnet": TokenPricing(ProviderPricing.ANTHROPIC, "claude-3-5-sonnet", 3.00, 15.00,
                                      cache_write_price_per_1m=3.75, cache_read_price_per_1m=0.30),
    "claude-3-haiku": TokenPricing(ProviderPricing.ANTHROPIC, "claude-3-haiku", 0.25, 1.25),
    "claude-3-opus": TokenPricing(ProviderPricing.ANTHROPIC, "claude-3-opus", 15.00, 75.00),
    # Google
    "gemini-2.0-flash": TokenPricing(ProviderPricing.GOOGLE, "gemini-2.0-flash", 0.10, 0.40),
    "gemini-2.0-pro": TokenPricing(ProviderPricing.GOOGLE, "gemini-2.0-pro", 1.25, 5.00),
    "gemini-1.5-pro": TokenPricing(ProviderPricing.GOOGLE, "gemini-1.5-pro", 1.25, 5.00),
    # DeepSeek
    "deepseek-chat": TokenPricing(ProviderPricing.DEEPSEEK, "deepseek-chat", 0.27, 1.10),
    "deepseek-reasoner": TokenPricing(ProviderPricing.DEEPSEEK, "deepseek-reasoner", 0.55, 2.19),
    # Groq
    "llama-3.3-70b": TokenPricing(ProviderPricing.GROQ, "llama-3.3-70b", 0.59, 0.79),
    "mixtral-8x7b": TokenPricing(ProviderPricing.GROQ, "mixtral-8x7b", 0.24, 0.24),
    "gemma2-9b-it": TokenPricing(ProviderPricing.GROQ, "gemma2-9b-it", 0.20, 0.20),
}


# ── Token Counter (heuristic-based, provider-agnostic) ────────────

class TokenCounter:
    """Approximate token counter based on word count + code heuristics.

    For exact counts, use provider-specific tokenizers (tiktoken, etc.).
    This provides fast, offline estimates within ~10% accuracy.
    """

    # Rough tokens-per-word ratios (language-dependent)
    TOKENS_PER_WORD: dict[str, float] = {
        "en": 1.3,   # ~4 chars/token for English
        "zh": 0.5,   # ~2 chars/token for Chinese (character-based)
        "ja": 0.6,
        "ko": 0.6,
        "code": 0.7,  # Code tends to be denser in tokens per word
        "default": 1.0,
    }

    @classmethod
    def count(cls, text: str, source: str = "default") -> int:
        """Estimate token count."""
        if not text:
            return 0

        ratio = cls.TOKENS_PER_WORD.get(source, cls.TOKENS_PER_WORD["default"])
        chars = len(text)

        # For Chinese (high CJK ratio), use character-based estimation
        cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff'
                       or '\u3040' <= c <= '\u30ff')
        cjk_ratio = cjk_chars / max(chars, 1)

        if cjk_ratio > 0.3:
            # Mostly Chinese/Japanese — use CJK character ratio
            non_cjk = chars - cjk_chars
            return int(cjk_chars * cls.TOKENS_PER_WORD["zh"] + non_cjk * 0.25)

        if source == "code" or cls._is_code(text):
            ratio = cls.TOKENS_PER_WORD["code"]

        words = len(text.split())
        return max(1, int(words * ratio))

    @staticmethod
    def _is_code(text: str) -> bool:
        """Heuristic: detect if text is code."""
        code_indicators = ["def ", "class ", "import ", "from ", "function",
                          "const ", "let ", "var ", "{", "}", "=>", "return "]
        count = sum(1 for ind in code_indicators if ind in text)
        return count >= 3


# ── Cost Tracker ───────────────────────────────────────────────────

class CostTracker:
    """Track token usage and costs across all provider calls.

    Usage:
        tracker = CostTracker()
        tracker.record("gpt-4o", input_tokens=500, output_tokens=200)
        tracker.record("claude-3-5-sonnet", input_tokens=1000, output_tokens=500)
        report = tracker.report()
    """

    def __init__(
        self,
        custom_pricing: dict[str, TokenPricing] | None = None,
        budgets: list[Budget] | None = None,
    ):
        self.pricing: dict[str, TokenPricing] = {**DEFAULT_PRICING}
        if custom_pricing:
            self.pricing.update(custom_pricing)

        self.budgets: dict[str, Budget] = {}
        if budgets:
            for b in budgets:
                self.budgets[b.name] = b

        self.usage_log: list[TokenUsage] = []
        self._model_totals: dict[str, dict[str, float]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "cost": 0.0, "calls": 0}
        )

    def get_price(self, model: str) -> TokenPricing:
        """Get pricing for a model. Falls back to default if unknown."""
        if model in self.pricing:
            return self.pricing[model]

        # Best-effort fallback based on model name
        if "gpt-4" in model:
            return TokenPricing(ProviderPricing.OPENAI, model, 2.50, 10.00)
        if "gpt-3" in model:
            return TokenPricing(ProviderPricing.OPENAI, model, 0.50, 1.50)
        if "claude" in model:
            return TokenPricing(ProviderPricing.ANTHROPIC, model, 3.00, 15.00)
        if "gemini" in model:
            return TokenPricing(ProviderPricing.GOOGLE, model, 0.10, 0.40)
        if "deepseek" in model:
            return TokenPricing(ProviderPricing.DEEPSEEK, model, 0.27, 1.10)
        if any(m in model for m in ["llama", "mixtral", "gemma"]):
            return TokenPricing(ProviderPricing.GROQ, model, 0.20, 0.20)

        return TokenPricing(ProviderPricing.CUSTOM, model, 1.00, 1.00)

    def record(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        latency_ms: float = 0.0,
    ) -> TokenUsage:
        """Record a token usage event. Returns the TokenUsage with cost."""
        pricing = self.get_price(model)
        cost = pricing.cost(input_tokens, output_tokens, cache_write_tokens, cache_read_tokens)

        usage = TokenUsage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_read_tokens=cache_read_tokens,
            cost=cost,
            latency_ms=latency_ms,
        )
        self.usage_log.append(usage)

        # Update model totals
        mt = self._model_totals[model]
        mt["input_tokens"] += input_tokens
        mt["output_tokens"] += output_tokens
        mt["cost"] += cost
        mt["calls"] += 1

        # Update budgets
        for budget in self.budgets.values():
            budget.current_spend += cost

        return usage

    def check_budget(self) -> list[str]:
        """Check all budgets. Returns list of alert messages."""
        alerts = []
        for budget in self.budgets.values():
            if budget.exceeded and budget.hard_stop:
                alerts.append(f"BUDGET EXCEEDED: {budget.name} (${budget.current_spend:.2f}/${budget.limit:.2f})")
            elif budget.should_alert:
                alerts.append(f"Budget alert: {budget.name} at {budget.pct_used:.0f}% (${budget.current_spend:.2f}/${budget.limit:.2f})")
        return alerts

    def report(self) -> str:
        """Generate a human-readable cost report."""
        total_cost = sum(u.cost for u in self.usage_log)
        total_tokens = sum(u.total_tokens for u in self.usage_log)
        total_calls = len(self.usage_log)

        lines = [
            f"╔══ Cost Report ══╗",
            f"║ Total calls:  {total_calls}",
            f"║ Total tokens: {total_tokens:,}",
            f"║ Total cost:   ${total_cost:.4f}",
            f"╚════════════════╝",
            "",
            "By model:",
        ]
        for model, totals in sorted(self._model_totals.items(), key=lambda x: -x[1]["cost"]):
            lines.append(
                f"  {model:<30} {totals['calls']:>4} calls  "
                f"{totals['input_tokens']+totals['output_tokens']:>12,} tokens  "
                f"${totals['cost']:>8.4f}"
            )

        if self.budgets:
            lines.append("\nBudgets:")
            for budget in self.budgets.values():
                status = "EXCEEDED" if budget.exceeded else "OK"
                lines.append(
                    f"  {budget.name:<20} ${budget.current_spend:.2f}/${budget.limit:.2f} "
                    f"({budget.pct_used:.0f}%) [{status}]"
                )

        return "\n".join(lines)

    def report_dict(self) -> dict[str, Any]:
        """Generate a machine-readable cost report."""
        return {
            "total_calls": len(self.usage_log),
            "total_tokens": sum(u.total_tokens for u in self.usage_log),
            "total_cost": sum(u.cost for u in self.usage_log),
            "by_model": {
                model: dict(totals)
                for model, totals in self._model_totals.items()
            },
            "recent": [
                {
                    "model": u.model,
                    "input_tokens": u.input_tokens,
                    "output_tokens": u.output_tokens,
                    "cost": u.cost,
                    "timestamp": u.timestamp,
                }
                for u in self.usage_log[-20:]  # Last 20 calls
            ],
        }

    def reset(self) -> None:
        """Reset all counters (keeps pricing and budgets)."""
        self.usage_log.clear()
        self._model_totals.clear()
        for budget in self.budgets.values():
            budget.current_spend = 0.0

    def set_budget(self, name: str, limit: float, hard_stop: bool = False) -> Budget:
        """Create or update a budget."""
        budget = Budget(name=name, limit=limit, hard_stop=hard_stop)
        self.budgets[name] = budget
        return budget


# ── Backward Compatibility Aliases (v1.2.7-) ──────────────────────
# Old names → new equivalents
RunCostSession = CostTracker              # CostTracker was RunCostSession
ModelPricing = TokenPricing               # ModelPricing → TokenPricing
UsageRecord = TokenUsage                  # UsageRecord → TokenUsage
PRICING = DEFAULT_PRICING                 # PRICING → DEFAULT_PRICING
