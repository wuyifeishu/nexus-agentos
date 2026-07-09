"""
Tool Bridge — 连接 ToolRegistry (BaseTool) 和 ToolExecutor (Tool + callable)。

让 BaseTool 子类可以无缝注册到 ToolAgent 使用的 ToolExecutor 中。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from agentos.llm.base import Tool as LLMTool
from agentos.llm.base import ToolFunction, ToolParameter
from agentos.tools.base import BaseTool
from agentos.tools.registry import ToolRegistry


def base_tool_to_llm_tool(tool: BaseTool) -> LLMTool:
    """将 BaseTool 的 parameters schema 转换为 LLM Tool 对象。"""
    params = tool.parameters or {"type": "object", "properties": {}, "required": []}
    tool_params: dict[str, ToolParameter] = {}
    required_list: list[str] = params.get("required", [])

    for name, schema in params.get("properties", {}).items():
        tool_params[name] = ToolParameter(
            type=schema.get("type", "string"),
            description=schema.get("description", ""),
            enum=schema.get("enum"),
            required=name in required_list,
        )

    return LLMTool(
        function=ToolFunction(
            name=tool.name,
            description=tool.description,
            parameters=tool_params,
            required=required_list,
        )
    )


def make_handler(tool: BaseTool) -> Callable[..., str]:
    """创建适配 callable，让 ToolExecutor 能调用 BaseTool。"""

    def sync_handler(**kwargs) -> str:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, tool.execute(kwargs))
                    result = future.result(timeout=30)
            else:
                result = asyncio.run(tool.execute(kwargs))
        except RuntimeError:
            result = asyncio.run(tool.execute(kwargs))

        if result.error:
            return json.dumps({"error": result.error})
        return result.output or ""

    return sync_handler


def bridge_registry_to_executor(registry: ToolRegistry, executor) -> None:
    """将 ToolRegistry 中所有已注册的 BaseTool 桥接到 ToolExecutor。"""
    for name in registry.list_names():
        tool = registry.get(name)
        if tool is None:
            continue
        llm_tool = base_tool_to_llm_tool(tool)
        handler = make_handler(tool)
        executor.register(llm_tool, handler)
