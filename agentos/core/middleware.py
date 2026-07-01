"""
AgentOS v1.1.4 Agent Runtime Middleware Pipeline — 可组合的执行生命周期中间件。

在 Agent 执行的每个阶段（pre-LLM / post-LLM / pre-tool / post-tool）
插入策略检查、日志、脱敏、预算控制等拦截逻辑。

灵感来自 Microsoft Agent Framework 1.0 的 Middleware Pipeline 和 CrewAI Runtime Hooks。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class MiddlewarePhase(str, Enum):
    """中间件触发阶段。"""

    PRE_LLM = "pre_llm"          # LLM 调用前
    POST_LLM = "post_llm"        # LLM 调用后、输出解析前
    PRE_TOOL = "pre_tool"        # 工具调用前
    POST_TOOL = "post_tool"      # 工具调用后
    ON_ERROR = "on_error"        # 执行出错时
    ON_START = "on_start"        # Agent 启动时
    ON_COMPLETE = "on_complete"  # Agent 执行完成时


@dataclass
class MiddlewareContext:
    """中间件执行上下文。"""

    phase: MiddlewarePhase
    agent_name: str = ""
    run_id: str = ""
    # LLM 阶段
    prompt: Optional[str] = None
    model_name: Optional[str] = None
    llm_output: Optional[str] = None
    # Tool 阶段
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Any = None
    # Error
    error: Optional[Exception] = None
    # 额外元数据
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MiddlewareDecision:
    """中间件决策结果。"""

    allow: bool = True
    """是否允许继续执行。"""

    reason: str = ""
    """决策理由。"""

    modified_context: Optional[MiddlewareContext] = None
    """修改后的上下文（如脱敏后的 prompt）。"""

    action: str = "allow"  # allow / warn / block / transform / escalate
    """决策动作。"""

    blocked_by: str = ""
    """阻断方名称。"""


class AgentMiddleware(ABC):
    """Agent 运行时中间件基类。

    每个中间件声明自己监听的阶段，通过 process() 返回决策。
    返回 MiddlewareDecision(allow=False) 阻断执行链。
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
        from agentos.security.guard import PIISanitizer
        sanitized, count = PIISanitizer.sanitize(ctx.prompt)
        if count > 0:
            new_ctx = MiddlewareContext(**{**ctx.__dict__})
            new_ctx.prompt = sanitized
            new_ctx.metadata["pii_count"] = count
            return MiddlewareDecision(
                allow=True, action="transform",
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
                allow=False, action="block",
                reason=f"Budget exceeded: ${spent:.4f} / ${self.budget_limit:.2f}",
                blocked_by=self.name,
            )
        if ratio >= self.warn_ratio:
            return MiddlewareDecision(
                allow=True, action="warn",
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
                allow=False, action="escalate",
                reason=f"Tool '{ctx.tool_name}' requires user approval: {risk.description}",
                blocked_by=self.name,
            )

        levels = ["low", "medium", "high", "critical"]
        if levels.index(risk.level.value) > levels.index(self.max_auto_level.value):
            return MiddlewareDecision(
                allow=False, action="block",
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
            MiddlewarePhase.ON_START, MiddlewarePhase.PRE_LLM,
            MiddlewarePhase.PRE_TOOL, MiddlewarePhase.POST_TOOL,
            MiddlewarePhase.ON_ERROR, MiddlewarePhase.ON_COMPLETE,
        ]

    async def process(self, ctx: MiddlewareContext) -> MiddlewareDecision:
        import logging
        logger = logging.getLogger("agentos.audit")
        logger.info(
            f"[{ctx.phase.value}] agent={ctx.agent_name} run={ctx.run_id} "
            f"tool={ctx.tool_name or '-'}"
        )
        return MiddlewareDecision(allow=True)


# ── 中间件管道 ──────────────────────────────────────────────────────────────

class MiddlewarePipeline:
    """编排多个中间件按阶段执行。

    每个阶段：
    1. 筛选监听该阶段的中间件
    2. 按注册顺序依次执行
    3. 任一返回 allow=False 即阻断
    4. 若返回 modified_context 则传递给后续中间件
    """

    def __init__(self, middlewares: Optional[list[AgentMiddleware]] = None):
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
