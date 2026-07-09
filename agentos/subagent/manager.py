"""
子Agent管理 — Fork隔离 + Swarm并行 + A2A委派 + 父子通信。
基因来源: Claude Code (Fork) + Cursor (Swarm)
v1.3.15: +Parent-Child 通信（状态共享、心跳、生命周期）
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .parent_child import (
    ChildContext,
    ChildHandle,
    ChildStatus,
    SharedState,
)


class SubAgentMode(StrEnum):
    """子 Agent 模式枚举。"""

    FORK = "fork"
    SWARM = "swarm"
    A2A = "a2a"


@dataclass
class SubAgentSpec:
    """子 Agent 规格。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    task: str = ""
    mode: SubAgentMode = SubAgentMode.FORK
    model: str = "kimi-k2.6"
    max_iterations: int = 50
    timeout: float | None = None
    heartbeat_interval: float = 2.0


@dataclass
class SubAgentResult:
    """子 Agent 执行结果。"""

    agent_id: str
    output: str
    iterations: int
    error: str | None = None
    handle: ChildHandle | None = None

    def summarize(self) -> str:
        if self.error:
            return f"[SubAgent {self.agent_id}] FAILED: {self.error}"
        return (
            f"[SubAgent {self.agent_id}] Completed in {self.iterations} steps.\n"
            f"Result: {self.output[:500]}"
        )


class SubAgentManager:
    """子Agent管理器 — Fork/Swarm/A2A + 父子通信。

    用法::

        mgr = SubAgentManager()

        # Fork 模式
        result = await mgr.spawn_fork("分析这份报告")

        # Swarm 模式
        results = await mgr.spawn_swarm(["任务A", "任务B"])

        # 管控子Agent
        handle = mgr.get_handle(result.agent_id)
        await handle.pause()
        await handle.resume()
        await handle.cancel()
        status = handle.get_status()
    """

    MAX_SWARM_SIZE = 8

    def __init__(self):
        self._agents: dict[str, ChildHandle] = {}
        self._shared_state = SharedState()  # 全局共享状态

    @property
    def shared_state(self) -> SharedState:
        """全局父子共享状态。"""
        return self._shared_state

    @property
    def active_children(self) -> int:
        """当前活跃的子Agent数。"""
        return sum(
            1
            for h in self._agents.values()
            if h.status in (ChildStatus.RUNNING, ChildStatus.PAUSED)
        )

    def get_handle(self, agent_id: str) -> ChildHandle | None:
        """根据 agent_id 获取子Agent句柄。"""
        return self._agents.get(agent_id)

    def list_children(self) -> list[dict[str, Any]]:
        """列出所有子Agent状态。"""
        return [h.get_status() for h in self._agents.values()]

    async def cancel_all(self) -> None:
        """取消所有子Agent。"""
        tasks = [h.cancel() for h in self._agents.values()]
        await asyncio.gather(*tasks)

    async def spawn_fork(
        self,
        task: str,
        model: str = "kimi-k2.6",
        run_func: Callable[[SubAgentSpec, ChildContext], Awaitable[tuple[str, int]]] | None = None,
        timeout: float | None = None,
        heartbeat_interval: float = 2.0,
    ) -> SubAgentResult:
        """Fork模式：子Agent在干净上下文中运行，父只拿摘要。

        run_func(spec, ctx) -> (output, iterations)
        """
        spec = SubAgentSpec(
            task=task,
            mode=SubAgentMode.FORK,
            model=model,
            timeout=timeout,
            heartbeat_interval=heartbeat_interval,
        )

        handle = ChildHandle(
            agent_id=spec.id,
            task=task,
            mode=spec.mode.value,
            timeout=timeout,
            heartbeat_interval=heartbeat_interval,
        )
        self._agents[spec.id] = handle
        ctx = handle.create_context()
        handle.info.status = ChildStatus.RUNNING

        if run_func:
            try:
                output, iterations = await run_func(spec, ctx)
                if handle._cancel_flag:
                    handle.info.status = ChildStatus.CANCELLED
                    return SubAgentResult(
                        agent_id=spec.id,
                        output=output,
                        iterations=iterations,
                        error="Cancelled by parent",
                        handle=handle,
                    )
                await ctx.done(output)
                handle.info.output = output
                handle.info.iterations = iterations
                handle.info.status = ChildStatus.COMPLETED
                return SubAgentResult(
                    agent_id=spec.id,
                    output=output,
                    iterations=iterations,
                    handle=handle,
                )
            except asyncio.CancelledError:
                handle.info.status = ChildStatus.CANCELLED
                return SubAgentResult(
                    agent_id=spec.id,
                    output="",
                    iterations=handle.info.iterations,
                    error="Cancelled by parent",
                    handle=handle,
                )
            except Exception as e:
                await ctx.fail(str(e))
                handle.info.status = ChildStatus.FAILED
                handle.info.error = str(e)
                return SubAgentResult(
                    agent_id=spec.id,
                    output="",
                    iterations=handle.info.iterations,
                    error=str(e),
                    handle=handle,
                )

        handle.info.status = ChildStatus.COMPLETED
        return SubAgentResult(
            agent_id=spec.id,
            output=f"Fork agent would process: {task}",
            iterations=0,
            handle=handle,
        )

    async def spawn_swarm(
        self,
        tasks: list[str],
        model: str = "kimi-k2.6",
        run_func: Callable[[SubAgentSpec, ChildContext], Awaitable[tuple[str, int]]] | None = None,
        timeout: float | None = None,
        heartbeat_interval: float = 2.0,
    ) -> list[SubAgentResult]:
        """Swarm模式：最多8个Agent并行处理。"""
        agents = []
        for i, task in enumerate(tasks[: self.MAX_SWARM_SIZE]):
            spec = SubAgentSpec(
                task=task,
                mode=SubAgentMode.SWARM,
                model=model,
                timeout=timeout,
                heartbeat_interval=heartbeat_interval,
            )
            agents.append(spec)

        async def run_one(spec: SubAgentSpec) -> SubAgentResult:
            handle = ChildHandle(
                agent_id=spec.id,
                task=spec.task,
                mode=spec.mode.value,
                timeout=timeout,
                heartbeat_interval=heartbeat_interval,
            )
            self._agents[spec.id] = handle
            ctx = handle.create_context()
            handle.info.status = ChildStatus.RUNNING

            if run_func:
                try:
                    output, iterations = await run_func(spec, ctx)
                    if handle._cancel_flag:
                        handle.info.status = ChildStatus.CANCELLED
                        return SubAgentResult(
                            agent_id=spec.id,
                            output=output,
                            iterations=iterations,
                            error="Cancelled by parent",
                            handle=handle,
                        )
                    await ctx.done(output)
                    handle.info.output = output
                    handle.info.iterations = iterations
                    handle.info.status = ChildStatus.COMPLETED
                    return SubAgentResult(
                        agent_id=spec.id,
                        output=output,
                        iterations=iterations,
                        handle=handle,
                    )
                except Exception as e:
                    await ctx.fail(str(e))
                    handle.info.status = ChildStatus.FAILED
                    handle.info.error = str(e)
                    return SubAgentResult(
                        agent_id=spec.id,
                        output="",
                        iterations=handle.info.iterations,
                        error=str(e),
                        handle=handle,
                    )

            handle.info.status = ChildStatus.COMPLETED
            return SubAgentResult(
                agent_id=spec.id,
                output=f"Swarm agent would process: {spec.task}",
                iterations=0,
                handle=handle,
            )

        return await asyncio.gather(*[run_one(a) for a in agents])

    def split_task(self, task: str) -> list[str]:
        """将复杂任务拆分为子任务。"""
        if "\n" in task:
            return [t.strip() for t in task.split("\n") if t.strip()]
        return [task]

    async def monitor_heartbeats(self, interval: float = 1.0) -> None:
        """后台心跳监控协程，检测超时和失联子Agent。

        用法::

            asyncio.create_task(mgr.monitor_heartbeats())
        """
        while True:
            await asyncio.sleep(interval)
            for agent_id, handle in list(self._agents.items()):
                running = handle.status in (ChildStatus.RUNNING, ChildStatus.PAUSED)
                if running and handle.check_timeout():
                    await handle.cancel()
                    handle.info.status = ChildStatus.TIMEOUT
                    handle.info.error = f"Timeout after {handle.info.timeout}s"
                elif running and handle.check_heartbeat_timeout():
                    handle.info.status = ChildStatus.FAILED
                    handle.info.error = "Heartbeat lost — child agent unresponsive"

    async def cleanup(self, max_age_seconds: float = 3600.0) -> int:
        """清理已完成/失败/取消且超过 max_age_seconds 的句柄。返回清理数。"""
        now = time.time()
        cleaned = 0
        terminal = (
            ChildStatus.COMPLETED,
            ChildStatus.FAILED,
            ChildStatus.CANCELLED,
            ChildStatus.TIMEOUT,
        )
        for agent_id, handle in list(self._agents.items()):
            if handle.status in terminal:
                age = now - handle.info.spawned_at
                if age > max_age_seconds:
                    del self._agents[agent_id]
                    cleaned += 1
        return cleaned
