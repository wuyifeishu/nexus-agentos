"""Ollama backend for AgentOS.

Supports local LLM inference via Ollama.
Models: llama3, mistral, codellama, phi3, gemma2, deepseek-r1, etc.
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


@dataclass
class OllamaConfig:
    """Configuration for Ollama backend."""
    base_url: str = "http://localhost:11434"
    model: str = "llama3"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    top_k: int = 40
    num_ctx: int = 8192
    timeout: int = 120
    max_retries: int = 3
    keep_alive: str = "5m"


class OllamaClient:
    """Ollama LLM client for local model inference.

    Supports:
    - Chat completions (streaming and non-streaming)
    - Tool calling (function calling)
    - Model listing and management
    - Custom system prompts
    """

    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()

    @property
    def _generate_url(self) -> str:
        return f"{self.config.base_url}/api/chat"

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        msgs = messages.copy()
        if system:
            msgs.insert(0, {"role": "system", "content": system})

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "messages": msgs,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.config.temperature),
                "num_predict": kwargs.get("max_tokens", self.config.max_tokens),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "top_k": self.config.top_k,
                "num_ctx": self.config.num_ctx,
            },
        }

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
                        self._generate_url,
                        json=payload,
                        timeout=timeout,
                    )
                    resp.raise_for_status()
                    return resp.json()
            except (httpx.HTTPStatusError, httpx.ConnectError) as e:
                if attempt == self.config.max_retries - 1:
                    raise
                import asyncio
                await asyncio.sleep(2 ** attempt)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Send a chat completion request.

        Returns dict with 'content', 'role', 'usage', 'model'.
        """
        payload = self._build_payload(messages, system, **kwargs)
        result = await self._async_request(payload)

        message = result.get("message", {})
        tool_calls = []
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", "{}"),
                })

        return {
            "content": message.get("content", ""),
            "role": "assistant",
            "usage": {
                "input_tokens": result.get("prompt_eval_count", 0),
                "output_tokens": result.get("eval_count", 0),
                "total_duration_ms": result.get("total_duration", 0),
            },
            "model": result.get("model", self.config.model),
            "done_reason": result.get("done_reason", ""),
            "tool_calls": tool_calls,
        }

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion tokens."""
        payload = self._build_payload(messages, system, **kwargs)
        payload["stream"] = True

        import httpx

        timeout = httpx.Timeout(self.config.timeout * 2)
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self._generate_url,
                json=payload,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    import json
                    try:
                        event = json.loads(line)
                        message = event.get("message", {})
                        yield {
                            "delta": message.get("content", ""),
                            "done": event.get("done", False),
                            "model": event.get("model", self.config.model),
                        }
                        if event.get("done"):
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

    async def list_models(self) -> List[Dict[str, Any]]:
        """List locally available Ollama models."""
        import httpx

        timeout = httpx.Timeout(self.config.timeout)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.config.base_url}/api/tags",
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "modified": m.get("modified_at", ""),
                    "format": m.get("details", {}).get("format", ""),
                }
                for m in data.get("models", [])
            ]

    async def pull_model(self, model_name: str) -> AsyncIterator[Dict[str, Any]]:
        """Pull a model from Ollama registry."""
        import httpx

        timeout = httpx.Timeout(600)  # 10 min for downloads
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.config.base_url}/api/pull",
                json={"name": model_name, "stream": True},
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    import json
                    try:
                        event = json.loads(line)
                        yield event
                    except json.JSONDecodeError:
                        continue
