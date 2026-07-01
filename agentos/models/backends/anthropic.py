"""Anthropic Claude backend for AgentOS.

Supports Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku.
Uses Anthropic Messages API.
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

import os


@dataclass
class ClaudeConfig:
    """Configuration for Anthropic Claude backend."""
    api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    base_url: str = "https://api.anthropic.com/v1"
    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    top_k: int = -1
    timeout: int = 90
    max_retries: int = 3
    anthropic_version: str = "2023-06-01"


class ClaudeClient:
    """Anthropic Claude LLM client.

    Supports:
    - Claude Opus 4 / Claude Sonnet 4 / Claude Haiku 3.5
    - Streaming and non-streaming
    - Tool use (function calling)
    - System prompts
    """

    def __init__(self, config: Optional[ClaudeConfig] = None):
        self.config = config or ClaudeConfig()

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.config.anthropic_version,
            "content-type": "application/json",
        }

    @property
    def _messages_url(self) -> str:
        return f"{self.config.base_url}/messages"

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "messages": messages,
        }

        if system:
            payload["system"] = system

        temp = kwargs.get("temperature", self.config.temperature)
        if temp > 0:
            payload["temperature"] = temp

        if kwargs.get("top_p", self.config.top_p) < 1.0:
            payload["top_p"] = kwargs.get("top_p", self.config.top_p)

        if self.config.top_k > 0:
            payload["top_k"] = self.config.top_k

        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]

        return payload

    async def _async_request(self, payload: Dict) -> Dict:
        import httpx

        timeout = httpx.Timeout(self.config.timeout)
        for attempt in range(self.config.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        self._messages_url,
                        json=payload,
                        headers=self._headers,
                        timeout=timeout,
                    )
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == self.config.max_retries - 1:
                    raise
                if e.response.status_code >= 500 or e.response.status_code == 429:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Send a chat completion request.

        Messages format: [{"role": "user", "content": "..."}, ...]
        Return format: {"content": str, "role": str, "usage": dict, "model": str}
        """
        payload = self._build_payload(messages, system, **kwargs)
        result = await self._async_request(payload)

        content_blocks = result.get("content", [])
        text_content = ""
        tool_calls = []

        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": block.get("input", {}),
                })

        usage = result.get("usage", {})
        return {
            "content": text_content,
            "role": "assistant",
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
            "model": result.get("model", self.config.model),
            "stop_reason": result.get("stop_reason", ""),
            "tool_calls": tool_calls,
        }

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion events."""
        payload = self._build_payload(messages, system, **kwargs)
        payload["stream"] = True

        import httpx

        timeout = httpx.Timeout(self.config.timeout * 2)
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self._messages_url,
                json=payload,
                headers=self._headers,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        import json
                        try:
                            event = json.loads(data)
                            event_type = event.get("type", "")
                            if event_type == "content_block_delta":
                                delta = event.get("delta", {})
                                yield {
                                    "delta": delta.get("text", ""),
                                    "type": delta.get("type", "text"),
                                }
                            elif event_type == "message_stop":
                                yield {"delta": "", "finish_reason": "stop"}
                                break
                            elif event_type == "error":
                                yield {"error": event.get("error", {}).get("message", "")}
                                break
                        except json.JSONDecodeError:
                            continue

    def sync_chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Synchronous chat completion."""
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.chat(messages, system, **kwargs))
        finally:
            loop.close()
