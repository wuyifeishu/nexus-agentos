"""Tests for agentos.tools.function_calling — ToolSchema, ToolCall, ToolResult, ToolRegistry."""

import pytest

from agentos.tools.function_calling import (
    ToolCall,
    ToolRegistry,
    ToolResult,
    ToolSchema,
)

# ── ToolSchema Tests ────────────────────────────────────────

class TestToolSchema:
    def test_creation(self):
        schema = ToolSchema(
            name="get_weather",
            description="Get weather for a city",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
            required=["city"],
        )
        assert schema.name == "get_weather"
        assert schema.required == ["city"]

    def test_to_openai(self):
        schema = ToolSchema(
            name="search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            required=["query"],
        )
        result = schema.to_openai()
        assert result["type"] == "function"
        assert result["function"]["name"] == "search"
        assert result["function"]["parameters"]["required"] == ["query"]

    def test_to_openai_no_required(self):
        schema = ToolSchema(
            name="ping",
            description="Check connection",
            parameters={"type": "object", "properties": {}},
        )
        result = schema.to_openai()
        assert "required" not in result["function"]["parameters"]

    def test_to_anthropic(self):
        schema = ToolSchema(
            name="calc",
            description="Calculate something",
            parameters={
                "type": "object",
                "properties": {"expr": {"type": "string"}},
            },
            required=["expr"],
        )
        result = schema.to_anthropic()
        assert result["name"] == "calc"
        assert result["input_schema"]["required"] == ["expr"]


# ── ToolCall / ToolResult Tests ─────────────────────────────

class TestToolCall:
    def test_creation(self):
        call = ToolCall(id="c1", name="echo", arguments={"msg": "hi"})
        assert call.id == "c1"
        assert call.name == "echo"
        assert call.arguments == {"msg": "hi"}


class TestToolResult:
    def test_creation(self):
        result = ToolResult(call_id="c1", name="echo", success=True, output="hello")
        assert result.call_id == "c1"
        assert result.success is True
        assert result.output == "hello"

    def test_failure(self):
        result = ToolResult(call_id="c2", name="fail", success=False, error="boom")
        assert result.success is False
        assert result.error == "boom"

    def test_latency_ms_default(self):
        result = ToolResult(call_id="x", name="y", success=True, output="ok")
        assert result.latency_ms == 0.0


# ── ToolRegistry Tests ──────────────────────────────────────

class TestToolRegistry:
    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    @pytest.fixture
    def weather_schema(self):
        return ToolSchema(
            name="get_weather",
            description="Get weather",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}},
            },
            required=["city"],
        )

    def test_register_and_get(self, registry, weather_schema):
        def handler(city):
            return f"Weather in {city}: sunny"
        registry.register(weather_schema, handler)
        assert registry.tool_count == 1
        schema = registry.get_schema("get_weather")
        assert schema is not None
        assert schema.name == "get_weather"

    def test_register_duplicate_raises(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        with pytest.raises(ValueError, match="already registered"):
            registry.register(weather_schema, lambda city: "ok2")

    def test_unregister(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        assert registry.tool_count == 1
        registry.unregister("get_weather")
        assert registry.tool_count == 0
        assert registry.get_schema("get_weather") is None

    def test_unregister_nonexistent_no_error(self, registry):
        registry.unregister("nope")

    def test_list_schemas(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        schemas = registry.list_schemas()
        assert len(schemas) == 1
        assert schemas[0].name == "get_weather"

    def test_to_openai_tools(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        tools = registry.to_openai_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "get_weather"

    def test_to_anthropic_tools(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        tools = registry.to_anthropic_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "get_weather"

    def test_validate_arguments_valid(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        errors = registry.validate_arguments("get_weather", {"city": "London"})
        assert errors == []

    def test_validate_arguments_missing_required(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        errors = registry.validate_arguments("get_weather", {})
        assert any("Missing required" in e for e in errors)

    def test_validate_arguments_unknown_tool(self, registry):
        errors = registry.validate_arguments("unknown", {})
        assert any("Unknown tool" in e for e in errors)

    def test_validate_arguments_schema_violation(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        errors = registry.validate_arguments("get_weather", {"city": 123})
        assert any("Schema validation" in e for e in errors)

    def test_execute_success(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: f"Weather in {city}: sunny")
        call = ToolCall(id="c1", name="get_weather", arguments={"city": "Paris"})
        result = registry.execute(call)
        assert result.success is True
        assert "Paris" in result.output
        assert result.latency_ms >= 0

    def test_execute_validation_failure(self, registry, weather_schema):
        registry.register(weather_schema, lambda city: "ok")
        call = ToolCall(id="c1", name="get_weather", arguments={})
        result = registry.execute(call)
        assert result.success is False

    def test_execute_no_handler(self, registry):
        call = ToolCall(id="c1", name="ghost", arguments={})
        result = registry.execute(call)
        assert result.success is False
        assert "Unknown tool" in result.error or "No handler" in result.error

    def test_execute_handler_exception(self, registry, weather_schema):
        def bad_handler(city):
            raise RuntimeError("boom")
        registry.register(weather_schema, bad_handler)
        call = ToolCall(id="c1", name="get_weather", arguments={"city": "X"})
        result = registry.execute(call)
        assert result.success is False
        assert "RuntimeError" in result.error

    def test_execute_batch(self, registry, weather_schema):
        def handler(city):
            return f"Weather: {city}"
        registry.register(weather_schema, handler)
        calls = [
            ToolCall(id="1", name="get_weather", arguments={"city": "London"}),
            ToolCall(id="2", name="get_weather", arguments={"city": "Tokyo"}),
        ]
        results = registry.execute_batch(calls)
        assert len(results) == 2
        assert all(r.success for r in results)
        assert "London" in results[0].output
        assert "Tokyo" in results[1].output

    def test_parse_tool_calls_string_args(self, registry):
        raw = [
            {
                "id": "call_1",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"city": "Berlin"}',
                },
            }
        ]
        parsed = registry.parse_tool_calls(raw)
        assert len(parsed) == 1
        assert parsed[0].name == "get_weather"
        assert parsed[0].arguments == {"city": "Berlin"}

    def test_parse_tool_calls_dict_args(self, registry):
        raw = [
            {
                "id": "call_1",
                "function": {
                    "name": "search",
                    "arguments": {"query": "Python"},
                },
            }
        ]
        parsed = registry.parse_tool_calls(raw)
        assert len(parsed) == 1
        assert parsed[0].arguments == {"query": "Python"}

    def test_parse_tool_calls_invalid_json(self, registry):
        raw = [
            {
                "id": "call_1",
                "function": {
                    "name": "bad",
                    "arguments": "not json{",
                },
            }
        ]
        parsed = registry.parse_tool_calls(raw)
        assert parsed[0].arguments == {}

    def test_parse_tool_calls_no_function_key(self, registry):
        raw = [{"name": "echo", "arguments": "{}"}]
        parsed = registry.parse_tool_calls(raw)
        assert len(parsed) == 1
        assert parsed[0].name == "echo"

    def test_tool_count(self, registry, weather_schema):
        assert registry.tool_count == 0
        registry.register(weather_schema, lambda city: "ok")
        assert registry.tool_count == 1
