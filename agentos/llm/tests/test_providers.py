"""LLM Provider 模块单元测试 — v1.3.36。
测试范围: factory, base types, Function Calling, DeepSeek, Anthropic (unit/mock)。
"""

import os
from unittest.mock import patch

import pytest

from agentos.llm import (
    AnthropicProvider,
    CompletionUsage,
    DeepSeekProvider,
    LLMProvider,
    Message,
    MessageRole,
    OpenAIProvider,
    StreamChunk,
    TokenUsage,
    Tool,
    ToolCall,
    ToolParameter,
    create_provider,
)

# ── Base Types ───────────────────────────────────────────────────


class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_values(self):
        u = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert u.prompt_tokens == 100


class TestCompletionUsage:
    def test_cost_default(self):
        u = CompletionUsage(prompt_tokens=500, completion_tokens=200, total_tokens=700)
        assert u.cost_usd == 0.0


class TestMessage:
    def test_basic(self):
        m = Message(role=MessageRole.USER, content="hi")
        d = m.as_dict()
        assert d["role"] == "user"
        assert d["content"] == "hi"

    def test_with_tool_call_id(self):
        m = Message(role=MessageRole.TOOL, content="result", tool_call_id="call_123")
        d = m.as_dict()
        assert d["tool_call_id"] == "call_123"

    def test_with_tool_calls(self):
        m = Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="tc1", name="get_weather", arguments='{"city":"NYC"}')],
        )
        assert m.tool_calls[0].name == "get_weather"


# ── Tool / Function Calling ───────────────────────────────────────


class TestToolParameter:
    def test_basic_schema(self):
        p = ToolParameter(type="string", description="City name", required=True)
        s = p.as_schema()
        assert s["type"] == "string"
        assert s["description"] == "City name"

    def test_with_enum(self):
        p = ToolParameter(type="string", enum=["celsius", "fahrenheit"])
        s = p.as_schema()
        assert s["enum"] == ["celsius", "fahrenheit"]


class TestTool:
    def test_from_function(self):
        t = Tool.from_function(
            "get_weather",
            "Get weather for a city",
            {
                "city": ToolParameter(type="string", description="City", required=True),
                "unit": ToolParameter(type="string", enum=["celsius", "fahrenheit"]),
            },
            required=["city"],
        )
        schema = t.as_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == "get_weather"
        assert fn["parameters"]["required"] == ["city"]
        assert "city" in fn["parameters"]["properties"]

    def test_to_openai_format(self):
        t = Tool.from_function(
            "search",
            "Web search",
            {
                "query": ToolParameter(type="string", description="Query", required=True),
            },
        )
        schema = t.as_schema()
        assert schema["function"]["name"] == "search"
        props = schema["function"]["parameters"]["properties"]
        assert props["query"]["type"] == "string"


class TestToolCall:
    def test_create_and_parse(self):
        tc = ToolCall(id="call_1", name="add", arguments='{"a":1,"b":2}')
        assert tc.id == "call_1"
        assert tc.name == "add"
        assert tc.parsed_arguments == {"a": 1, "b": 2}

    def test_empty_arguments(self):
        tc = ToolCall(id="x", name="ping", arguments="{}")
        assert tc.parsed_arguments == {}


# ── StreamChunk ────────────────────────────────────────────────────


class TestStreamChunk:
    def test_defaults(self):
        c = StreamChunk()
        assert c.content == ""
        assert c.finish_reason is None

    def test_with_content(self):
        c = StreamChunk(content="hello")
        assert c.content == "hello"


# ── Factory ────────────────────────────────────────────────────────


class TestCreateProvider:
    def test_openai_default(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            p = create_provider("openai")
            assert p.provider_name == "openai"
            assert p.model == "gpt-4o-mini"

    def test_deepseek_default(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds"}, clear=True):
            p = create_provider("deepseek")
            assert p.provider_name == "deepseek"
            assert p.model == "deepseek-chat"
            assert "deepseek.com" in p.base_url

    def test_anthropic_default(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant"}, clear=True):
            p = create_provider("anthropic")
            assert p.provider_name == "anthropic"
            assert "sonnet" in p.model.lower()

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider("nonexistent")

    def test_api_key_env_openai(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-test"}, clear=True):
            p = create_provider("openai")
            assert p.api_key == "sk-env-test"

    def test_custom_model(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            p = create_provider("openai", model="gpt-4o")
            assert p.model == "gpt-4o"


# ── DeepSeek Provider ──────────────────────────────────────────────


class TestDeepSeekProvider:
    def test_is_openai_subclass(self):
        p = DeepSeekProvider(api_key="sk-ds")
        assert isinstance(p, OpenAIProvider)
        assert isinstance(p, LLMProvider)

    def test_provider_name(self):
        p = DeepSeekProvider(api_key="sk-ds")
        assert p.provider_name == "deepseek"

    def test_default_base_url(self):
        p = DeepSeekProvider(api_key="sk-ds")
        assert p.base_url == "https://api.deepseek.com/v1"

    def test_custom_base_url(self):
        p = DeepSeekProvider(api_key="sk-ds", base_url="http://localhost:8080/v1")
        assert p.base_url == "http://localhost:8080/v1"

    def test_default_model(self):
        p = DeepSeekProvider(api_key="sk-ds")
        assert p.model == "deepseek-chat"

    def test_factory_creates(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds"}, clear=True):
            p = create_provider("deepseek")
            assert isinstance(p, DeepSeekProvider)
            assert p.provider_name == "deepseek"


# ── Anthropic Provider ─────────────────────────────────────────────


class TestAnthropicProvider:
    def test_provider_name(self):
        p = AnthropicProvider(api_key="sk-ant")
        assert p.provider_name == "anthropic"

    def test_default_model(self):
        p = AnthropicProvider(api_key="sk-ant")
        assert p.model == "claude-sonnet-4-20250514"

    def test_default_base_url(self):
        p = AnthropicProvider(api_key="sk-ant")
        assert "api.anthropic.com" in p.base_url

    def test_custom_base_url(self):
        p = AnthropicProvider(api_key="sk-ant", base_url="http://localhost:9999")
        assert p.base_url == "http://localhost:9999"

    def test_headers(self):
        p = AnthropicProvider(api_key="sk-ant-test")
        h = p._headers()
        assert h["x-api-key"] == "sk-ant-test"
        assert h["anthropic-version"] == "2023-06-01"

    def test_tools_conversion(self):
        AnthropicProvider(api_key="sk-ant")
        tools = [
            Tool.from_function(
                "get_weather",
                "Get weather",
                {
                    "city": ToolParameter(type="string", description="City", required=True),
                },
            ),
        ]
        from agentos.llm.anthropic_provider import _tools_to_anthropic

        result = _tools_to_anthropic(tools)
        assert len(result) == 1
        assert result[0]["name"] == "get_weather"
        assert result[0]["input_schema"]["type"] == "object"

    def test_message_conversion_simple(self):
        from agentos.llm.anthropic_provider import _messages_to_anthropic

        msgs = [Message(role=MessageRole.USER, content="Hello")]
        system, api_msgs = _messages_to_anthropic(msgs)
        assert system is None
        assert len(api_msgs) == 1
        assert api_msgs[0]["role"] == "user"
        assert api_msgs[0]["content"] == "Hello"

    def test_message_conversion_with_system(self):
        from agentos.llm.anthropic_provider import _messages_to_anthropic

        msgs = [
            Message(role=MessageRole.SYSTEM, content="You are helpful."),
            Message(role=MessageRole.USER, content="Hi"),
        ]
        system, api_msgs = _messages_to_anthropic(msgs)
        assert system == "You are helpful."
        assert len(api_msgs) == 1
        assert api_msgs[0]["role"] == "user"

    def test_build_body_includes_tools(self):
        p = AnthropicProvider(api_key="sk-ant")
        tools = [
            Tool.from_function(
                "search",
                "search the web",
                {
                    "q": ToolParameter(type="string", description="query", required=True),
                },
            )
        ]
        body = p._build_body(
            [Message(role=MessageRole.USER, content="test")],
            temperature=0.5,
            max_tokens=100,
            top_p=0.9,
            stop=None,
            tools=tools,
            tool_choice="auto",
        )
        assert body["model"] == "claude-sonnet-4-20250514"
        assert "tools" in body
        assert body["tools"][0]["name"] == "search"
