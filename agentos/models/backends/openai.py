"""OpenAI backend for AgentOS.

Supports OpenAI, Azure OpenAI, and any OpenAI-compatible API (DeepSeek, Groq, etc.).
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

import os


@dataclass
class OpenAIConfig:
    """Configuration for OpenAI backend."""
    api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout: int = 60
    max_retries: int = 3
    organization: str = ""


class OpenAIClient:
    """OpenAI-compatible LLM client.

    Works with:
    - OpenAI (GPT-4o, GPT-4, GPT-3.5)
    - Azure OpenAI
    - DeepSeek
    - Groq
    - Together AI
    - Any OpenAI-compatible endpoint
    """

    def __init__(self, config: Optional[OpenAIConfig] = None):
        self.config = config or OpenAIConfig()
        self._client = None
        self._async_client = None

    @property
    def headers(self) -> Dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        if self.config.organization:
            h["OpenAI-Organization"] = self.config.organization
        return h

    @property
    def _chat_url(self) -> str:
        return f"{self.config.base_url}/chat/completions"

    async def _async_request(self, messages: List[Dict], **kwargs) -> Dict:
        import httpx

        timeout = httpx.Timeout(self.config.timeout)
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "frequency_penalty": self.config.frequency_penalty,
            "presence_penalty": self.config.presence_penalty,
        }

        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
            payload["tool_choice"] = kwargs.get("tool_choice", "auto")

        if kwargs.get("response_format"):
            payload["response_format"] = kwargs["response_format"]

        for attempt in range(self.config.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        self._chat_url,
                        json=payload,
                        headers=self.headers,
                        timeout=timeout,
                    )
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == self.config.max_retries - 1:
                    raise
                if e.response.status_code >= 500:
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

        Args:
            messages: List of message dicts with 'role' and 'content'.
            system: Optional system prompt.
            **kwargs: Override config parameters.

        Returns:
            Response dict with 'content', 'role', 'usage', 'model'.
        """
        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        result = await self._async_request(msgs, **kwargs)
        choice = result["choices"][0]
        message = choice.get("message", {})

        tool_calls = message.get("tool_calls", [])

        return {
            "content": message.get("content", ""),
            "role": message.get("role", "assistant"),
            "usage": result.get("usage", {}),
            "model": result.get("model", self.config.model),
            "finish_reason": choice.get("finish_reason", ""),
            "tool_calls": [
                {
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", "{}"),
                }
                for tc in tool_calls
            ],
        }

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion tokens.

        Yields dicts with 'delta', 'finish_reason', 'tool_call_delta'.
        """
        import httpx

        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        payload = {
            "model": self.config.model,
            "messages": msgs,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "stream": True,
        }

        timeout = httpx.Timeout(self.config.timeout * 2)
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self._chat_url,
                json=payload,
                headers=self.headers,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        import json
                        try:
                            chunk = json.loads(data)
                            choice = chunk["choices"][0]
                            delta = choice.get("delta", {})
                            yield {
                                "delta": delta.get("content", ""),
                                "finish_reason": choice.get("finish_reason"),
                                "tool_call_delta": delta.get("tool_calls"),
                            }
                        except (json.JSONDecodeError, KeyError):
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
