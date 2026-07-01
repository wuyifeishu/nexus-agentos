"""
AgentOS v1.2.7 — Minimal ModelRouter for CodeAgent.

Lightweight LLM call wrapper using httpx to OpenAI-compatible endpoints.
Designed as a self-contained module with zero internal dependencies.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from agentos.tools.base import ToolCall


@dataclass
class ModelResponse:
    """LLM 响应：文本内容 + 函数调用列表。"""
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class ModelSpec:
    """单个模型的规格定义。"""
    provider: str
    model_id: str
    context_window: int = 128_000
    api_key: str = ""
    base_url: str = ""
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0


class AllModelsFailed(Exception):

    """所有模型均失败异常。"""

    pass


@dataclass
class ModelConfig:
    """模型路由配置。"""
    default_model: str = "gpt-4o-mini"
    fallback_chain: list[str] = field(default_factory=list)
    models: dict[str, ModelSpec] = field(default_factory=dict)
    max_retries: int = 3
    request_timeout: int = 120


RECOMMENDED_CONFIG = ModelConfig(
    default_model="gpt-4o-mini",
    fallback_chain=["gpt-4o", "claude-3.5-sonnet"],
    models={
        "gpt-4o-mini": ModelSpec(provider="openai", model_id="gpt-4o-mini", context_window=128_000),
        "gpt-4o": ModelSpec(provider="openai", model_id="gpt-4o", context_window=128_000),
        "claude-3.5-sonnet": ModelSpec(provider="anthropic", model_id="claude-3.5-sonnet", context_window=200_000),
    },
)


@dataclass
class ModelRouter:
    """Minimal LLM router for code generation tasks."""

    api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Send a chat request and return text content."""
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
