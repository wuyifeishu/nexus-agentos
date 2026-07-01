"""
Ollama Provider — 本地 LLM 推理，OpenAI 兼容协议。
零额外依赖，纯 httpx 实现。支持任意 Ollama 模型（qwen2.5, llama3, gemma, mistral 等）。

用法:
    provider = OllamaProvider(model="qwen2.5:7b", base_url="http://localhost:11434/v1")
"""

from __future__ import annotations

from typing import Any

from agentos.llm.openai_provider import OpenAIProvider

__all__ = ["OllamaProvider"]

OLLAMA_DEFAULT_BASE = "http://localhost:11434/v1"
OLLAMA_DEFAULT_MODEL = "qwen2.5:7b"


class OllamaProvider(OpenAIProvider):
    """Ollama 本地 LLM Provider — 通过 OpenAI 兼容 API 调用。

    支持所有 Ollama 模型：qwen2.5, llama3.1, gemma2, mistral, deepseek-r1 等。

    环境变量:
        OLLAMA_API_KEY: API Key（Ollama 默认不需要，可留空）
        OLLAMA_BASE_URL: Ollama 服务地址，默认 http://localhost:11434/v1
    """

    def __init__(
        self,
        model: str = OLLAMA_DEFAULT_MODEL,
        api_key: str = "",
        base_url: str = "",
        timeout: float = 120.0,
    ):
        import os

        resolved_base = base_url or os.getenv("OLLAMA_BASE_URL", OLLAMA_DEFAULT_BASE)
        resolved_key = api_key or os.getenv("OLLAMA_API_KEY", "ollama")

        super().__init__(
            model=model,
            api_key=resolved_key,
            base_url=resolved_base,
        )
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "ollama"

    def chat(self, *args: Any, **kwargs: Any):
        # Override timeout
        kwargs.setdefault("timeout", self._timeout)
        return super().chat(*args, **kwargs)

    async def achat(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("timeout", self._timeout)
        return await super().achat(*args, **kwargs)
