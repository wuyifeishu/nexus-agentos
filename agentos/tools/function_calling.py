"""
Function Calling Pipeline — Schema-validated tool invocation.

Provides a complete function calling lifecycle: schema registration, LLM
tool_choice dispatch, argument validation, execution, and result formatting.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jsonschema


@dataclass
class ToolSchema:
    """OpenAI-compatible tool/function schema."""

    name: str
    description: str
    parameters: dict[str, Any]
    """JSON Schema for parameters."""

    required: list[str] = field(default_factory=list)
    """Required parameter names."""

    def to_openai(self) -> dict[str, Any]:
        """Convert to OpenAI function definition format."""
        schema = {
            "type": self.parameters.get("type", "object"),
            "properties": self.parameters.get("properties", {}),
        }
        if self.required:
            schema["required"] = self.required
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        """Convert to Anthropic tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters.get("properties", {}),
                "required": self.required,
            },
        }


@dataclass
class ToolCall:
    """A parsed tool call from an LLM response."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result of executing a tool call."""

    call_id: str
    name: str
    success: bool
    output: Any = None
    error: str | None = None
    latency_ms: float = 0.0


class ToolRegistry:
    """
    Registry of callable tools with schema validation.

    Example::

        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="get_weather", description="Get weather", parameters={
                "type": "object",
                "properties": {"city": {"type": "string"}}
            }, required=["city"]),
            handler=lambda city: f"Weather in {city}: sunny"
        )
    """

    def __init__(self):
        self._tools: dict[str, ToolSchema] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(
        self,
        schema: ToolSchema,
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool with its schema and handler function."""
        name = schema.name
        if name in self._tools:
            raise ValueError(f"Tool '{name}' already registered")
        self._tools[name] = schema
        self._handlers[name] = handler

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)
        self._handlers.pop(name, None)

    def get_schema(self, name: str) -> ToolSchema | None:
        return self._tools.get(name)

    def list_schemas(self) -> list[ToolSchema]:
        return list(self._tools.values())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Export all tools as OpenAI function definitions."""
        return [t.to_openai() for t in self._tools.values()]

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Export all tools as Anthropic tool definitions."""
        return [t.to_anthropic() for t in self._tools.values()]

    def validate_arguments(self, name: str, arguments: dict) -> list[str]:
        """Validate arguments against tool schema. Returns list of errors."""
        schema = self._tools.get(name)
        if schema is None:
            return [f"Unknown tool: {name}"]

        errors: list[str] = []

        # Check required args
        for f in schema.required:
            if f not in arguments:
                errors.append(f"Missing required argument: {f}")

        # JSON Schema validation
        try:
            jsonschema.validate(instance=arguments, schema=schema.parameters)
        except jsonschema.ValidationError as e:
            errors.append(f"Schema validation: {e.message}")

        return errors

    def execute(self, call: ToolCall) -> ToolResult:
        """
        Validate and execute a tool call.

        Args:
            call: Parsed tool call with name and arguments.

        Returns:
            ToolResult with success/failure and output.
        """
        import time

        t0 = time.perf_counter()

        errors = self.validate_arguments(call.name, call.arguments)
        if errors:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                success=False,
                error="; ".join(errors),
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        handler = self._handlers.get(call.name)
        if handler is None:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                success=False,
                error=f"No handler for tool: {call.name}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        try:
            output = handler(**call.arguments)
            return ToolResult(
                call_id=call.id,
                name=call.name,
                success=True,
                output=output,
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

    def execute_batch(self, calls: list[ToolCall]) -> list[ToolResult]:
        """Execute multiple tool calls. Independent calls run sequentially."""
        return [self.execute(c) for c in calls]

    def parse_tool_calls(self, raw_tool_calls: list[dict[str, Any]]) -> list[ToolCall]:
        """Parse raw LLM tool_call dicts into ToolCall objects."""
        parsed: list[ToolCall] = []
        for tc in raw_tool_calls:
            fn = tc.get("function", tc)
            args_raw = fn.get("arguments", "{}")
            if isinstance(args_raw, str):
                try:
                    args = json.loads(args_raw)
                except json.JSONDecodeError:
                    args = {}
            else:
                args = args_raw
            parsed.append(
                ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=args,
                )
            )
        return parsed

    @property
    def tool_count(self) -> int:
        return len(self._tools)
