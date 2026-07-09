"""Tests for agentos/agent/agent_builder.py."""

import os

from agentos.agent.agent_builder import (
    _MockProvider,
    build_agent,
    create_provider,
    discover_tools,
)
from agentos.agent.tool_agent import ToolAgent


class TestMockProvider:
    def test_provider_name(self):
        mp = _MockProvider()
        assert mp.provider_name == "mock-dev"

    def test_chat_returns_completion(self):
        mp = _MockProvider()
        result = mp.chat([{"role": "user", "content": "hello"}])
        assert result is not None
        assert len(result.choices) == 1
        assert "Mock provider" in result.choices[0].message.content

    def test_achat_returns_same(self):
        import asyncio
        mp = _MockProvider()
        sync = mp.chat([])
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        async_result = loop.run_until_complete(mp.achat([]))
        assert async_result.choices[0].message.content == sync.choices[0].message.content


class TestDiscoverTools:
    def test_discovers_tools(self):
        tools = discover_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_tools_are_instantiated(self):
        tools = discover_tools()
        for tool in tools:
            assert hasattr(tool, "name")
            assert tool.name is not None

    def test_no_duplicate_tools(self):
        tools = discover_tools()
        names = [t.name for t in tools]
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"


class TestCreateProvider:
    def test_returns_mock_when_no_api_key(self):
        # Ensure no API keys are set
        for key in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            os.environ.pop(key, None)
        provider = create_provider()
        assert provider.provider_name == "mock-dev"
        assert isinstance(provider, _MockProvider)

    def test_returns_deepseek_when_key_set(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from agentos.llm.providers.deepseek import DeepSeekProvider
        provider = create_provider()
        assert isinstance(provider, DeepSeekProvider)

    def test_returns_openai_when_only_openai_key_set(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from agentos.llm.providers.openai import OpenAIProvider
        provider = create_provider()
        assert isinstance(provider, OpenAIProvider)


class TestBuildAgent:
    def test_builds_with_mock_provider(self):
        # Ensure no real API keys
        for key in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            os.environ.pop(key, None)
        agent = build_agent(discover_all=False, include_skills=False)
        assert isinstance(agent, ToolAgent)
        assert agent._provider.provider_name == "mock-dev"

    def test_builds_with_manual_tools(self):
        tools = discover_tools()[:3]  # take first 3
        agent = build_agent(tools=list(tools), discover_all=False, include_skills=False)
        assert isinstance(agent, ToolAgent)

    def test_builds_with_custom_system_prompt(self):
        custom_prompt = "You are a test assistant. Answer briefly."
        agent = build_agent(
            system_prompt=custom_prompt,
            discover_all=False,
            include_skills=False,
        )
        assert agent._system_prompt == custom_prompt

    def test_builds_with_default_system_prompt(self):
        agent = build_agent(discover_all=False, include_skills=False)
        assert "智能助手" in agent._system_prompt

    def test_builds_with_custom_max_steps(self):
        agent = build_agent(max_steps=5, discover_all=False, include_skills=False)
        assert agent._config.max_steps == 5

    def test_builds_with_custom_verbose(self):
        agent = build_agent(verbose=True, discover_all=False, include_skills=False)
        assert agent._config.verbose is True

    def test_builds_with_custom_provider(self):
        mp = _MockProvider()
        agent = build_agent(provider=mp, discover_all=False, include_skills=False)
        assert agent._provider is mp
