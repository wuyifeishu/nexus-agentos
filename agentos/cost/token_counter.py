"""
Token Counter — Model-aware token counting and cost estimation.

Supports tiktoken-based counting for OpenAI models and approximate
counting for other providers (Anthropic, Google, local models).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ModelFamily(Enum):

    """模型系列枚举。"""

    GPT4 = "gpt-4"
    GPT4O = "gpt-4o"
    GPT35 = "gpt-3.5-turbo"
    CLAUDE3 = "claude-3"
    CLAUDE35 = "claude-3.5"
    GEMINI = "gemini"
    LLAMA = "llama"
    MIXTRAL = "mixtral"
    UNKNOWN = "unknown"


@dataclass
class TokenCount:
    """Token counts for a message or conversation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""


@dataclass
class CostEstimate:
    """Estimated cost for token usage."""

    prompt_cost: float = 0.0
    completion_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"
    token_count: Optional[TokenCount] = None


# Pricing per 1M tokens (input, output) — updated mid-2025
PRICING_TABLE: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Anthropic
    "claude-3.5-sonnet": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3-sonnet": (3.00, 15.00),
    # Google
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    # Open-source (hosted)
    "llama-3-70b": (0.59, 0.79),
    "llama-3-8b": (0.06, 0.06),
    "mixtral-8x7b": (0.24, 0.24),
}


class TokenCounter:
    """
    Model-aware token counting and cost estimation.

    Uses tiktoken when available for OpenAI models, falls back to
    character-based approximation for other models.

    Example::

        counter = TokenCounter()
        tokens = counter.count("Hello, world!", model="gpt-4o")
        cost = counter.estimate_cost(tokens, model="gpt-4o")
    """

    # Characters per token — rough estimates per model family
    CHARS_PER_TOKEN: dict[ModelFamily, float] = {
        ModelFamily.GPT4: 3.5,
        ModelFamily.GPT4O: 3.8,
        ModelFamily.GPT35: 4.0,
        ModelFamily.CLAUDE3: 3.2,
        ModelFamily.CLAUDE35: 3.4,
        ModelFamily.GEMINI: 3.0,
        ModelFamily.LLAMA: 3.8,
        ModelFamily.MIXTRAL: 3.6,
        ModelFamily.UNKNOWN: 4.0,
    }

    def __init__(self):
        self._tiktoken_available = self._try_load_tiktoken()
        self._encoders: dict[str, object] = {}
        self._usage_log: list[TokenCount] = []

    def _try_load_tiktoken(self) -> bool:
        try:
            import tiktoken
            self._tiktoken = tiktoken
            return True
        except ImportError:
            return False

    def _get_encoder(self, model: str):
        """Get tiktoken encoder for model, with caching."""
        if not self._tiktoken_available:
            return None

        if model in self._encoders:
            return self._encoders[model]

        try:
            encoder = self._tiktoken.encoding_for_model(model)
        except KeyError:
            try:
                encoder = self._tiktoken.get_encoding("cl100k_base")
            except Exception:
                return None
        self._encoders[model] = encoder
        return encoder

    def count(self, text: str, model: str = "gpt-4o") -> TokenCount:
        """
        Count tokens in text for a specific model.

        Args:
            text: The text to count tokens for.
            model: Model identifier string.

        Returns:
            TokenCount with prompt_tokens set (single text counts as prompt).
        """
        family = self._classify_model(model)
        encoder = self._get_encoder(model)

        if encoder:
            count_val = len(encoder.encode(text))
        else:
            chars_per = self.CHARS_PER_TOKEN.get(family, 4.0)
            count_val = max(1, int(len(text) / chars_per))

        result = TokenCount(
            prompt_tokens=count_val,
            total_tokens=count_val,
            model=model,
        )
        self._usage_log.append(result)
        return result

    def count_messages(
        self, messages: list[dict[str, str]], model: str = "gpt-4o",
    ) -> TokenCount:
        """
        Count tokens for a list of chat messages.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts.
            model: Model identifier.

        Returns:
            TokenCount with total prompt tokens.
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            # Role overhead: ~4 tokens per message
            total += 4
            total += self.count(content, model=model).prompt_tokens

        result = TokenCount(
            prompt_tokens=total,
            total_tokens=total,
            model=model,
        )
        self._usage_log.append(result)
        return result

    def estimate_cost(
        self, token_count: TokenCount, model: Optional[str] = None,
    ) -> CostEstimate:
        """
        Estimate USD cost from token usage.

        Args:
            token_count: Token counts from count() or count_messages().
            model: Override model for pricing lookup.

        Returns:
            CostEstimate with total USD cost.
        """
        m = model or token_count.model
        pricing = self._get_pricing(m)

        prompt_cost = (token_count.prompt_tokens / 1_000_000) * pricing[0]
        completion_cost = (token_count.completion_tokens / 1_000_000) * pricing[1]

        return CostEstimate(
            prompt_cost=prompt_cost,
            completion_cost=completion_cost,
            total_cost=prompt_cost + completion_cost,
            token_count=token_count,
        )

    def _get_pricing(self, model: str) -> tuple[float, float]:
        """Find closest pricing match for model."""
        if model in PRICING_TABLE:
            return PRICING_TABLE[model]

        # Try prefix match
        for key, pricing in PRICING_TABLE.items():
            if model.startswith(key):
                return pricing

        # Default: conservative estimate
        return (1.00, 3.00)

    def _classify_model(self, model: str) -> ModelFamily:
        model_lower = model.lower()
        if "gpt-4o" in model_lower:
            return ModelFamily.GPT4O
        if "gpt-4" in model_lower:
            return ModelFamily.GPT4
        if "gpt-3.5" in model_lower:
            return ModelFamily.GPT35
        if "claude-3.5" in model_lower:
            return ModelFamily.CLAUDE35
        if "claude-3" in model_lower or "claude" in model_lower:
            return ModelFamily.CLAUDE3
        if "gemini" in model_lower:
            return ModelFamily.GEMINI
        if "llama" in model_lower:
            return ModelFamily.LLAMA
        if "mixtral" in model_lower:
            return ModelFamily.MIXTRAL
        return ModelFamily.UNKNOWN

    def get_total_usage(self) -> TokenCount:
        """Aggregate all logged usage."""
        prompt = sum(u.prompt_tokens for u in self._usage_log)
        completion = sum(u.completion_tokens for u in self._usage_log)
        return TokenCount(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )

    def get_total_cost(self) -> CostEstimate:
        """Estimate total cost of all logged usage."""
        total_tokens = self.get_total_usage()
        total_cost = 0.0
        for entry in self._usage_log:
            cost = self.estimate_cost(entry)
            total_cost += cost.total_cost
        return CostEstimate(total_cost=total_cost, token_count=total_tokens)

    def reset_usage(self) -> None:
        self._usage_log.clear()

    @staticmethod
    def format_cost(cost: CostEstimate) -> str:
        """Human-readable cost string."""
        if cost.total_cost < 0.01:
            return f"${cost.total_cost:.6f}"
        if cost.total_cost < 1.0:
            return f"${cost.total_cost:.4f}"
        return f"${cost.total_cost:.2f}"

    @staticmethod
    def format_tokens(tokens: TokenCount) -> str:
        """Human-readable token count string."""
        if tokens.total_tokens < 1000:
            return str(tokens.total_tokens)
        return f"{tokens.total_tokens / 1000:.1f}K"
