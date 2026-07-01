"""
LLM Provider 抽象层。
为 Nexus AgentOS 提供统一的 LLM 调用接口，实现 Provider 无关性。
v1.3.36: +Function Calling / Tool Use 抽象。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterator, Union

__all__ = [
    "MessageRole",
    "Message",
    "CompletionUsage",
    "CompletionChoice",
    "CompletionResult",
    "StreamChunk",
    "TokenUsage",
    "Tool",
    "ToolFunction",
    "ToolParameter",
    "ToolCall",
    "LLMProvider",
]


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class CompletionUsage(TokenUsage):
    cost_usd: float = 0.0


@dataclass
class Message:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


# --- Function Calling / Tool Use ---

@dataclass
class ToolParameter:
    """JSON Schema 属性定义。"""
    type: str = "string"
    description: str = ""
    enum: list[str] | None = None
    required: bool = False

    def as_schema(self) -> dict[str, Any]:
        s: dict[str, Any] = {"type": self.type}
        if self.description:
            s["description"] = self.description
        if self.enum:
            s["enum"] = self.enum
        return s


@dataclass
class ToolFunction:
    """函数定义。"""
    name: str
    description: str = ""
    parameters: dict[str, ToolParameter] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def as_schema(self) -> dict[str, Any]:
        props = {k: v.as_schema() for k, v in self.parameters.items()}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": self.required or [k for k, v in self.parameters.items() if v.required],
                },
            },
        }


@dataclass
class Tool:
    """顶层 Tool 包装。"""
    function: ToolFunction

    def as_schema(self) -> dict[str, Any]:
        return self.function.as_schema()

    @classmethod
    def from_function(
        cls,
        name: str,
        description: str = "",
        parameters: dict[str, ToolParameter] | None = None,
        required: list[str] | None = None,
    ) -> Tool:
        return cls(
            function=ToolFunction(
                name=name, description=description,
                parameters=parameters or {},
                required=required or [],
            )
        )


@dataclass
class ToolCall:
    """模型请求的工具调用。"""
    id: str
    name: str
    arguments: str  # JSON string

    @property
    def parsed_arguments(self) -> dict[str, Any]:
        import json
        return json.loads(self.arguments)


@dataclass
class CompletionChoice:
    index: int
    message: Message
    finish_reason: str = "stop"


@dataclass
class CompletionResult:
    id: str = ""
    model: str = ""
    choices: list[CompletionChoice] = field(default_factory=list)
    usage: CompletionUsage = field(default_factory=CompletionUsage)
    created: int = 0


@dataclass
class StreamChunk:
    content: str = ""
    finish_reason: str | None = None
    index: int = 0
    tool_calls: list[ToolCall] | None = None


class LLMProvider(ABC):
    """统一 LLM Provider 抽象。实现 OpenAI / Anthropic / 本地模型 的标准化调用。"""

    def __init__(self, model: str = "", api_key: str = "", base_url: str = ""):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    @abstractmethod
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
        """同步聊天补全。"""
        ...

    @abstractmethod
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
        """异步聊天补全。"""
        ...

    def stream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """流式聊天补全。默认调用非流式包装。"""
        result = self.chat(messages, temperature=temperature, max_tokens=max_tokens, tools=tools, **kwargs)
        for c in result.choices:
            yield StreamChunk(content=c.message.content, finish_reason=c.finish_reason, index=c.index)

    async def astream(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[Tool] | None = None,
        **kwargs: Any,
    ):
        """异步流式补全。默认调用 achat 包装。"""
        result = await self.achat(messages, temperature=temperature, max_tokens=max_tokens, tools=tools, **kwargs)
        for c in result.choices:
            yield StreamChunk(content=c.message.content, finish_reason=c.finish_reason, index=c.index)

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...
