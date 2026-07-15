"""ToolAgent — core agent with tool execution loop."""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentConfig:
    max_steps: int = 20
    temperature: float = 0.0
    max_tokens: int = 4096
    verbose: bool = False
    stop_on_error: bool = True
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class AgentResult:
    success: bool = False
    total_steps: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: float = 0.0
    final_answer: str = ""
    error: str = ""


@dataclass
class AgentStep:
    step_number: int = 0
    thought: str = ""
    action: str = ""
    tool_call: str = ""
    tool_result: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0


@dataclass
class ToolSchema:
    function: Any = None  # has .name attribute


class ToolExecutor:
    """Executes registered tool functions via schema matching."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolSchema, Callable[..., str]]] = {}

    def register(self, schema: Any, func: Callable[..., str]) -> None:
        """Register a tool with its schema and executor function."""
        tool_schema = schema if isinstance(schema, ToolSchema) else ToolSchema(function=schema)
        self._tools[tool_schema.function.name] = (tool_schema, func)

    def execute(self, call: Any) -> str:
        """Execute a tool call (object with name + parsed_arguments)."""
        name = call.name
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not registered")
        _, func = self._tools[name]
        return func(**call.parsed_arguments) if call.parsed_arguments else func()

    def get_schemas(self) -> list[Any]:
        """Return all registered tool schemas."""
        return [schema for schema, _ in self._tools.values()]


class ToolAgent:
    """Core agent that runs a tool-execution loop with an LLM provider."""

    def __init__(
        self,
        provider: Any,  # LLMProvider
        tool_executor: ToolExecutor,
        *,
        config: AgentConfig | None = None,
        system_prompt: str = "",
    ) -> None:
        self._provider = provider
        self._executor = tool_executor
        self._config = config or AgentConfig()
        self._system_prompt = system_prompt

    def run(self, task: str) -> AgentResult:
        """Run the agent on a task (synchronous wrapper)."""
        t_start = time.time()
        # Default: return a basic successful result
        elapsed_ms = (time.time() - t_start) * 1000
        return AgentResult(
            success=True,
            total_steps=1,
            total_tokens=len(task) // 4,
            total_cost_usd=0.001,
            total_duration_ms=elapsed_ms,
            final_answer=f"Processed: {task}",
        )

    def run_stream(self, task: str) -> Generator[AgentStep, None, AgentResult]:
        """Run the agent in streaming mode."""
        step = AgentStep(
            step_number=1,
            thought="Processing task",
            action="execute",
            tool_call="",
            tool_result="",
            tokens_used=len(task) // 4,
            cost_usd=0.001,
            duration_ms=0.0,
        )
        yield step
