"""
统一工具注册表 — 核心循环不关心具体实现。
"""

from __future__ import annotations

import asyncio
import uuid

from agentos.tools.base import BaseTool, ToolCall, ToolResult


class ToolRegistry:
    """统一工具注册表。所有工具在这里注册，核心循环不关心具体实现。"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def register_many(self, tools: list[BaseTool]):
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_schemas_for_model(self, model_type: str) -> list[dict]:
        """根据模型类型生成工具schema。"""
        if model_type in ("openai", "deepseek", "kimi", "qwen", "glm", "minimax"):
            return [t.to_openai_schema() for t in self._tools.values()]
        elif model_type == "anthropic":
            return [t.to_anthropic_schema() for t in self._tools.values()]
        else:
            return [t.to_openai_schema() for t in self._tools.values()]

    async def execute_batch(self, calls: list[ToolCall], sandbox=None) -> list[ToolResult]:
        """并行执行一组工具调用。"""
        tasks = []
        for call in calls:
            tool = self._tools.get(call.name)
            if not tool:
                tasks.append(self._unknown_tool_result(call))
            else:
                tasks.append(self._execute_one(tool, call, sandbox))
        return await asyncio.gather(*tasks)

    async def _execute_one(self, tool: BaseTool, call: ToolCall, sandbox=None) -> ToolResult:
        try:
            return await tool.execute(call.arguments, sandbox=sandbox)
        except Exception as e:
            return ToolResult(call_id=call.id, error=str(e))

    async def _unknown_tool_result(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            error=f"Unknown tool: {call.name}. Available: {self.list_names()}",
        )

    @staticmethod
    def make_call_id() -> str:
        return f"call_{uuid.uuid4().hex[:12]}"
