"""
AgentOS v1.1.4 Agent Runtime Middleware Pipeline — 可组合的执行生命周期中间件。

在 Agent 执行的每个阶段（pre-LLM / post-LLM / pre-tool / post-tool）
插入策略检查、日志、脱敏、预算控制等拦截逻辑。

灵感来自 Microsoft Agent Framework 1.0 的 Middleware Pipeline 和 CrewAI Runtime Hooks。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MiddlewarePhase(StrEnum):
    """中间件触发阶段。"""

    PRE_LLM = "pre_llm"  # LLM 调用前
    POST_LLM = "post_llm"  # LLM 调用后、输出解析前
    PRE_TOOL = "pre_tool"  # 工具调用前
    POST_TOOL = "post_tool"  # 工具调用后
    ON_ERROR = "on_error"  # 执行出错时
    ON_START = "on_start"  # Agent 启动时
    ON_COMPLETE = "on_complete"  # Agent 执行完成时


@dataclass
class MiddlewareContext:
    """中间件执行上下文。"""

    phase: MiddlewarePhase
    agent_name: str = ""
    run_id: str = ""
    # LLM 阶段
    prompt: str | None = None
    model_name: str | None = None
    llm_output: str | None = None
    # Tool 阶段
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: Any = None
    # Error
    error: Exception | None = None
    # 额外元数据
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MiddlewareDecision:
    """中间件决策结果。"""

    allow: bool = True
    """是否允许继续执行。"""

    reason: str = ""
    """决策理由。"""

    modified_context: MiddlewareContext | None = None
    """修改后的上下文（如脱敏后的 prompt）。"""

    action: str = "allow"  # allow / warn / block / transform / escalate
    """决策动作。"""

    blocked_by: str = ""
    """阻断方名称。"""


class AgentMiddleware(ABC):
    """Agent 运行时中间件基类。

    每个中间件声明自己监听的阶段，通过 process() 返回决策。
    返回 MiddlewareDecision(allow=False) 阻断执行链。

    __call__ 提供便捷调用：mw(ctx) → process(ctx)。
    """

    name: str = "base_middleware"

    @property
    def phases(self) -> list[MiddlewarePhase]:
        """返回此中间件监听的阶段列表。"""
        return [MiddlewarePhase.PRE_LLM]

    @abstractmethod
    async def process(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        """处理中间件逻辑。返回决策。"""
        ...

    async def __call__(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        """便捷调用，等价于 process(ctx)。"""
        return await self.process(ctx)


# ── 内置中间件 ──────────────────────────────────────────────────────────────


class PIIMaskingMiddleware(AgentMiddleware):
    """PII脱敏中间件：在 pre-LLM 阶段对 prompt 脱敏。"""

    name = "pii_masking"

    @property
    def phases(self) -> list[MiddlewarePhase]:
        return [MiddlewarePhase.PRE_LLM]

    async def process(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        if not ctx.prompt:
            return MiddlewareDecision(allow=True)
        from agentos.security.guard import PIIDetector

        detector = PIIDetector(auto_redact=True)
        sanitized, items = detector.redact(ctx.prompt)
        count = len(items)
        if count > 0:
            new_ctx = MiddlewareContext(**{**ctx.__dict__})
            new_ctx.prompt = sanitized
            new_ctx.metadata["pii_count"] = count
            return MiddlewareDecision(
                allow=True,
                action="transform",
                reason=f"Masked {count} PII instances",
                modified_context=new_ctx,
            )
        return MiddlewareDecision(allow=True)


class BudgetGuardMiddleware(AgentMiddleware):
    """预算守护中间件：pre-LLM 阶段检查预算。"""

    name = "budget_guard"

    def __init__(self, tracker=None, budget_limit: float = 0.0, warn_ratio: float = 0.8):
        self.tracker = tracker
        self.budget_limit = budget_limit
        self.warn_ratio = warn_ratio

    @property
    def phases(self) -> list[MiddlewarePhase]:
        return [MiddlewarePhase.PRE_LLM, MiddlewarePhase.PRE_TOOL]

    async def process(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        if not self.tracker or self.budget_limit <= 0:
            return MiddlewareDecision(allow=True)
        spent = self.tracker.total_cost
        ratio = spent / self.budget_limit
        if ratio >= 1.0:
            return MiddlewareDecision(
                allow=False,
                action="block",
                reason=f"Budget exceeded: ${spent:.4f} / ${self.budget_limit:.2f}",
                blocked_by=self.name,
            )
        if ratio >= self.warn_ratio:
            return MiddlewareDecision(
                allow=True,
                action="warn",
                reason=f"Budget warning: {ratio:.0%} used (${spent:.4f} / ${self.budget_limit:.2f})",
            )
        return MiddlewareDecision(allow=True)


class ToolRiskGuardMiddleware(AgentMiddleware):
    """工具风险守护中间件：pre-tool 阶段根据风险等级决定是否阻断。"""

    name = "tool_risk_guard"

    def __init__(self, max_auto_level: str = "medium"):
        from agentos.tools.risk import ToolRiskLevel

        self.max_auto_level = ToolRiskLevel(max_auto_level)

    @property
    def phases(self) -> list[MiddlewarePhase]:
        return [MiddlewarePhase.PRE_TOOL]

    async def process(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        if not ctx.tool_name:
            return MiddlewareDecision(allow=True)

        from agentos.tools.risk import infer_risk_level

        risk = infer_risk_level(ctx.tool_name, tool_args=ctx.tool_args)

        if risk.requires_user_confirm():
            return MiddlewareDecision(
                allow=False,
                action="escalate",
                reason=f"Tool '{ctx.tool_name}' requires user approval: {risk.description}",
                blocked_by=self.name,
            )

        levels = ["low", "medium", "high", "critical"]
        if levels.index(risk.level.value) > levels.index(self.max_auto_level.value):
            return MiddlewareDecision(
                allow=False,
                action="block",
                reason=f"Tool '{ctx.tool_name}' risk {risk.level.value} exceeds auto limit {self.max_auto_level.value}",
                blocked_by=self.name,
            )

        return MiddlewareDecision(allow=True)


class AuditLogMiddleware(AgentMiddleware):
    """审计日志中间件：在所有阶段记录审计轨迹。"""

    name = "audit_log"

    @property
    def phases(self) -> list[MiddlewarePhase]:
        return [
            MiddlewarePhase.ON_START,
            MiddlewarePhase.PRE_LLM,
            MiddlewarePhase.PRE_TOOL,
            MiddlewarePhase.POST_TOOL,
            MiddlewarePhase.ON_ERROR,
            MiddlewarePhase.ON_COMPLETE,
        ]

    async def process(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        import logging

        logger = logging.getLogger("agentos.audit")
        logger.info(
            f"[{ctx.phase.value}] agent={ctx.agent_name} run={ctx.run_id} "
            f"tool={ctx.tool_name or '-'}"
        )
        return MiddlewareDecision(allow=True)


class TimingMiddleware(AgentMiddleware):
    """计时中间件：记录每个阶段的耗时。"""

    name = "timing"

    def __init__(self):
        self.timings: dict[str, float] = {}
        self._phase_start: dict[str, float] = {}

    @property
    def phases(self) -> list[MiddlewarePhase]:
        return [
            MiddlewarePhase.ON_START,
            MiddlewarePhase.PRE_LLM,
            MiddlewarePhase.POST_LLM,
            MiddlewarePhase.PRE_TOOL,
            MiddlewarePhase.POST_TOOL,
            MiddlewarePhase.ON_COMPLETE,
            MiddlewarePhase.ON_ERROR,
        ]

    async def process(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        import time

        phase_key = f"{ctx.phase.value}.{ctx.tool_name or ctx.agent_name or 'default'}"
        self._phase_start[phase_key] = time.monotonic()
        self.timings[phase_key] = self.timings.get(phase_key, 0.0)
        return MiddlewareDecision(allow=True)

    def get_timings(self) -> dict[str, float]:
        return dict(self.timings)

    def total_ms(self) -> float:
        return sum(self.timings.values()) * 1000


class RetryMiddleware(AgentMiddleware):
    """重试中间件：在 ON_ERROR 阶段自动重试。"""

    name = "retry"

    def __init__(self, max_retries: int = 2, backoff_base: float = 1.0):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._retry_counts: dict[str, int] = {}

    @property
    def phases(self) -> list[MiddlewarePhase]:
        return [MiddlewarePhase.ON_ERROR]

    async def process(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        import asyncio

        run_key = ctx.run_id or "default"
        count = self._retry_counts.get(run_key, 0)

        if count >= self.max_retries:
            return MiddlewareDecision(
                allow=True,
                action="warn",
                reason=f"Max retries ({self.max_retries}) exhausted",
            )

        self._retry_counts[run_key] = count + 1
        delay = self.backoff_base * (2**count)
        await asyncio.sleep(delay)

        return MiddlewareDecision(
            allow=True,
            action="warn",
            reason=f"Retry {count + 1}/{self.max_retries} after {delay:.1f}s",
        )

    def reset(self, run_id: str = "") -> None:
        if run_id:
            self._retry_counts.pop(run_id, None)
        else:
            self._retry_counts.clear()


# ── 中间件管道 ──────────────────────────────────────────────────────────────


class MiddlewarePipeline:
    """编排多个中间件按阶段执行。

    每个阶段：
    1. 筛选监听该阶段的中间件
    2. 按注册顺序依次执行
    3. 任一返回 allow=False 即阻断
    4. 若返回 modified_context 则传递给后续中间件
    """

    def __init__(self, middlewares: list[AgentMiddleware] | None = None):
        self._middlewares: list[AgentMiddleware] = list(middlewares or [])

    def add(self, middleware: AgentMiddleware) -> MiddlewarePipeline:
        """添加中间件，返回自身以支持链式调用。"""
        self._middlewares.append(middleware)
        return self

    def remove(self, name: str) -> None:
        self._middlewares = [m for m in self._middlewares if m.name != name]

    @property
    def middleware_names(self) -> list[str]:
        return [m.name for m in self._middlewares]

    async def execute_phase(
        self,
        phase: MiddlewarePhase,
        ctx: MiddlewareContext,
    ) -> MiddlewareDecision:
        """执行指定阶段的所有中间件。"""
        current_ctx = ctx
        for mw in self._middlewares:
            if phase not in mw.phases:
                continue
            decision = await mw.process(current_ctx)
            if not decision.allow:
                decision.blocked_by = mw.name
                return decision
            if decision.modified_context:
                current_ctx = decision.modified_context
        return MiddlewareDecision(allow=True, modified_context=current_ctx)

    async def on_start(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        return await self.execute_phase(MiddlewarePhase.ON_START, ctx)

    async def pre_llm(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        return await self.execute_phase(MiddlewarePhase.PRE_LLM, ctx)

    async def post_llm(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        return await self.execute_phase(MiddlewarePhase.POST_LLM, ctx)

    async def pre_tool(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        return await self.execute_phase(MiddlewarePhase.PRE_TOOL, ctx)

    async def post_tool(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        return await self.execute_phase(MiddlewarePhase.POST_TOOL, ctx)

    async def on_error(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        return await self.execute_phase(MiddlewarePhase.ON_ERROR, ctx)

    async def on_complete(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        return await self.execute_phase(MiddlewarePhase.ON_COMPLETE, ctx)

    async def run(
        self,
        ctx: MiddlewareContext,
        phases: list[MiddlewarePhase] | None = None,
    ) -> MiddlewareDecision:
        """便捷方法：按阶段列表依次执行管道。

        phases 默认为完整的生命周期序列。
        """
        if phases is None:
            phases = [
                MiddlewarePhase.ON_START,
                MiddlewarePhase.PRE_LLM,
                MiddlewarePhase.POST_LLM,
                MiddlewarePhase.ON_COMPLETE,
            ]
        decision = MiddlewareDecision(allow=True, modified_context=ctx)
        for phase in phases:
            current_ctx = decision.modified_context or ctx
            decision = await self.execute_phase(phase, current_ctx)
            if not decision.allow:
                return decision
        return decision
