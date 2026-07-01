"""
Nexus AgentOS LLM 模块。
提供统一的 LLM Provider 抽象，支持 OpenAI / DeepSeek / Anthropic 等。
v1.3.36: +DeepSeekProvider +AnthropicProvider +Function Calling。
"""

from agentos.llm.base import (
    CompletionChoice,
    CompletionResult,
    CompletionUsage,
    LLMProvider,
    Message,
    MessageRole,
    StreamChunk,
    TokenUsage,
    Tool,
    ToolCall,
    ToolFunction,
    ToolParameter,
)
from agentos.llm.factory import create_provider
from agentos.llm.openai_provider import OpenAIProvider
from agentos.llm.deepseek_provider import DeepSeekProvider
from agentos.llm.anthropic_provider import AnthropicProvider

__all__ = [
    "LLMProvider",
    "OpenAIProvider",
    "DeepSeekProvider",
    "AnthropicProvider",
    "CompletionResult",
    "CompletionChoice",
    "CompletionUsage",
    "TokenUsage",
    "Message",
    "MessageRole",
    "StreamChunk",
    "Tool",
    "ToolCall",
    "ToolFunction",
    "ToolParameter",
    "create_provider",
]
