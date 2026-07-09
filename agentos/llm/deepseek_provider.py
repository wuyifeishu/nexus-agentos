"""
DeepSeek Provider — 基于 OpenAIProvider 子类化，仅换 base_url。
DeepSeek API 完全兼容 OpenAI Chat Completions 格式。
v1.3.36: 首个实现，支持 Function Calling。
"""

from __future__ import annotations

from agentos.llm.openai_provider import OpenAIProvider

__all__ = ["DeepSeekProvider"]

# USD per 1M tokens (DeepSeek pricing as of 2025-06)
_DEEPSEEK_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
}


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek Provider — OpenAI 兼容，零额外代码。

    用法:
        provider = DeepSeekProvider(api_key="sk-...")
        result = provider.chat([Message(role=MessageRole.USER, content="Hello")])
    """

    _pricing_injected: bool = False

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        timeout: float = 120.0,
    ):
        super().__init__(model=model, api_key=api_key, base_url=base_url, timeout=timeout)
        if not self._pricing_injected:
            from agentos.llm.openai_provider import _PRICING

            _PRICING.update(_DEEPSEEK_PRICING)
            DeepSeekProvider._pricing_injected = True

    @property
    def provider_name(self) -> str:
        return "deepseek"
