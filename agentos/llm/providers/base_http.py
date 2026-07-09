"""Base HTTP-based LLM Provider with shared OpenAI-compatible API logic."""

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


class BaseHttpProvider(LLMProvider):
    """OpenAI-compatible HTTP API provider base class.

    Subclasses override: provider_name, API_URL, _api_key_env, _default_model
    """

    API_URL: str = ""
    _api_key_env: str = ""
    _default_model: str = ""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        super().__init__(model=model or self._default_model)
        self._api_key = api_key or os.getenv(self._api_key_env, "")

    # ── Message conversion ──

    @staticmethod
    def _messages_to_api(messages: list[Message]) -> list[dict]:
        api_msgs = []
        for m in messages:
            entry: dict = {"role": m.role.value}
            if m.content:
                entry["content"] = m.content
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type if hasattr(tc, "type") else "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in m.tool_calls
                ]
            if m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
                entry["content"] = m.content or ""
            api_msgs.append(entry)
        return api_msgs

    @staticmethod
    def _tools_to_api(tools: list[Tool]) -> list[dict]:
        return [t.as_schema() for t in tools]

    # ── API call ──

    def _call_api(
        self, messages: list[Message], tools: list[Tool] | None = None, temperature: float = 0.7
    ) -> CompletionResult:
        body: dict = {
            "model": self.model,
            "messages": self._messages_to_api(messages),
            "stream": False,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = self._tools_to_api(tools)

        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choice = data["choices"][0]
        msg = choice["message"]

        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=tc["function"]["arguments"],
                )
                for tc in msg["tool_calls"]
            ]

        return CompletionResult(
            id=data.get("id", ""),
            model=data.get("model", self.model),
            choices=[
                CompletionChoice(
                    index=0,
                    message=Message(
                        role=MessageRole.ASSISTANT,
                        content=msg.get("content", ""),
                        tool_calls=tool_calls,
                    ),
                    finish_reason=choice.get("finish_reason", "stop"),
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
                total_tokens=data.get("usage", {}).get("total_tokens", 0),
            ),
        )

    # ── Interface ──

    def chat(self, messages: list[Message], **kwargs) -> CompletionResult:
        tools = kwargs.get("tools")
        temperature = kwargs.get("temperature", 0.7)
        return self._call_api(messages, tools=tools, temperature=temperature)

    async def achat(self, messages: list[Message], **kwargs) -> CompletionResult:
        return self.chat(messages, **kwargs)
