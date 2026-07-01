"""
AgentOS v0.70 — Google Gemini Provider 全集成。
基因来源: Google AI Studio SDK + Vertex AI
支持: Gemini 2.5 Pro/Flash、Vision、System Instruction、Streaming、Token Counting、Safety Settings。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from agentos.models.router import ModelResponse, ModelSpec
from agentos.core.context import AgentContext
from agentos.tools.base import ToolCall


# ── Gemini Public API Endpoint ──────────────────
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Prebuilt Gemini model specs
GEMINI_MODELS: dict[str, ModelSpec] = {
    "gemini-2.5-pro": ModelSpec(
        provider="gemini",
        model_id="gemini-2.5-pro-exp-03-25",
        context_window=1_048_576,
        cost_per_1m_input=1.25,
        cost_per_1m_output=10.00,
    ),
    "gemini-2.5-flash": ModelSpec(
        provider="gemini",
        model_id="gemini-2.5-flash-preview-04-17",
        context_window=1_048_576,
        cost_per_1m_input=0.15,
        cost_per_1m_output=0.60,
    ),
    "gemini-2.0-flash": ModelSpec(
        provider="gemini",
        model_id="gemini-2.0-flash",
        context_window=1_048_576,
        cost_per_1m_input=0.10,
        cost_per_1m_output=0.40,
    ),
}


@dataclass
class GeminiSafetySetting:
    """安全过滤配置。"""

    category: str  # HARM_CATEGORY_HARASSMENT | HATE_SPEECH | SEXUALLY_EXPLICIT | DANGEROUS_CONTENT
    threshold: str = "BLOCK_ONLY_HIGH"  # BLOCK_NONE | BLOCK_ONLY_HIGH | BLOCK_MEDIUM_AND_ABOVE | BLOCK_LOW_AND_ABOVE


@dataclass
class GeminiConfig:
    """Gemini调用配置。"""

    api_key: str = ""
    temperature: float = 0.7
    top_p: float = 0.95
    top_k: int = 40
    max_output_tokens: int = 8192
    safety_settings: list[GeminiSafetySetting] = field(default_factory=lambda: [
        GeminiSafetySetting("HARM_CATEGORY_HARASSMENT", "BLOCK_ONLY_HIGH"),
        GeminiSafetySetting("HARM_CATEGORY_HATE_SPEECH", "BLOCK_ONLY_HIGH"),
        GeminiSafetySetting("HARM_CATEGORY_SEXUALLY_EXPLICIT", "BLOCK_ONLY_HIGH"),
        GeminiSafetySetting("HARM_CATEGORY_DANGEROUS_CONTENT", "BLOCK_ONLY_HIGH"),
    ])


# ── Tool Declaration Helpers ─────────────────────

def _convert_tools_to_gemini(openai_tools: list[dict]) -> list[dict]:
    """将OpenAI格式的tools转换为Gemini functionDeclarations。"""
    declarations = []
    for tool in openai_tools:
        if tool.get("type") != "function":
            continue
        func = tool.get("function", {})
        declarations.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "parameters": func.get("parameters", {}),
        })
    return [{"function_declarations": declarations}] if declarations else []


def _convert_gemini_tool_calls(parts: list[dict]) -> list[ToolCall]:
    """将Gemini functionCall parts转为ToolCall列表。"""
    tool_calls = []
    for part in parts:
        fc = part.get("functionCall")
        if not fc:
            continue
        args = fc.get("args", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        tool_calls.append(ToolCall(
            id=fc.get("name", "unknown"),
            name=fc.get("name", "unknown"),
            arguments=args,
        ))
    return tool_calls


# ── Core Gemini Client ───────────────────────────

class GeminiClient:
    """
    Google Gemini API 客户端。
    支持: chat/completions、Vision多模态、Streaming、System Instruction。
    """

    def __init__(
        self,
        config: GeminiConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.config = config or GeminiConfig()
        self._http = http_client or httpx.AsyncClient(timeout=180)
        self._owned_http = http_client is None

    @property
    def api_key(self) -> str:
        return self.config.api_key or os.environ.get("GEMINI_API_KEY", "")

    async def close(self):
        if self._owned_http:
            await self._http.aclose()

    async def call(
        self,
        spec: ModelSpec,
        context: AgentContext,
    ) -> ModelResponse:
        """同步调用Gemini API。"""
        contents, system_instruction = self._build_gemini_contents(context)
        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.config.temperature,
                "topP": self.config.top_p,
                "topK": self.config.top_k,
                "maxOutputTokens": self.config.max_output_tokens,
            },
            "safetySettings": [
                {"category": s.category, "threshold": s.threshold}
                for s in self.config.safety_settings
            ],
        }
        if system_instruction:
            body["systemInstruction"] = system_instruction

        if context.tools:
            body["tools"] = _convert_tools_to_gemini(context.tools)

        url = f"{GEMINI_API_BASE}/models/{spec.model_id}:generateContent?key={self.api_key}"
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

        return self._parse_response(data)

    async def call_stream(
        self,
        spec: ModelSpec,
        context: AgentContext,
    ) -> AsyncIterator[dict]:
        """流式调用Gemini API，逐个yield chunk。"""
        contents, system_instruction = self._build_gemini_contents(context)
        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.config.temperature,
                "topP": self.config.top_p,
                "topK": self.config.top_k,
                "maxOutputTokens": self.config.max_output_tokens,
            },
            "safetySettings": [
                {"category": s.category, "threshold": s.threshold}
                for s in self.config.safety_settings
            ],
        }
        if system_instruction:
            body["systemInstruction"] = system_instruction

        url = f"{GEMINI_API_BASE}/models/{spec.model_id}:streamGenerateContent?alt=sse&key={self.api_key}"
        async with self._http.stream("POST", url, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                # skip safety / promptFeedback
                if "candidates" not in chunk:
                    continue
                yield chunk

    async def call_with_image(
        self,
        spec: ModelSpec,
        prompt: str,
        image_data: bytes,
        mime_type: str = "image/jpeg",
    ) -> ModelResponse:
        """Vision多模态调用。image_data为base64之前的内容。"""
        import base64
        b64 = base64.b64encode(image_data).decode()
        contents = [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": mime_type, "data": b64}},
            ],
        }]
        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_output_tokens,
            },
        }
        url = f"{GEMINI_API_BASE}/models/{spec.model_id}:generateContent?key={self.api_key}"
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        return self._parse_response(resp.json())

    async def count_tokens(self, spec: ModelSpec, context: AgentContext) -> dict:
        """使用Gemini API统计输入/输出token数。"""
        contents, _ = self._build_gemini_contents(context)
        url = f"{GEMINI_API_BASE}/models/{spec.model_id}:countTokens?key={self.api_key}"
        resp = await self._http.post(url, json={"contents": contents})
        resp.raise_for_status()
        data = resp.json()
        return {
            "total_tokens": data.get("totalTokens", 0),
            "prompt_tokens": data.get("totalTokens", 0),  # Gemini不区分输入输出
            "model": spec.model_id,
        }

    # ── Internal helpers ──────────────────────────

    def _build_gemini_contents(self, context: AgentContext) -> tuple[list[dict], dict | None]:
        """将AgentContext转为Gemini contents格式。"""
        contents = []
        system_instruction = None

        for msg in context.messages:
            role = self._map_role(msg.role)
            parts = []

            # system prompt → systemInstruction
            if msg.role == "system":
                system_instruction = {"parts": [{"text": msg.content}]}
                continue

            # text content
            if msg.content:
                parts.append({"text": msg.content})

            # tool calls from assistant
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    parts.append({
                        "functionCall": {
                            "name": tc.name,
                            "args": tc.arguments,
                        }
                    })

            # tool results
            if msg.role == "tool" and msg.tool_call_id:
                # Gemini uses functionResponse in user role
                parts.append({
                    "functionResponse": {
                        "name": msg.tool_call_id,
                        "response": {"content": msg.content},
                    }
                })

            if parts:
                contents.append({"role": role, "parts": parts})

        # Ensure there's at least a user message
        if not contents:
            contents = [{"role": "user", "parts": [{"text": context.current_task or ""}]}]

        return contents, system_instruction

    def _map_role(self, role: str) -> str:
        mapping = {
            "user": "user",
            "assistant": "model",
            "system": "user",  # handled separately via systemInstruction
            "tool": "user",    # functionResponse must be in user turn
        }
        return mapping.get(role, "user")

    def _parse_response(self, data: dict) -> ModelResponse:
        """解析Gemini API响应为ModelResponse。"""
        candidates = data.get("candidates", [])
        if not candidates:
            # Safety blocked
            block_reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
            return ModelResponse(content=f"[SAFETY_BLOCKED] {block_reason}")

        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        text_parts = []
        tool_calls = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            if "functionCall" in part:
                fc = part["functionCall"]
                args = fc.get("args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    id=fc.get("name", "unknown"),
                    name=fc.get("name", "unknown"),
                    arguments=args,
                ))

        return ModelResponse(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
        )
