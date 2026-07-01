"""
OpenAI Provider 实现 — 基于官方 openai SDK 的对话补全。
v1.3.36: +Function Calling / Tool Use 支持。
"""

from __future__ import annotations

import json
from typing import Any, Iterator

try:
    from openai import AsyncOpenAI, OpenAI
    from openai.types.chat import ChatCompletionMessageParam
except ImportError as e:
    raise ImportError(
        "openai SDK not installed. Run: pip install 'nexus-agentos[openai]'"
    ) from e

from agentos.llm.base import (
    CompletionChoice,
    CompletionResult,
    CompletionUsage,
    LLMProvider,
    Message,
    MessageRole,
    StreamChunk,
    Tool,
    ToolCall,
)

__all__ = ["OpenAIProvider"]


_ROLE_MAP: dict[MessageRole, str] = {
    MessageRole.SYSTEM: "system",
    MessageRole.USER: "user",
    MessageRole.ASSISTANT: "assistant",
    MessageRole.TOOL: "tool",
}

_REVERSE_ROLE_MAP: dict[str, MessageRole] = {v: k for k, v in _ROLE_MAP.items()}

# USD per 1K tokens (as of 2025-06)
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.0100),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4.1": (0.0020, 0.0080),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-4.1-nano": (0.0001, 0.0004),
    "o3": (0.0100, 0.0400),
    "o3-mini": (0.0011, 0.0044),
    "o4-mini": (0.0011, 0.0044),
}


def _messages_to_openai(messages: list[Message]) -> list[ChatCompletionMessageParam]:
    """将 Message 列表转换为 OpenAI SDK 格式。"""
    result: list[ChatCompletionMessageParam] = []
    for m in messages:
        entry: dict[str, Any] = {"role": _ROLE_MAP[m.role], "content": m.content}
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in m.tool_calls
            ]
        result.append(entry)
    return result


def _tools_to_openai(tools: list[Tool] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [t.as_schema() for t in tools]


def _extract_tool_calls(message_obj) -> list[ToolCall]:
    """从 OpenAI message 对象中提取 ToolCall 列表。"""
    raw = getattr(message_obj, "tool_calls", None) or []
    result: list[ToolCall] = []
    for tc in raw:
        fn = getattr(tc, "function", None)
        result.append(ToolCall(
            id=tc.id,
            name=fn.name if fn else "",
            arguments=fn.arguments if fn else "{}",
        ))
    return result


def _build_result(raw, model: str | None = None) -> CompletionResult:
    """从 OpenAI SDK 响应构建 CompletionResult。"""
    m = raw.choices[0].message
    role = _REVERSE_ROLE_MAP.get(m.role, MessageRole.ASSISTANT)
    tool_calls = _extract_tool_calls(m)
    choice = CompletionChoice(
        index=raw.choices[0].index,
        message=Message(
            role=role, content=m.content or "",
            tool_calls=tool_calls if tool_calls else None,
        ),
        finish_reason=raw.choices[0].finish_reason or "stop",
    )
    usage = raw.usage
    tokens = CompletionUsage(
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=usage.total_tokens if usage else 0,
    )
    resolved_model = model or raw.model or ""
    if resolved_model in _PRICING:
        in_price, out_price = _PRICING[resolved_model]
        tokens.cost_usd = round(
            tokens.prompt_tokens / 1000 * in_price + tokens.completion_tokens / 1000 * out_price, 6
        )
    return CompletionResult(
        id=raw.id, model=resolved_model, choices=[choice], usage=tokens, created=raw.created
    )


class OpenAIProvider(LLMProvider):
    """OpenAI SDK 提供商。支持 openai、azure、及所有 OpenAI 兼容的三方端点。"""

    _sync_client: OpenAI | None = None
    _async_client: AsyncOpenAI | None = None

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str = "",
        base_url: str = "",
        organization: str = "",
        timeout: float = 60.0,
    ):
        super().__init__(model=model, api_key=api_key, base_url=base_url)
        self._organization = organization
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "openai"

    def _get_client(self) -> OpenAI:
        if self._sync_client is None:
            kwargs: dict[str, Any] = {"timeout": self._timeout, "max_retries": 2}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            if self._organization:
                kwargs["organization"] = self._organization
            self._sync_client = OpenAI(**kwargs)
        return self._sync_client

    def _get_async_client(self) -> AsyncOpenAI:
        if self._async_client is None:
            kwargs: dict[str, Any] = {"timeout": self._timeout, "max_retries": 2}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            if self._organization:
                kwargs["organization"] = self._organization
            self._async_client = AsyncOpenAI(**kwargs)
        return self._async_client

    def chat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        stop: list[str] | None = None,
        tools: list[Tool] | None = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> CompletionResult:
        client = self._get_client()
        params: dict[str, Any] = {
            "model": self.model,
            "messages": _messages_to_openai(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "stop": stop,
            **kwargs,
        }
        if tools:
            params["tools"] = _tools_to_openai(tools)
            params["tool_choice"] = tool_choice
        resp = client.chat.completions.create(**params)
        return _build_result(resp, model=self.model)

    async def achat(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 1.0,
        stop: list[str] | None = None,
        tools: list[Tool] | None = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> CompletionResult:
        client = self._get_async_client()
        params: dict[str, Any] = {
            "model": self.model,
            "messages": _messages_to_openai(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "stop": stop,
            **kwargs,
        }
        if tools:
            params["tools"] = _tools_to_openai(tools)
            params["tool_choice"] = tool_choice
        resp = await client.chat.completions.create(**params)
        return _build_result(resp, model=self.model)

    def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        client = self._get_client()
        params: dict[str, Any] = {
            "model": self.model,
            "messages": _messages_to_openai(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs,
        }
        if tools:
            params["tools"] = _tools_to_openai(tools)
        stream_resp = client.chat.completions.create(**params)
        for chunk in stream_resp:
            if chunk.choices and chunk.choices[0].delta.content:
                yield StreamChunk(
                    content=chunk.choices[0].delta.content,
                    finish_reason=(
                        chunk.choices[0].finish_reason if chunk.choices[0].finish_reason else None
                    ),
                    index=chunk.choices[0].index,
                )
