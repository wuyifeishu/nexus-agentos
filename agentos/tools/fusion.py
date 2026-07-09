"""
Fusion Toolkit for NexusAgent.

Multi-tool coordination system. Allows agents to use
multiple tools in sequence or parallel, with automatic
result fusion and conflict resolution.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FusionMode(StrEnum):
    """Tool fusion modes."""

    SEQUENTIAL = "sequential"  # Run tools one by one
    PARALLEL = "parallel"  # Run tools in parallel
    CHAIN = "chain"  # Output of one feeds into next


@dataclass
class ToolSpec:
    """
    Tool specification.

    Attributes:
        name: Tool name
        description: Tool description
        func: Tool function
        parameters: Parameter schema
        timeout: Execution timeout
        retry_count: Number of retries
    """

    name: str
    description: str = ""
    func: Callable[..., Any] = None
    parameters: dict[str, Any] = field(default_factory=dict)
    timeout: float = 30.0
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
        }


@dataclass
class ToolResult:
    """
    Result of a single tool execution.

    Attributes:
        tool_name: Name of the tool
        success: Whether execution succeeded
        output: Tool output
        error: Error message (if failed)
        duration: Execution duration
    """

    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
    duration: float = 0.0


@dataclass
class FusionResult:
    """
    Result of tool fusion.

    Attributes:
        id: Unique identifier
        mode: Fusion mode used
        results: List of individual tool results
        fused_output: Fused final output
        total_duration: Total execution duration
        success: Whether fusion succeeded
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    mode: FusionMode = FusionMode.SEQUENTIAL
    results: list[ToolResult] = field(default_factory=list)
    fused_output: Any = None
    total_duration: float = 0.0
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "mode": self.mode.value,
            "results": [
                {
                    "tool_name": r.tool_name,
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                    "duration": r.duration,
                }
                for r in self.results
            ],
            "fused_output": self.fused_output,
            "total_duration": self.total_duration,
            "success": self.success,
        }


class FusionToolkit:
    """
    Multi-tool coordination system.

    Allows agents to use multiple tools in different modes:
    - Sequential: Run tools one by one
    - Parallel: Run tools in parallel
    - Chain: Output of one feeds into next

    Usage:
        toolkit = FusionToolkit()
        toolkit.register(ToolSpec(name="search", func=search_func))
        toolkit.register(ToolSpec(name="summarize", func=summarize_func))

        # Sequential execution
        result = await toolkit.execute(["search", "summarize"], {"query": "AI"})

        # Parallel execution
        result = await toolkit.execute_parallel(["search", "summarize"], {"query": "AI"})
    """

    def __init__(self, default_timeout: float = 30.0):
        """
        Initialize fusion toolkit.

        Args:
            default_timeout: Default tool timeout
        """
        self._tools: dict[str, ToolSpec] = {}
        self._default_timeout = default_timeout

    def register(self, tool: ToolSpec) -> None:
        """
        Register a tool.

        Args:
            tool: Tool specification
        """
        self._tools[tool.name] = tool

    def unregister(self, tool_name: str) -> bool:
        """
        Unregister a tool.

        Args:
            tool_name: Tool name

        Returns:
            True if unregistered, False if not found
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
        return False

    def get_tool(self, tool_name: str) -> ToolSpec | None:
        """
        Get a tool by name.

        Args:
            tool_name: Tool name

        Returns:
            ToolSpec if found, None otherwise
        """
        return self._tools.get(tool_name)

    def list_tools(self) -> list[ToolSpec]:
        """
        List all registered tools.

        Returns:
            List of ToolSpec
        """
        return list(self._tools.values())

    async def execute(
        self,
        tool_names: list[str],
        inputs: dict[str, Any],
        mode: FusionMode = FusionMode.SEQUENTIAL,
    ) -> FusionResult:
        """
        Execute multiple tools.

        Args:
            tool_names: List of tool names
            inputs: Input parameters
            mode: Fusion mode

        Returns:
            FusionResult
        """
        start_time = time.time()

        if mode == FusionMode.SEQUENTIAL:
            result = await self._execute_sequential(tool_names, inputs)
        elif mode == FusionMode.PARALLEL:
            result = await self._execute_parallel(tool_names, inputs)
        elif mode == FusionMode.CHAIN:
            result = await self._execute_chain(tool_names, inputs)
        else:
            raise ValueError(f"Unknown fusion mode: {mode}")

        result.total_duration = time.time() - start_time

        return result

    async def _execute_sequential(
        self,
        tool_names: list[str],
        inputs: dict[str, Any],
    ) -> FusionResult:
        """Execute tools sequentially."""
        result = FusionResult(mode=FusionMode.SEQUENTIAL)

        for tool_name in tool_names:
            tool = self._tools.get(tool_name)
            if not tool:
                result.results.append(
                    ToolResult(
                        tool_name=tool_name,
                        success=False,
                        error=f"Tool not found: {tool_name}",
                    )
                )
                result.success = False
                continue

            try:
                tool_start = time.time()
                output = await self._execute_tool(tool, inputs)
                duration = time.time() - tool_start

                result.results.append(
                    ToolResult(
                        tool_name=tool_name,
                        success=True,
                        output=output,
                        duration=duration,
                    )
                )
            except Exception as e:
                result.results.append(
                    ToolResult(
                        tool_name=tool_name,
                        success=False,
                        error=str(e),
                    )
                )
                result.success = False

        # Fuse outputs
        result.fused_output = self._fuse_outputs(result.results)

        return result

    async def _execute_parallel(
        self,
        tool_names: list[str],
        inputs: dict[str, Any],
    ) -> FusionResult:
        """Execute tools in parallel."""
        result = FusionResult(mode=FusionMode.PARALLEL)

        tasks = []
        for tool_name in tool_names:
            tool = self._tools.get(tool_name)
            if tool:
                tasks.append(self._execute_tool_with_result(tool, inputs))
            else:
                result.results.append(
                    ToolResult(
                        tool_name=tool_name,
                        success=False,
                        error=f"Tool not found: {tool_name}",
                    )
                )

        # Execute in parallel
        if tasks:
            tool_results = await asyncio.gather(*tasks, return_exceptions=True)
            for tr in tool_results:
                if isinstance(tr, Exception):
                    result.results.append(
                        ToolResult(
                            tool_name="unknown",
                            success=False,
                            error=str(tr),
                        )
                    )
                    result.success = False
                else:
                    result.results.append(tr)
                    if not tr.success:
                        result.success = False

        # Fuse outputs
        result.fused_output = self._fuse_outputs(result.results)

        return result

    async def _execute_chain(
        self,
        tool_names: list[str],
        inputs: dict[str, Any],
    ) -> FusionResult:
        """Execute tools in chain (output feeds into next)."""
        result = FusionResult(mode=FusionMode.CHAIN)
        current_input = inputs.copy()

        for tool_name in tool_names:
            tool = self._tools.get(tool_name)
            if not tool:
                result.results.append(
                    ToolResult(
                        tool_name=tool_name,
                        success=False,
                        error=f"Tool not found: {tool_name}",
                    )
                )
                result.success = False
                break

            try:
                tool_start = time.time()
                output = await self._execute_tool(tool, current_input)
                duration = time.time() - tool_start

                result.results.append(
                    ToolResult(
                        tool_name=tool_name,
                        success=True,
                        output=output,
                        duration=duration,
                    )
                )

                # Feed output into next tool
                current_input = {"input": output, **inputs}
            except Exception as e:
                result.results.append(
                    ToolResult(
                        tool_name=tool_name,
                        success=False,
                        error=str(e),
                    )
                )
                result.success = False
                break

        # Final output is last tool's output
        if result.results:
            last_result = result.results[-1]
            if last_result.success:
                result.fused_output = last_result.output

        return result

    async def _execute_tool(
        self,
        tool: ToolSpec,
        inputs: dict[str, Any],
    ) -> Any:
        """Execute a single tool."""
        if not tool.func:
            raise ValueError(f"Tool {tool.name} has no function")

        # Apply timeout
        try:
            if asyncio.iscoroutinefunction(tool.func):
                return await asyncio.wait_for(
                    tool.func(**inputs),
                    timeout=tool.timeout or self._default_timeout,
                )
            else:
                return await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: tool.func(**inputs)),
                    timeout=tool.timeout or self._default_timeout,
                )
        except TimeoutError:
            raise TimeoutError(f"Tool {tool.name} timed out")

    async def _execute_tool_with_result(
        self,
        tool: ToolSpec,
        inputs: dict[str, Any],
    ) -> ToolResult:
        """Execute tool and return ToolResult."""
        try:
            tool_start = time.time()
            output = await self._execute_tool(tool, inputs)
            duration = time.time() - tool_start

            return ToolResult(
                tool_name=tool.name,
                success=True,
                output=output,
                duration=duration,
            )
        except Exception as e:
            return ToolResult(
                tool_name=tool.name,
                success=False,
                error=str(e),
            )

    def _fuse_outputs(self, results: list[ToolResult]) -> Any:
        """Fuse multiple tool outputs."""
        outputs = [r.output for r in results if r.success and r.output is not None]

        if not outputs:
            return None

        if len(outputs) == 1:
            return outputs[0]

        # Default fusion: merge dicts, concatenate lists
        if all(isinstance(o, dict) for o in outputs):
            fused = {}
            for o in outputs:
                fused.update(o)
            return fused

        if all(isinstance(o, list) for o in outputs):
            return [item for o in outputs for item in o]

        # Default: return list of outputs
        return outputs
