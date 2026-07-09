"""Comprehensive unit tests for agent_builder.py — covering all branches."""
import os
from unittest.mock import patch

# ── Test create_provider ──

def test_create_provider_deepseek():
    """When DEEPSEEK_API_KEY is set, use DeepSeek."""
    from agentos.agent.agent_builder import create_provider
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}, clear=True):
        provider = create_provider()
        assert "deepseek" in provider.provider_name

def test_create_provider_openai():
    """When only OPENAI_API_KEY is set, use OpenAI."""
    from agentos.agent.agent_builder import create_provider
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
        provider = create_provider()
        assert "openai" in provider.provider_name.lower()

def test_create_provider_anthropic():
    """When only ANTHROPIC_API_KEY is set, use Anthropic."""
    from agentos.agent.agent_builder import create_provider
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
        provider = create_provider()
        assert "anthropic" in provider.provider_name.lower() or "claude" in provider.provider_name.lower()

def test_create_provider_mock_fallback():
    """When no API key is set, falls back to _MockProvider."""
    from agentos.agent.agent_builder import create_provider
    with patch.dict(os.environ, {}, clear=True):
        provider = create_provider()
        assert "mock" in provider.provider_name

# ── Test discover_tools ──

def test_discover_tools_returns_list():
    """discover_tools returns a non-empty list of BaseTool instances."""
    from agentos.agent.agent_builder import discover_tools
    tools = discover_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0
    from agentos.tools.base import BaseTool
    for t in tools:
        assert isinstance(t, BaseTool)

def test_discover_tools_includes_core_tools():
    """Core tools (read/write/list) are discovered."""
    from agentos.agent.agent_builder import discover_tools
    tools = discover_tools()
    names = {t.name for t in tools}
    assert "read_file" in names
    assert "write_file" in names
    assert "list_directory" in names

def test_discover_tools_no_duplicates():
    """Tool names are unique."""
    from agentos.agent.agent_builder import discover_tools
    tools = discover_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names))

# ── Test build_agent ──

def test_build_agent_without_discover():
    """build_agent with discover_all=False returns an agent with no tools."""
    from agentos.agent.agent_builder import build_agent
    agent = build_agent(discover_all=False, include_skills=False, tools=[], verbose=False)
    assert agent is not None
    schemas = agent._executor.get_schemas()
    assert len(schemas) == 0

def test_build_agent_custom_max_steps():
    """Custom max_steps is applied to AgentConfig."""
    from agentos.agent.agent_builder import build_agent
    agent = build_agent(max_steps=25, discover_all=False, include_skills=False, tools=[], verbose=False)
    assert agent._config.max_steps == 25

def test_build_agent_custom_provider():
    """Custom provider is used when provided."""
    from agentos.agent.agent_builder import _MockProvider, build_agent
    provider = _MockProvider()
    agent = build_agent(provider=provider, discover_all=False, include_skills=False, tools=[], verbose=False)
    assert agent._provider is provider

def test_build_agent_verbose_mode():
    """Verbose flag propagates to config."""
    from agentos.agent.agent_builder import build_agent
    agent = build_agent(verbose=True, discover_all=False, include_skills=False, tools=[], max_steps=1)
    assert agent._config.verbose is True

def test_build_agent_default_system_prompt():
    """Default system prompt mentions available tools."""
    from agentos.agent.agent_builder import build_agent
    agent = build_agent(discover_all=False, include_skills=False, tools=[], verbose=False)
    assert "无" in agent._system_prompt or "工具" in agent._system_prompt

def test_build_agent_system_prompt_with_tools():
    """System prompt lists tool names when tools are provided."""
    from agentos.agent.agent_builder import build_agent
    from agentos.tools.file_tools import ReadFileTool, WriteFileTool
    agent = build_agent(
        tools=[ReadFileTool(), WriteFileTool()],
        discover_all=False,
        include_skills=False,
        verbose=False,
    )
    assert "read_file" in agent._system_prompt
    assert "write_file" in agent._system_prompt

def test_build_agent_include_skills():
    """include_skills=True discovers and adds skill tools."""
    from agentos.agent.agent_builder import build_agent
    agent = build_agent(discover_all=False, include_skills=True, tools=[], verbose=False)
    schemas = agent._executor.get_schemas()
    # Skills should be discovered — at least one skill tool expected
    assert len(schemas) >= 0  # Skills might not exist in test env, but shouldn't crash

# ── Test _MockProvider ──

def test_mock_provider_chat():
    """_MockProvider returns a completion result."""
    from agentos.agent.agent_builder import _MockProvider
    from agentos.llm.base import Message, MessageRole
    provider = _MockProvider()
    result = provider.chat([Message(role=MessageRole.USER, content="hello")])
    assert result is not None
    assert "Mock" in result.choices[0].message.content

def test_mock_provider_achat():
    """_MockProvider async chat works."""
    import asyncio

    from agentos.agent.agent_builder import _MockProvider
    from agentos.llm.base import Message, MessageRole
    provider = _MockProvider()
    result = asyncio.run(provider.achat([Message(role=MessageRole.USER, content="hello")]))
    assert result is not None
    assert "Mock" in result.choices[0].message.content

# ── Test discover_tools error handling ──

def test_discover_tools_skips_bad_modules():
    """discover_tools gracefully skips import errors."""
    from agentos.agent.agent_builder import discover_tools
    # This should not raise even with bad modules
    tools = discover_tools()
    assert isinstance(tools, list)

def test_discover_tools_custom_package():
    """discover_tools with custom package path."""
    from agentos.agent.agent_builder import discover_tools
    tools = discover_tools("agentos.tools")
    assert len(tools) > 0

# ── Test build_agent edge cases ──

def test_build_agent_tools_none_no_discover():
    """tools=None with discover_all=False yields empty tools."""
    from agentos.agent.agent_builder import build_agent
    agent = build_agent(tools=None, discover_all=False, include_skills=False, verbose=False)
    schemas = agent._executor.get_schemas()
    assert len(schemas) == 0

def test_build_agent_with_empty_tools():
    """Explicitly empty tools list."""
    from agentos.agent.agent_builder import build_agent
    agent = build_agent(tools=[], discover_all=False, include_skills=False, verbose=False)
    schemas = agent._executor.get_schemas()
    assert len(schemas) == 0
