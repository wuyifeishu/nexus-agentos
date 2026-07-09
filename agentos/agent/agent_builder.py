"""
Agent Builder — 一键构建生产级 ToolAgent。

自动发现所有 BaseTool 子类并通过 Bridge 注册到 ToolExecutor。
支持多种 LLM Provider 的自动探测。
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil

from agentos.agent.tool_agent import AgentConfig, ToolAgent, ToolExecutor
from agentos.llm.base import LLMProvider
from agentos.tools.base import BaseTool
from agentos.tools.bridge import bridge_registry_to_executor
from agentos.tools.registry import ToolRegistry

# ── Tool Discovery ──


def discover_tools(package_path: str = "agentos.tools") -> list[BaseTool]:
    """自动发现 agentos.tools 包下所有 BaseTool 子类并实例化。

    排除已知不能独立执行的基础类。
    """
    tools: list[BaseTool] = []
    seen: set[str] = set()

    package = importlib.import_module(package_path)
    package_dir = os.path.dirname(package.__file__)

    for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
        if module_name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{package_path}.{module_name}")
        except Exception:
            continue

        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(obj, BaseTool) or obj is BaseTool:
                continue
            if name in seen:
                continue
            # Skip abstract/helper base classes
            if getattr(obj, "name", None) is None:
                continue
            try:
                instance = obj()
                tools.append(instance)
                seen.add(name)
            except Exception:
                continue

    return tools


# ── Provider Auto-Detection ──


def create_provider() -> LLMProvider:
    """自动探测可用的 LLM Provider。

    优先级: DEEPSEEK_API_KEY > OPENAI_API_KEY > Mock (dev fallback)
    """
    # DeepSeek
    if os.getenv("DEEPSEEK_API_KEY"):
        from agentos.llm.providers.deepseek import DeepSeekProvider

        return DeepSeekProvider(model="deepseek-chat")

    # OpenAI
    if os.getenv("OPENAI_API_KEY"):
        from agentos.llm.providers.openai import OpenAIProvider

        return OpenAIProvider(model="gpt-4o-mini")

    # Anthropic
    if os.getenv("ANTHROPIC_API_KEY"):
        from agentos.llm.providers.anthropic import AnthropicProvider

        return AnthropicProvider(model="claude-3-5-sonnet-20241022")

    # Mock (dev fallback)
    from agentos.agent.agent_builder import _MockProvider

    return _MockProvider()


class _MockProvider(LLMProvider):
    """仅用于开发环境的 Mock Provider。"""

    provider_name = "mock-dev"

    def __init__(self):
        super().__init__(model="mock")

    def chat(self, messages, **kwargs):
        return self._make("Mock provider: no API key configured. Set DEEPSEEK_API_KEY.")

    async def achat(self, messages, **kwargs):
        return self.chat(messages, **kwargs)

    def _make(self, content):
        from agentos.llm.base import (
            CompletionChoice,
            CompletionResult,
            CompletionUsage,
            Message,
            MessageRole,
        )

        return CompletionResult(
            choices=[
                CompletionChoice(
                    index=0,
                    message=Message(role=MessageRole.ASSISTANT, content=content),
                    finish_reason="stop",
                )
            ],
            usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="mock",
        )


# ── Builder ──


def build_agent(
    *,
    tools: list[BaseTool] | None = None,
    provider: LLMProvider | None = None,
    system_prompt: str | None = None,
    max_steps: int = 10,
    verbose: bool = False,
    discover_all: bool = True,
    include_skills: bool = True,
) -> ToolAgent:
    """一键构建生产级 ToolAgent。

    Args:
        tools: 手动指定的工具列表。为 None 且 discover_all=True 时自动发现全部。
        provider: LLM Provider。为 None 时自动探测。
        system_prompt: 系统提示词。为 None 时使用默认中文提示。
        max_steps: 最大推理步数。
        verbose: 是否打印详细日志。
        discover_all: 是否自动发现所有 BaseTool。

    Returns:
        配置完成的 ToolAgent 实例。

    Example:
        agent = build_agent()
        result = agent.run("列出 /tmp 目录下的所有 .txt 文件")
    """
    # Tools
    if tools is None and discover_all:
        tools = discover_tools()

    # Skills — auto-discover and wrap as tools
    if include_skills:
        try:
            from agentos.tools.skill_tool import discover_skills

            skill_tools = discover_skills()
            if tools is None:
                tools = list(skill_tools)
            else:
                tools = list(tools) + list(skill_tools)
        except Exception:
            pass

    if tools is None:
        tools = []

    reg = ToolRegistry()
    for tool in tools:
        reg.register(tool)

    executor = ToolExecutor()
    bridge_registry_to_executor(reg, executor)

    # Provider
    if provider is None:
        provider = create_provider()

    # System prompt
    if system_prompt is None:
        tool_names = ", ".join(t.name for t in tools) if tools else "无"
        system_prompt = (
            "你是一个智能助手，可以使用工具来完成任务。\n"
            f"可用工具: {tool_names}\n"
            "当你可以给出最终答案时直接回答，不要再调用工具。\n"
            "用简洁的中文回答。"
        )

    agent = ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(max_steps=max_steps, verbose=verbose),
        system_prompt=system_prompt,
    )

    return agent
