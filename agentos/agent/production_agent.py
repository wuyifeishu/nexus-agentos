"""
ProductionAgent — 生产级一行调用接口。

将 LLM Provider → ToolExecutor → Bridge → BaseTool/Skill 全链路封装，
提供结构化日志、结果统计，开箱即用。

用法:
    from agentos.agent.production_agent import ProductionAgent

    agent = ProductionAgent()
    result = agent.run("分析我的 CSV 文件 sales.csv")

    print(result.output)
    print(f"{result.total_steps} steps, {result.total_latency_ms:.0f}ms")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agentos.agent.agent_builder import build_agent
from agentos.llm.base import LLMProvider

logger = logging.getLogger("agentos.production")


@dataclass
class AgentResult:
    """Agent 执行完整结果。"""

    success: bool
    output: str = ""
    error: str | None = None
    total_steps: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    tool_calls: int = 0


class ProductionAgent:
    """生产级 Agent — 一行 run() 搞定一切。

    Example:
        agent = ProductionAgent()
        result = agent.run("帮我计算 hello world 的 SHA256")
        print(result.output)
    """

    def __init__(
        self,
        provider: LLMProvider | None = None,
        max_steps: int = 20,
        system_prompt: str | None = None,
        include_skills: bool = True,
        verbose: bool = False,
    ):
        self.verbose = verbose

        self._agent = build_agent(
            provider=provider,
            max_steps=max_steps,
            system_prompt=system_prompt,
            include_skills=include_skills,
            verbose=verbose,
        )

    def run(self, task: str) -> AgentResult:
        """执行任务并返回结构化结果。"""
        logger.info(f"Task: {task[:120]}")

        try:
            raw = self._agent.run(task)

            tool_calls = sum(len(s.tool_calls) for s in raw.steps)

            logger.info(
                f"Done: {raw.total_steps} steps, "
                f"{tool_calls} tool calls, "
                f"{raw.total_duration_ms:.0f}ms"
            )

            return AgentResult(
                success=raw.success,
                output=raw.final_answer or "",
                error=raw.error,
                total_steps=raw.total_steps,
                total_tokens=raw.total_tokens,
                total_cost_usd=raw.total_cost_usd,
                total_latency_ms=raw.total_duration_ms,
                tool_calls=tool_calls,
            )

        except Exception as e:
            logger.error(f"Failed: {e}")
            return AgentResult(success=False, error=str(e))

    def get_tool_count(self) -> int:
        """返回已注册工具数量。"""
        return len(self._agent._executor._tools)

    def list_tools(self) -> list[str]:
        """返回已注册工具名称列表。"""
        return sorted(self._agent._executor._tools.keys())
