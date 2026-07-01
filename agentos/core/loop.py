"""
AgentOS v0.70 核心循环 — Gemini + Metrics + CostAnalytics 集成版。
v0.40: Swarm多Agent并行、Agent间通信、语义缓存、任务队列。
v0.70: MetricsCollector、CostAnalytics实时监控。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable

from agentos.core.context import ContextManager
from agentos.tools.registry import ToolRegistry
from agentos.models.router import ModelRouter, AllModelsFailed
from agentos.security.sandbox import SandboxManager
from agentos.observability.tracer import Tracer
from agentos.observability.metrics import MetricsCollector
from agentos.observability.cost_analytics import CostAnalytics
from agentos.core.streaming import StreamChunk, StreamEvent
from agentos.storage.base import CheckpointStore
from agentos.checkpoint.base import Checkpoint, CheckpointMetadata, CheckpointBackend
from agentos.cost.tracker import CostTracker
from agentos.swarm.coordinator import SwarmCoordinator, SwarmTopology, AgentRole, SwarmResult, MessageBus
from agentos.comm.layer import CommunicationLayer
from agentos.cache.llm_cache import LLMCache
from agentos.multimodal.manager import MultimodalManager


class LoopState(str, Enum):

    """主循环状态。"""

    RUNNING = "running"
    PAUSED = "paused"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentResult:
    """Agent 主循环的最终运行结果。"""

    output: str
    iterations: int
    tokens_used: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    tool_calls_total: int = 0
    reflections_count: int = 0
    human_interrupts: int = 0
    final_state: LoopState = LoopState.COMPLETED
    error: str | None = None
    # v0.40
    swarm_result: SwarmResult | None = None
    cache_hit: bool = False


@dataclass
class LoopConfig:
    """Agent 主循环的运行时配置。"""

    max_iterations: int = 100
    max_retries_per_step: int = 2
    step_timeout_seconds: int = 120
    enable_streaming: bool = False
    enable_checkpoints: bool = True
    checkpoint_interval: int = 5
    # v0.30
    enable_reflection: bool = True
    reflection_frequency: int = 3
    max_reflection_loops: int = 3
    enable_self_critique: bool = True
    enable_human_in_the_loop: bool = False
    human_approval_trigger: str = "high_risk"
    enable_cost_tracking: bool = True
    auto_select_model: bool = True
    # v0.40
    enable_swarm: bool = False
    swarm_topology: str = "sequential"
    swarm_roles: list[AgentRole] = field(default_factory=list)
    max_parallel_agents: int = 4
    enable_comm_layer: bool = True
    enable_semantic_cache: bool = True
    # v1.11.0 — long-running task support
    checkpoint_backend: CheckpointBackend | None = None  # Full checkpoint backend for crash recovery
    enable_auto_paging: bool = True    # Auto-evict old memories when context fills
    auto_page_threshold: float = 0.85  # Page out at 85% context window usage


class MaxIterationsExceeded(Exception):

    """超出最大迭代次数异常。"""

    pass


class HumanInterruptNeeded(Exception):

    """需要人工介入异常。"""

    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}


@dataclass
class ReflectionResult:
    """反思结果。"""
    quality_score: float
    issues: list[str]
    suggestions: list[str]
    should_continue: bool
    new_plan: str | None = None


class AgentLoop:
    """v0.30 核心循环 — Reflection + HITL + Self-Critique + 自动路由 + 成本追踪。"""

    def __init__(
        self,
        model_router: ModelRouter,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        sandbox_manager: SandboxManager | None = None,
        tracer: Tracer | None = None,
        checkpoint_store: CheckpointStore | None = None,
        checkpoint_backend: CheckpointBackend | None = None,
        cost_tracker: CostTracker | None = None,
        config: LoopConfig | None = None,
        on_iteration: Callable | None = None,
        on_stream: Callable[[StreamChunk], None] | None = None,
        on_human_interrupt: Callable[[str, dict], str | None] | None = None,
        on_reflection: Callable[[ReflectionResult], None] | None = None,
        metrics_collector: MetricsCollector | None = None,
        cost_analytics: CostAnalytics | None = None,
    ):
        self.model_router = model_router
        self.tool_registry = tool_registry
        self.context_manager = context_manager
        self.sandbox_manager = sandbox_manager
        self.tracer = tracer or Tracer.noop()
        self.checkpoint_store = checkpoint_store
        self.cost_tracker = cost_tracker or CostTracker.noop()
        self.config = config or LoopConfig()
        self.checkpoint_backend = checkpoint_backend  # v1.11.0 full checkpoint integration
        self._auto_page_callback: Callable | None = None  # v1.11.0 auto-paging callback
        self.on_iteration = on_iteration
        self.on_stream = on_stream
        self.on_human_interrupt = on_human_interrupt
        self.on_reflection = on_reflection
        self.metrics = metrics_collector or MetricsCollector()
        self.cost_analytics = cost_analytics or CostAnalytics()
        self._cancelled = False
        self._reflection_history: list[ReflectionResult] = []
        self._human_interrupts = 0

    # ── 运行入口 ──────────────────────────────────

    async def run(self, task: str, session_id: str = "") -> AgentResult:
        start_time = time.time()
        self.context_manager.init_session(session_id, task)

        if self.config.auto_select_model:
            await self._auto_route_model(task)

        iteration = await self._try_restore(session_id)
        tool_calls_total = 0
        reflection_loops = 0

        while iteration < self.config.max_iterations and not self._cancelled:
            iteration += 1

            if self.config.enable_reflection and iteration % self.config.reflection_frequency == 0:
                with self.tracer.step("reflection"):
                    reflection = await self._reflect(session_id)
                    self._reflection_history.append(reflection)
                if not reflection.should_continue and reflection_loops < self.config.max_reflection_loops:
                    reflection_loops += 1
                    if reflection.new_plan:
                        self.context_manager.update_plan(reflection.new_plan)
                    continue

            try:
                with self.tracer.step(f"loop_{iteration}"):
                    step_result = await self._execute_step_sync(iteration, session_id)

                if step_result.is_terminal:
                    duration_ms = (time.time() - start_time) * 1000
                    return AgentResult(
                        output=step_result.content,
                        iterations=iteration,
                        tokens_used=self.tracer.token_summary(),
                        cost_usd=self.cost_tracker.total_cost,
                        duration_ms=duration_ms,
                        tool_calls_total=tool_calls_total,
                        reflections_count=len(self._reflection_history),
                        human_interrupts=self._human_interrupts,
                    )

                if step_result.tool_results:
                    tool_calls_total += len(step_result.tool_results)

                if self.on_iteration:
                    self.on_iteration(iteration, step_result.tool_results or [])

            except HumanInterruptNeeded as e:
                self._human_interrupts += 1
                if self.on_human_interrupt:
                    feedback = self.on_human_interrupt(str(e), e.context)
                    if feedback:
                        self.context_manager.append_user_message(feedback)
                continue

            except StepTimeoutError:
                return AgentResult(output="", iterations=iteration, final_state=LoopState.FAILED, error="Step timeout")

            if self.config.enable_checkpoints and iteration % self.config.checkpoint_interval == 0:
                await self._save_checkpoint(session_id, iteration)

        raise MaxIterationsExceeded(f"超过 {self.config.max_iterations} 步")

    # ── Reflection ────────────────────────────────

    async def _reflect(self, session_id: str) -> ReflectionResult:
        prompt = f"""你是一个反思者。审核以下Agent执行过程：

任务: {self.context_manager.current_task}
已执行: {self.context_manager.step_count} 步

评估并返回JSON:
{{"quality_score": 0.0-1.0, "issues": [...], "suggestions": [...], "should_continue": true/false, "new_plan": "如果调整，新计划"}}"""

        resp = await self.model_router.call_simple(prompt)
        try:
            import json
            d = json.loads(resp)
            result = ReflectionResult(
                quality_score=d.get("quality_score", 0.5),
                issues=d.get("issues", []),
                suggestions=d.get("suggestions", []),
                should_continue=d.get("should_continue", True),
                new_plan=d.get("new_plan"),
            )
        except Exception:
            result = ReflectionResult(0.5, [], [], True)
        if self.on_reflection:
            self.on_reflection(result)
        return result

    # ── Self-Critique ─────────────────────────────

    async def _self_critique(self, text: str) -> str:
        if not self.config.enable_self_critique:
            return text
        prompt = f"""审视以下回答，找出逻辑错误或不准确之处。如果已足够好就原样返回。

{text[:3000]}"""
        improved = await self.model_router.call_simple(prompt)
        return improved or text

    # ── Auto Route ────────────────────────────────

    async def _auto_route_model(self, task: str):
        score = self._estimate_complexity(task)
        if score > 0.7:
            self.model_router.set_preferred("deepseek-r1")
        elif score > 0.4:
            self.model_router.set_preferred("kimi-k2.6")
        else:
            self.model_router.set_preferred("deepseek-v3.1")

    def _estimate_complexity(self, task: str) -> float:
        kw = ["分析", "对比", "设计", "架构", "review", "refactor", "实现", "优化", "诊断", "troubleshoot", "debug", "deploy", "migrate", "安全", "security"]
        score = sum(0.15 for k in kw if k in task.lower())
        return min(score + min(len(task) / 2000, 0.3), 1.0)

    # ── 步骤执行 ──────────────────────────────────

    async def _execute_step_sync(self, iteration: int, session_id: str) -> "StepResult":
        last_error = None
        for attempt in range(self.config.max_retries_per_step + 1):
            try:
                return await asyncio.wait_for(self._do_step(iteration, session_id), timeout=self.config.step_timeout_seconds)
            except asyncio.TimeoutError:
                last_error = StepTimeoutError(f"Step {iteration} timeout")
            except AllModelsFailed as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
        raise last_error

    async def _do_step(self, iteration: int, session_id: str) -> "StepResult":
        ctx = self.context_manager.build_context(
            model_type=self.model_router.model_type,
            tools=self.tool_registry.get_schemas_for_model(self.model_router.model_type),
        )

        # v1.11.0 — auto-page old memories if context nearing limit
        if self.config.enable_auto_paging and self._auto_page_callback:
            usage_ratio = self.context_manager.estimate_context_usage()
            if usage_ratio > self.config.auto_page_threshold:
                page_count = await self._auto_page_callback(usage_ratio)

        resp = await self.model_router.call(ctx)

        # 成本记录
        if self.config.enable_cost_tracking and hasattr(resp, "usage"):
            self.cost_tracker.record(self.model_router.current_model, resp.usage)

        if not resp.tool_calls:
            if self.config.enable_self_critique:
                improved = await self._self_critique(resp.content)
                return StepResult(content=improved, is_terminal=True)
            return StepResult(content=resp.content, is_terminal=True)

        # HITL 检查
        if self.config.enable_human_in_the_loop:
            for tc in resp.tool_calls:
                if self._is_high_risk(tc):
                    raise HumanInterruptNeeded(f"高风险操作需确认: {tc.name}", {"tool": tc.name, "args": tc.arguments})

        groups = self._group_independent_calls(resp.tool_calls)
        all_results = []
        for group in groups:
            sandbox = self.sandbox_manager.get_sandbox(session_id) if self.sandbox_manager else None
            batch_results = await self.tool_registry.execute_batch(group, sandbox=sandbox)
            all_results.extend(batch_results)

        self.context_manager.append_tool_results(all_results)
        return StepResult(content="", is_terminal=False, tool_results=all_results)

    def _is_high_risk(self, tc) -> bool:
        risky = ["delete", "rm", "uninstall", "format", "sudo", "kill", "drop"]
        name = tc.name.lower() if hasattr(tc, "name") else tc.get("name", "").lower()
        return any(r in name for r in risky)

    def _group_independent_calls(self, tool_calls: list) -> list[list]:
        if len(tool_calls) <= 1:
            return [tool_calls] if tool_calls else []
        groups: list[list] = []
        for call in tool_calls:
            for group in groups:
                if not self._has_conflict(call, group):
                    group.append(call)
                    break
            else:
                groups.append([call])
        return groups

    def _has_conflict(self, call, group: list) -> bool:
        write_paths = set()
        for tc in group:
            tool = self.tool_registry.get(tc.name)
            if tool and tool.is_write_operation(tc.arguments):
                if p := tool.extract_target_path(tc.arguments):
                    write_paths.add(p)
        cur = self.tool_registry.get(call.name)
        if cur and cur.is_read_operation(call.arguments):
            return cur.extract_target_path(call.arguments) in write_paths
        return False

    # ── v1.11.0 全量 Checkpoint (完整状态快照) ────

    async def _save_checkpoint(self, session_id: str, iteration: int):
        """Save full runtime state snapshot via CheckpointBackend."""
        backend = self.checkpoint_backend
        if not backend:
            # Fallback to thin CheckpointStore
            if not self.checkpoint_store:
                return
            snap = {
                "session_id": session_id, "iteration": iteration,
                "messages": [{"role": m.role, "content": m.content} for m in self.context_manager._messages],
                "timestamp": time.time(),
            }
            await self.checkpoint_store.save(session_id, snap)
            return

        # Full checkpoint via CheckpointBackend
        try:
            from datetime import datetime, timezone
            import uuid

            checkpoint_id = f"ckpt-{session_id}-{iteration:06d}"
            parent_id = getattr(self, '_last_checkpoint_id', None)

            cp = Checkpoint(
                metadata=CheckpointMetadata(
                    thread_id=session_id,
                    checkpoint_id=checkpoint_id,
                    step=iteration,
                    parent_checkpoint_id=parent_id,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    tags=["auto", f"iter_{iteration}"],
                ),
                messages=[{"role": m.role, "content": m.content} for m in self.context_manager._messages],
                state={
                    "iteration": iteration,
                    "task": self.context_manager.current_task,
                    "session_id": session_id,
                    "cost_usd": self.cost_tracker.total_cost,
                    "reflections": len(self._reflection_history),
                    "human_interrupts": self._human_interrupts,
                    "loop_state": self.context_manager.current_state if hasattr(self.context_manager, 'current_state') else "running",
                },
                tools_result={},
                next_node="loop",
            )
            await backend.put(cp)
            self._last_checkpoint_id = checkpoint_id

        except Exception as e:
            pass  # Checkpoint failure must not crash the loop

    async def _try_restore(self, session_id: str) -> int:
        """Restore full state from last checkpoint. Returns iteration to resume from."""
        backend = self.checkpoint_backend
        if not backend:
            # Fallback to thin CheckpointStore
            if not self.checkpoint_store or not self.config.enable_checkpoints:
                return 0
            snap = await self.checkpoint_store.load(session_id)
            if not snap:
                return 0
            iter_count = snap.get("iteration", 0)
            if iter_count > 0:
                msgs = snap.get("messages", [])
                for msg in msgs:
                    self.context_manager.append_message(msg["role"], msg["content"])
            return iter_count

        if not self.config.enable_checkpoints:
            return 0

        try:
            latest = await backend.get_latest(session_id)
            if not latest:
                return 0
            self._last_checkpoint_id = latest.metadata.checkpoint_id
            iter_count = latest.metadata.step

            # Restore messages
            for msg in latest.messages:
                self.context_manager.append_message(msg.get("role", "user"), msg.get("content", ""))

            # Restore state
            state = latest.state
            self._human_interrupts = state.get("human_interrupts", 0)

            return iter_count
        except Exception:
            return 0

    def set_auto_paging(self, callback: Callable):
        """Register callback for automatic memory paging (v1.11.0)."""
        self._auto_page_callback = callback

    def cancel(self):
        self._cancelled = True

    # ── v0.40 Swarm执行 ──────────────────────────

    async def run_swarm(self, task: str, roles: list[AgentRole] | None = None) -> AgentResult:
        """以Swarm模式执行任务 — 多Agent协作。"""
        start_time = time.time()
        roles = roles or self.config.swarm_roles
        if not roles:
            return AgentResult(output="[Swarm] No roles defined", iterations=0, final_state=LoopState.FAILED, error="No roles")

        topology = SwarmTopology(self.config.swarm_topology)
        comm_layer = CommunicationLayer() if self.config.enable_comm_layer else None

        swarm = SwarmCoordinator(
            router=self.model_router,
            tool_registry=self.tool_registry,
            topology=topology,
            max_parallel=self.config.max_parallel_agents,
        )
        swarm.register_roles(roles)

        swarm_result = await swarm.execute(task, roles)
        duration_ms = (time.time() - start_time) * 1000

        return AgentResult(
            output=swarm_result.combined_output,
            iterations=1,
            cost_usd=self.cost_tracker.total_cost,
            duration_ms=duration_ms,
            tool_calls_total=0,
            reflections_count=0,
            human_interrupts=0,
            final_state=LoopState.COMPLETED,
            swarm_result=swarm_result,
        )


class StepTimeoutError(Exception):

    """步骤超时异常。"""

    pass


@dataclass
class StepResult:
    """步骤执行结果。"""
    content: str
    is_terminal: bool = False
    tool_results: list | None = None
