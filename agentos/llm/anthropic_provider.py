"""
Anthropic Claude Provider — 基于 httpx 直接调用 Anthropic Messages API。
零额外依赖，不依赖 anthropic SDK。
v1.3.36: 首个纯 httpx 实现，支持同步/异步/流式/Function Calling。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

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

__all__ = ["AnthropicProvider"]

ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"

# USD per 1M tokens (Anthropic pricing as of 2026-07)
_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-20250630": (3.0, 15.0),  # Sonnet 5 — 性价比最高的 Agent 模型
    "claude-sonnet-5-20250701": (3.0, 15.0),  # Sonnet 5 (alternate ID)
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-3-5-sonnet-20241022": (3.0, 15.0),
    "claude-3-5-haiku-20241022": (0.80, 4.0),
    "claude-3-opus-20240229": (15.0, 75.0),
    "claude-3-haiku-20240307": (0.25, 1.25),
    "claude-opus-4-20250514": (15.0, 75.0),  # Opus 4
    "claude-opus-4-5-20251101": (15.0, 75.0),  # Opus 4.5
}

# 5-series models identified by prefix
_SONNET5_PREFIXES = ("claude-sonnet-5", "claude-sonnet5", "sonnet-5")


def _is_sonnet5(model: str) -> bool:
    return any(model.startswith(p) for p in _SONNET5_PREFIXES) or "sonnet-5" in model


def _messages_to_anthropic(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    """将 Message 列表转换为 Anthropic Messages API 格式。
    Returns (system_prompt, api_messages) — Anthropic 的 system 是顶层字段。
    """
    system_parts: list[str] = []
    api_messages: list[dict[str, Any]] = []

    for m in messages:
        if m.role == MessageRole.SYSTEM:
            system_parts.append(m.content)
            continue

        entry: dict[str, Any] = {"role": _ROLE_MAP[m.role], "content": m.content}
        if m.tool_calls:
            # 将 tool_calls 转成 Anthropic tool_use content blocks
            content_blocks: list[dict[str, Any]] = []
            if m.content:
                content_blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": json.loads(tc.arguments),
                    }
                )
            entry["content"] = content_blocks

        if m.role == MessageRole.TOOL and m.tool_call_id:
            entry["content"] = [
                {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": m.content,
                }
            ]
            del entry["role"]
        api_messages.append(entry)

    system_prompt = "\n".join(system_parts) if system_parts else None
    return system_prompt, api_messages


_ROLE_MAP: dict[MessageRole, str] = {
    MessageRole.USER: "user",
    MessageRole.ASSISTANT: "assistant",
    MessageRole.TOOL: "user",  # Anthropic 用 user 角色承载 tool_result
}


def _tools_to_anthropic(tools: list[Tool] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    result: list[dict[str, Any]] = []
    for t in tools:
        fn = t.function
        props = fn.parameters
        result.append(
            {
                "name": fn.name,
                "description": fn.description,
                "input_schema": {
                    "type": "object",
                    "properties": {k: v.as_schema() for k, v in props.items()},
                    "required": fn.required or [k for k, v in props.items() if v.required],
                },
            }
        )
    return result


def _parse_anthropic_tool_calls(content_blocks: list[dict[str, Any]]) -> list[ToolCall]:
    """从 Anthropic content 中提取 tool_use blocks。"""
    result: list[ToolCall] = []
    for block in content_blocks:
        if block.get("type") == "tool_use":
            result.append(
                ToolCall(
                    id=block["id"],
                    name=block["name"],
                    arguments=json.dumps(block.get("input", {})),
                )
            )
    return result


def _parse_text_content(content_blocks: list[dict[str, Any]]) -> str:
    """提取 text content blocks 中的文本。"""
    texts: list[str] = []
    for block in content_blocks:
        if block.get("type") == "text":
            texts.append(block.get("text", ""))
    return "".join(texts)


def _build_result(data: dict[str, Any], model: str) -> CompletionResult:
    content = data.get("content", [])
    if isinstance(content, str):
        text = content
        tool_calls = None
    else:
        text = _parse_text_content(content)
        tool_calls = _parse_anthropic_tool_calls(content)
        if not tool_calls:
            tool_calls = None

    choice = CompletionChoice(
        index=0,
        message=Message(role=MessageRole.ASSISTANT, content=text, tool_calls=tool_calls),
        finish_reason=data.get("stop_reason", "end_turn"),
    )
    usage_data = data.get("usage", {})
    tokens = CompletionUsage(
        prompt_tokens=usage_data.get("input_tokens", 0),
        completion_tokens=usage_data.get("output_tokens", 0),
        total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
    )
    if model in _PRICING:
        in_price, out_price = _PRICING[model]
        tokens.cost_usd = round(
            tokens.prompt_tokens / 1_000_000 * in_price
            + tokens.completion_tokens / 1_000_000 * out_price,
            6,
        )
    return CompletionResult(
        id=data.get("id", ""),
        model=model,
        choices=[choice],
        usage=tokens,
    )


class AnthropicProvider(LLMProvider):
    """Anthropic Claude Provider — 纯 httpx 实现，零 SDK 依赖。"""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str = "",
        base_url: str = "",
        timeout: float = 120.0,
    ):
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or ANTHROPIC_API_BASE,
        )
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _build_body(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        top_p: float,
        stop: list[str] | None,
        tools: list[Tool] | None,
        tool_choice: str,
    ) -> dict[str, Any]:
        system, api_messages = _messages_to_anthropic(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            body["system"] = system
        if top_p < 1.0:
            body["top_p"] = top_p
        if stop:
            body["stop_sequences"] = stop
        if tools:
            body["tools"] = _tools_to_anthropic(tools)
            if tool_choice == "any":
                body["tool_choice"] = {"type": "any"}
            elif tool_choice == "auto":
                body["tool_choice"] = {"type": "auto"}
        return body

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
        url = f"{self.base_url}/v1/messages"
        body = self._build_body(messages, temperature, max_tokens, top_p, stop, tools, tool_choice)
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            return _build_result(resp.json(), self.model)

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
        url = f"{self.base_url}/v1/messages"
        body = self._build_body(messages, temperature, max_tokens, top_p, stop, tools, tool_choice)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            return _build_result(resp.json(), self.model)

    def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        url = f"{self.base_url}/v1/messages"
        body = self._build_body(messages, temperature, max_tokens, 1.0, None, tools, "auto")
        body["stream"] = True
        with httpx.Client(timeout=self._timeout) as client:
            with client.stream("POST", url, headers=self._headers(), json=body) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        text = delta.get("text", "")
                        if text:
                            yield StreamChunk(content=text)
                    elif event.get("type") == "message_stop":
                        yield StreamChunk(finish_reason="end_turn")

    async def astream(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ):
        url = f"{self.base_url}/v1/messages"
        body = self._build_body(messages, temperature, max_tokens, 1.0, None, tools, "auto")
        body["stream"] = True
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", url, headers=self._headers(), json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        text = delta.get("text", "")
                        if text:
                            yield StreamChunk(content=text)
                    elif event.get("type") == "message_stop":
                        yield StreamChunk(finish_reason="end_turn")
