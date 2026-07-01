"""
LLM Provider 工厂 — 按名称/配置创建 Provider 实例。
v1.3.36: DeepSeek + Anthropic 硬注册（纯 httpx 实现，零 SDK 依赖）。

用法:
    from agentos.llm.factory import create_provider

    provider = create_provider("openai", model="gpt-4o", api_key="sk-...")
    result = provider.chat([Message(...), Message(...)])
"""

from __future__ import annotations

import os
from typing import Any

from agentos.llm.base import LLMProvider

__all__ = ["create_provider"]

_PROVIDER_REGISTRY: dict[str, tuple[str, str]] = {
    "openai": ("agentos.llm.openai_provider", "OpenAIProvider"),
    "deepseek": ("agentos.llm.deepseek_provider", "DeepSeekProvider"),
    "anthropic": ("agentos.llm.anthropic_provider", "AnthropicProvider"),
    "ollama": ("agentos.llm.ollama_provider", "OllamaProvider"),
    "pangu": ("agentos.llm.pangu_provider", "PanguProvider"),
}


def create_provider(
    name: str = "openai",
    *,
    model: str = "",
    api_key: str = "",
    base_url: str = "",
    **extra: Any,
) -> LLMProvider:
    """
    创建 LLM Provider 实例。

    Args:
        name: 提供商名称 — "openai" / "deepseek" / "anthropic"。
        model: 模型名称。openai: gpt-4o-mini, deepseek: deepseek-chat, anthropic: claude-sonnet-4-20250514。
        api_key: API Key。不传则从环境变量读取。
        base_url: 自定义端点。

    Returns:
        LLMProvider 实例。
    """
    if name not in _PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown provider: '{name}'. Available: {sorted(_PROVIDER_REGISTRY)}"
        )

    module_path, class_name = _PROVIDER_REGISTRY[name]

    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)

    # Auto-detect API key from env
    if not api_key:
        env_var_map = {
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "ollama": "OLLAMA_API_KEY",
            "pangu": "PANGU_API_KEY",
        }
        api_key = os.getenv(env_var_map.get(name, ""), "")

    # Default models
    if not model:
        defaults = {
            "openai": "gpt-4o-mini",
            "deepseek": "deepseek-chat",
            "anthropic": "claude-sonnet-5-20250630",
            "ollama": "qwen2.5:7b",
            "pangu": "pangu-4",
        }
        model = defaults.get(name, "")

    kwargs: dict[str, Any] = {}
    if base_url:
        kwargs["base_url"] = base_url
    return cls(model=model, api_key=api_key, **kwargs, **extra)
