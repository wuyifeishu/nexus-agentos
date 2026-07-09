"""
多Agent编排管道 — Conditional / Parallel / Router。

v1.5.1: 支持条件路由(ConditionalPipeline)、并行扇出(ParallelPipeline)、
        动态路由(RouterAgent) 三种生产级编排拓扑。
"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from dataclasses import dataclass, field

from agentos.agent.tool_agent import AgentConfig, AgentResult, ToolAgent


@dataclass
class PipelineAgent:
    """管道中的单个 Agent 节点。"""

    name: str
    agent: ToolAgent
    config: AgentConfig | None = None


@dataclass
class PipelineResult:
    """管道执行结果。"""

    success: bool = True
    steps: list[dict] = field(default_factory=list)
    final_output: str = ""
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: float = 0.0
    error: str = ""

    @property
    def output(self) -> str:
        return self.final_output


@dataclass
class StepResult:
    """单个步骤的结果包装。"""

    agent_name: str
    result: AgentResult
    output_key: str | None = None


# ── ConditionalPipeline — 条件路由 ──────────────────────────────────

ConditionFn = Callable[[str], str]  # 输入 → 下一个 agent 名称


class ConditionalPipeline:
    """基于条件路由的多 Agent 管道。

    每个 Agent 执行完成后，通过条件函数决定下一个调用的 Agent。
    支持 if-else / switch-case 风格的决策路由。

    Usage::

        cp = ConditionalPipeline()
        cp.add("classifier", classifier_agent)
        cp.add("legal", legal_agent)
        cp.add("tech", tech_agent)

        # 根据分类器输出决定下一跳
        def route(output: str) -> str:
            if "法律" in output: return "legal"
            if "技术" in output: return "tech"
            return "__END__"

        result = cp.run("这份合同有问题吗？", router=route)
    """

    def __init__(self, max_hops: int = 5):
        self._agents: dict[str, PipelineAgent] = {}
        self._max_hops = max_hops

    def add(self, name: str, agent: ToolAgent, config: AgentConfig | None = None):
        self._agents[name] = PipelineAgent(name=name, agent=agent, config=config)

    def run(
        self, task: str, start_agent: str | None = None, router: ConditionFn | None = None
    ) -> PipelineResult:
        if start_agent is None and self._agents:
            start_agent = next(iter(self._agents))
        if start_agent not in self._agents:
            return PipelineResult(success=False, error=f"Unknown start agent: {start_agent}")

        current = start_agent
        pipeline_output = ""
        steps: list[dict] = []
        total_tokens = 0
        total_cost = 0.0
        total_ms = 0.0

        for hop in range(self._max_hops):
            pa = self._agents[current]
            result = pa.agent.run(task)

            steps.append(
                {
                    "hop": hop,
                    "agent": current,
                    "output": result.final_answer,
                    "tokens": result.total_tokens,
                    "cost": result.total_cost_usd,
                    "duration_ms": result.total_duration_ms,
                }
            )
            total_tokens += result.total_tokens
            total_cost += result.total_cost_usd
            total_ms += result.total_duration_ms
            pipeline_output = result.final_answer

            if not result.success:
                return PipelineResult(
                    success=False,
                    steps=steps,
                    final_output=pipeline_output,
                    total_tokens=total_tokens,
                    total_cost_usd=total_cost,
                    total_duration_ms=total_ms,
                    error=result.error,
                )

            if router is None:
                break

            next_agent = router(result.final_answer)
            if next_agent == "__END__" or next_agent not in self._agents:
                break

            task = result.final_answer  # 下一跳的输入是当前输出
            current = next_agent

        return PipelineResult(
            success=True,
            steps=steps,
            final_output=pipeline_output,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            total_duration_ms=total_ms,
        )


# ── ParallelPipeline — 并行扇出 ──────────────────────────────────


class ParallelPipeline:
    """并行执行多个 Agent，聚合结果。

    所有 Agent 同时接收同一个 task，各自独立运行，最后合并输出。

    Usage::

        pp = ParallelPipeline()
        pp.add("analyst_1", agent_1)
        pp.add("analyst_2", agent_2)
        pp.add("analyst_3", agent_3)

        result = pp.run("分析 Q3 财报",
                        aggregator=lambda results: "\\n---\\n".join(results.values()))
    """

    def __init__(self, max_workers: int = 5):
        self._agents: dict[str, PipelineAgent] = {}
        self._max_workers = max_workers

    def add(self, name: str, agent: ToolAgent, config: AgentConfig | None = None):
        self._agents[name] = PipelineAgent(name=name, agent=agent, config=config)

    def run(
        self, task: str, aggregator: Callable[[dict[str, str]], str] | None = None
    ) -> PipelineResult:
        if not self._agents:
            return PipelineResult(success=False, error="No agents registered")

        def _run_one(pa: PipelineAgent) -> tuple[str, AgentResult]:
            return pa.name, pa.agent.run(task)

        results: dict[str, AgentResult] = {}
        total_tokens = 0
        total_cost = 0.0
        total_ms = 0.0
        errors: list[str] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {pool.submit(_run_one, pa): pa.name for pa in self._agents.values()}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    name, result = fut.result()
                    results[name] = result
                    total_tokens += result.total_tokens
                    total_cost += result.total_cost_usd
                    total_ms = max(total_ms, result.total_duration_ms)
                except Exception as e:
                    errors.append(f"{futures[fut]}: {e}")

        if errors and not results:
            return PipelineResult(success=False, error="; ".join(errors))

        raw_outputs = {name: r.final_answer for name, r in results.items()}
        if aggregator:
            final = aggregator(raw_outputs)
        else:
            parts = [f"## {name}\n{out}" for name, out in raw_outputs.items()]
            final = "\n\n".join(parts)

        return PipelineResult(
            success=len(errors) == 0,
            steps=[
                {"agent": name, "output": r.final_answer, "tokens": r.total_tokens}
                for name, r in results.items()
            ],
            final_output=final,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            total_duration_ms=total_ms,
            error="; ".join(errors) if errors else "",
        )


# ── RouterAgent — 动态路由 ──────────────────────────────────────

RouterFn = Callable[[str], tuple[str, str]]  # (task, str) → (next_agent_name, rewritten_task)


class RouterAgent:
    """动态路由编排器 — 根据初始化内容选择合适的 Agent。

    使用一个分类器 Agent 先分析任务，再动态路由到目标 Agent。

    Usage::

        ra = RouterAgent(classifier_agent)
        ra.register("code", code_agent, description="代码生成/调试任务")
        ra.register("writing", writer_agent, description="写作/翻译/总结任务")
        ra.register("research", research_agent, description="调研/搜索/分析任务")

        result = ra.run("帮我写一个 Python 快速排序")
    """

    def __init__(self, classifier: ToolAgent):
        self._classifier = classifier
        self._routes: dict[str, tuple[ToolAgent, str]] = {}

    def register(self, name: str, agent: ToolAgent, description: str = ""):
        self._routes[name] = (agent, description)

    def run(self, task: str) -> PipelineResult:
        if not self._routes:
            return PipelineResult(success=False, error="No routes registered")

        # 构建分类提示
        route_desc = "\n".join(f"- {name}: {desc}" for name, (_, desc) in self._routes.items())
        classify_task = (
            f"Analyze the following task and output ONLY the best matching route name "
            f"from the list below. Output just the name, nothing else.\n\n"
            f"Available routes:\n{route_desc}\n\n"
            f"Task: {task}\n\n"
            f"Route:"
        )

        class_result = self._classifier.run(classify_task)
        target = class_result.final_answer.strip().lower()

        # 模糊匹配
        matched = None
        for name in self._routes:
            if name.lower() in target:
                matched = name
                break

        if matched is None:
            # 回退到第一个
            matched = next(iter(self._routes))

        agent, _ = self._routes[matched]
        result = agent.run(task)

        return PipelineResult(
            success=result.success,
            steps=[
                {"agent": "router", "output": f"Classified as: {matched}"},
                {"agent": matched, "output": result.final_answer, "tokens": result.total_tokens},
            ],
            final_output=result.final_answer,
            total_tokens=result.total_tokens,
            total_cost_usd=result.total_cost_usd,
            total_duration_ms=result.total_duration_ms,
        )
