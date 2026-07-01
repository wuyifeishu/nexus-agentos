"""
AgentOS v1.14.0 — MCP Sampling 支持。

MCP Sampling 允许 MCP Server 向 Client 发起 LLM 请求。
这是 MCP 协议中 server→client 方向的核心能力，对标 Claude Desktop 的采样功能。

协议流程:
1. Server 发送 `sampling/createMessage` 请求到 Client
2. Client 调用 LLM 生成回复
3. Client 返回结果给 Server
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union


# ── Sampling Data Models ────────────────────


class SamplingRole(str, Enum):
    """Sampling 消息角色。"""
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class SamplingContentBlock:
    """Sampling 内容块。

    支持 text 和 image 两种类型。
    """

    type: str = "text"  # text | image
    text: str = ""
    data: str = ""       # base64 image data
    mime_type: str = ""

    def to_dict(self) -> dict:
        d: dict = {"type": self.type}
        if self.type == "text":
            d["text"] = self.text
        elif self.type == "image":
            d["data"] = self.data
            d["mimeType"] = self.mime_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SamplingContentBlock":
        return cls(
            type=d.get("type", "text"),
            text=d.get("text", ""),
            data=d.get("data", ""),
            mime_type=d.get("mimeType", ""),
        )

    @classmethod
    def text_block(cls, text: str) -> "SamplingContentBlock":
        return cls(type="text", text=text)

    @classmethod
    def image_block(cls, base64_data: str, mime_type: str = "image/png") -> "SamplingContentBlock":
        return cls(type="image", data=base64_data, mime_type=mime_type)


@dataclass
class SamplingMessage:
    """Sampling 消息。"""
    role: SamplingRole
    content: Union[str, List[SamplingContentBlock]]

    def to_dict(self) -> dict:
        if isinstance(self.content, str):
            return {
                "role": self.role.value,
                "content": {"type": "text", "text": self.content},
            }
        return {
            "role": self.role.value,
            "content": [c.to_dict() for c in self.content],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SamplingMessage":
        role = SamplingRole(d["role"])
        content_raw = d["content"]
        if isinstance(content_raw, str):
            content = content_raw
        elif isinstance(content_raw, dict):
            content = [SamplingContentBlock.from_dict(content_raw)]
        elif isinstance(content_raw, list):
            content = [SamplingContentBlock.from_dict(c) for c in content_raw]
        else:
            content = str(content_raw)
        return cls(role=role, content=content)


@dataclass
class SamplingRequest:
    """Server 发起的 Sampling 请求。

    符合 MCP sampling/createMessage 规范。
    """

    messages: List[SamplingMessage]
    model_preferences: Optional[Dict[str, Any]] = None
    system_prompt: str = ""
    include_context: str = "none"  # none | thisServer | allServers
    temperature: float = 0.7
    max_tokens: int = 4096
    stop_sequences: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {
            "messages": [m.to_dict() for m in self.messages],
            "maxTokens": self.max_tokens,
        }
        if self.model_preferences:
            d["modelPreferences"] = self.model_preferences
        if self.system_prompt:
            d["systemPrompt"] = self.system_prompt
        if self.include_context != "none":
            d["includeContext"] = self.include_context
        if self.temperature != 0.7:
            d["temperature"] = self.temperature
        if self.stop_sequences:
            d["stopSequences"] = self.stop_sequences
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SamplingRequest":
        return cls(
            messages=[SamplingMessage.from_dict(m) for m in d.get("messages", [])],
            model_preferences=d.get("modelPreferences"),
            system_prompt=d.get("systemPrompt", ""),
            include_context=d.get("includeContext", "none"),
            temperature=d.get("temperature", 0.7),
            max_tokens=d.get("maxTokens", 4096),
            stop_sequences=d.get("stopSequences", []),
            metadata=d.get("metadata", {}),
        )


@dataclass
class SamplingResponse:
    """Sampling 响应。

    Client 调用 LLM 后返回给 Server 的结果。
    """

    model: str = ""
    role: SamplingRole = SamplingRole.ASSISTANT
    content: Union[str, List[SamplingContentBlock]] = ""
    stop_reason: str = ""  # endTurn | stopSequence | maxTokens
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        content_block: dict
        if isinstance(self.content, str):
            content_block = {"type": "text", "text": self.content}
        elif isinstance(self.content, list):
            content_block = [c.to_dict() for c in self.content]
        else:
            content_block = {"type": "text", "text": str(self.content)}

        return {
            "model": self.model,
            "role": self.role.value,
            "content": content_block,
            "stopReason": self.stop_reason or "endTurn",
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SamplingResponse":
        content_raw = d.get("content", "")
        if isinstance(content_raw, str):
            content = content_raw
        elif isinstance(content_raw, dict):
            content = [SamplingContentBlock.from_dict(content_raw)]
        elif isinstance(content_raw, list):
            content = [SamplingContentBlock.from_dict(c) for c in content_raw]
        else:
            content = str(content_raw)
        return cls(
            model=d.get("model", ""),
            role=SamplingRole(d.get("role", "assistant")),
            content=content,
            stop_reason=d.get("stopReason", ""),
        )


# ── Sampling Handler ────────────────────────


class SamplingError(Exception):
    """Sampling 错误。"""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Sampling Error [{code}]: {message}")


# LLM 调用接口
LLMCallFn = Callable[
    [SamplingRequest],
    Coroutine[Any, Any, SamplingResponse],
]


class MCPClientSampling:
    """MCP Client 端 Sampling 支持。

    在 MCPClient 上挂载此 handler 后，MCP Server 可通过
    `sampling/createMessage` 向 Client 发起 LLM 请求。

    Usage:
        client = MCPClient()
        sampling = MCPClientSampling(my_llm_call_fn)
        client.set_sampling_handler(sampling)
    """

    def __init__(
        self,
        llm_call_fn: LLMCallFn,
        default_model: str = "claude-sonnet-4-20250514",
        max_tokens_limit: int = 8192,
        allow_image_input: bool = True,
    ):
        self._llm_call = llm_call_fn
        self.default_model = default_model
        self.max_tokens_limit = max_tokens_limit
        self.allow_image_input = allow_image_input

    async def handle_create_message(
        self,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """处理 sampling/createMessage 请求。

        Args:
            params: MCP 请求参数

        Returns:
            MCP JSON-RPC 响应 result 部分
        """
        try:
            request = SamplingRequest.from_dict(params)
        except Exception as e:
            raise SamplingError(-32602, f"Invalid sampling request: {e}")

        # Validate max_tokens
        if request.max_tokens > self.max_tokens_limit:
            request.max_tokens = self.max_tokens_limit

        # Validate image input
        if not self.allow_image_input:
            for msg in request.messages:
                if isinstance(msg.content, list):
                    has_image = any(
                        c.type == "image" for c in msg.content
                    )
                    if has_image:
                        raise SamplingError(
                            -32000,
                            "Image input is not allowed by client policy",
                        )

        try:
            response = await self._llm_call(request)
        except Exception as e:
            raise SamplingError(-32001, f"LLM call failed: {e}")

        return {
            "model": response.model or self.default_model,
            "role": response.role.value,
            "content": response.to_dict()["content"],
            "stopReason": response.stop_reason or "endTurn",
        }


# ── Mock LLM for Testing ───────────────────


async def mock_llm_call(request: SamplingRequest) -> SamplingResponse:
    """Mock LLM 调用函数（用于测试）。

    简单回显最后一条用户消息的内容。
    """
    last_msg = request.messages[-1] if request.messages else None
    if last_msg and isinstance(last_msg.content, str):
        content = f"[Mock] Echo: {last_msg.content[:100]}"
    elif last_msg and isinstance(last_msg.content, list):
        text_parts = [c.text for c in last_msg.content if c.type == "text"]
        content = f"[Mock] Echo: {' '.join(text_parts)[:100]}"
    else:
        content = "[Mock] No input messages."

    return SamplingResponse(
        model="mock-model",
        content=content,
        stop_reason="endTurn",
    )


# ── Resource Templates ──────────────────────


@dataclass
class MCPResourceTemplate:
    """MCP Resource Template（URI 模板）。

    Server 可暴露参数化的资源模板，Client 可按模板实例化资源。
    """

    uri_template: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    annotations: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {
            "uriTemplate": self.uri_template,
            "name": self.name,
        }
        if self.description:
            d["description"] = self.description
        if self.mime_type:
            d["mimeType"] = self.mime_type
        if self.annotations:
            d["annotations"] = self.annotations
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MCPResourceTemplate":
        return cls(
            uri_template=d.get("uriTemplate", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            mime_type=d.get("mimeType", ""),
            annotations=d.get("annotations", {}),
        )


# ── MCP Logging ────────────────────────────


class MCPLogLevel(str, Enum):
    """MCP 日志级别。"""
    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    ALERT = "alert"
    EMERGENCY = "emergency"


class MCPLoggingHandler:
    """MCP Client 端日志接收处理。

    Client 可通过 `logging/setLevel` 设置日志级别，
    Server 通过 `notifications/message` 推送日志消息。
    """

    def __init__(self, max_level: MCPLogLevel = MCPLogLevel.INFO):
        self._max_level = max_level
        self._log_callback: Optional[Callable[[MCPLogLevel, str, str], None]] = None

    def set_log_callback(
        self,
        callback: Callable[[MCPLogLevel, str, str], None],
    ) -> None:
        """设置日志回调函数。

        Args:
            callback: fn(level, logger_name, message)
        """
        self._log_callback = callback

    @property
    def max_level(self) -> MCPLogLevel:
        return self._max_level

    def set_level(self, level: MCPLogLevel) -> None:
        """Client 设置日志级别。"""
        self._max_level = level

    def _level_rank(self, level: MCPLogLevel) -> int:
        levels = list(MCPLogLevel)
        return levels.index(level)

    def should_log(self, level: MCPLogLevel) -> bool:
        """判断给定级别的日志是否应被记录。"""
        return self._level_rank(level) >= self._level_rank(self._max_level)

    def handle_log_message(
        self,
        level: MCPLogLevel,
        logger_name: str,
        message: str,
    ) -> None:
        """处理来自 Server 的日志消息。"""
        if self.should_log(level) and self._log_callback:
            self._log_callback(level, logger_name, message)


# ── MCP Roots ──────────────────────────────


@dataclass
class MCPRoot:
    """MCP Root — Client 暴露给 Server 的可访问文件系统根。"""
    uri: str
    name: str = ""

    def to_dict(self) -> dict:
        d: dict = {"uri": self.uri}
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MCPRoot":
        return cls(uri=d.get("uri", ""), name=d.get("name", ""))
