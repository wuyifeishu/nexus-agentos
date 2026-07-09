"""Anthropic Claude API Provider."""

from __future__ import annotations

import json
import os
import urllib.request

from agentos.llm.base import (
    CompletionChoice,
    CompletionResult,
    CompletionUsage,
    LLMProvider,
    Message,
    MessageRole,
    Tool,
    ToolCall,
)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider.

    Requires: ANTHROPIC_API_KEY env var.
    """

    provider_name = "anthropic"
    API_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        super().__init__(model=model or "claude-3-5-sonnet-20241022")
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")

    def _messages_to_anthropic(self, messages: list[Message]) -> tuple[list[dict], str | None]:
        """Convert to Anthropic format. Returns (messages, system_prompt)."""
        system = None
        result = []
        for m in messages:
            if m.role == MessageRole.SYSTEM:
                system = m.content
                continue
            entry: dict = {"role": m.role.value}
            if m.content:
                entry["content"] = [{"type": "text", "text": m.content}]
            if m.tool_calls:
                # Anthropic: assistant content with tool_use blocks
                content_blocks = []
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
            if m.tool_call_id:
                entry["role"] = "user"
                entry["content"] = [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id,
                        "content": m.content or "",
                    }
                ]
            result.append(entry)
        return result, system

    def _tools_to_anthropic(self, tools: list[Tool]) -> list[dict]:
        result = []
        for t in tools:
            schema = t.as_schema()
            result.append(
                {
                    "name": schema["function"]["name"],
                    "description": schema["function"]["description"],
                    "input_schema": schema["function"]["parameters"],
                }
            )
        return result

    def chat(self, messages: list[Message], **kwargs) -> CompletionResult:
        tools_param = kwargs.get("tools", [])
        api_messages, system = self._messages_to_anthropic(messages)

        body: dict = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": 4096,
            "stream": False,
        }
        if system:
            body["system"] = system
        if tools_param:
            body["tools"] = self._tools_to_anthropic(tools_param)

        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": self.ANTHROPIC_VERSION,
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Parse response
        content_blocks = data.get("content", [])
        text_content = ""
        tool_calls = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=json.dumps(block.get("input", {})),
                    )
                )

        return CompletionResult(
            id=data.get("id", ""),
            model=data.get("model", self.model),
            choices=[
                CompletionChoice(
                    index=0,
                    message=Message(
                        role=MessageRole.ASSISTANT,
                        content=text_content,
                        tool_calls=tool_calls if tool_calls else None,
                    ),
                    finish_reason=data.get("stop_reason", "end_turn"),
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=data.get("usage", {}).get("input_tokens", 0),
                completion_tokens=data.get("usage", {}).get("output_tokens", 0),
                total_tokens=(
                    data.get("usage", {}).get("input_tokens", 0)
                    + data.get("usage", {}).get("output_tokens", 0)
                ),
            ),
        )

    async def achat(self, messages: list[Message], **kwargs) -> CompletionResult:
        return self.chat(messages, **kwargs)
