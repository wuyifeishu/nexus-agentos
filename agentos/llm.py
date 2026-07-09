from dataclasses import dataclass
from enum import Enum


class MessageRole(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    role: MessageRole = MessageRole.USER
    content: str = ""


@dataclass
class ToolParameter:
    name: str = ""


@dataclass
class ToolFunction:
    name: str = ""


@dataclass
class Tool:
    type: str = "function"


@dataclass
class ToolCall:
    id: str = ""


@dataclass
class CompletionChoice:
    text: str = ""


@dataclass
class TokenUsage:
    prompt: int = 0
    completion: int = 0


@dataclass
class CompletionUsage:
    pass


@dataclass
class CompletionResult:
    choices: list = None


@dataclass
class StreamChunk:
    content: str = ""


class LLMProvider:
    pass


class OpenAIProvider(LLMProvider):
    pass


class DeepSeekProvider(LLMProvider):
    pass


class AnthropicProvider(LLMProvider):
    pass


def create_provider(name: str) -> LLMProvider:
    return OpenAIProvider()
