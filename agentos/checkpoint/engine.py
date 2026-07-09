"""
AgentOS v1.14.7 — Fine-grained Checkpoint Engine.

LangGraph-aligned step-level checkpointing with time travel.
Every tool_call, llm_call, and state transition triggers a snapshot.

Key differences from v1.14.6 checkpoint module:
- Step-level (not task-level) granularity
- Time travel: rewind to any checkpoint and replay from there
- Branching: fork execution from any historical checkpoint
- Delta snapshots: only store state diffs when possible
- Automatic pruning: configurable retention policies

Usage:
    engine = CheckpointEngine(checkpointer=SQLiteCheckpointer("checkpoints.db"))

    # Auto-snapshot around tool calls
    @engine.snapshot_on("tool_call")
    async def my_tool(...): ...

    # Time travel
    await engine.rewind("checkpoint-42")
    # Now continue execution from that point

    # Branch
    branch_id = await engine.branch("checkpoint-42", "bugfix-experiment")
"""

from __future__ import annotations

import functools
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agentos.checkpoint.base import (
    Checkpoint,
    CheckpointBackend,
    CheckpointMetadata,
)

logger = logging.getLogger(__name__)


# ── Types ────────────────────────────────────


class SnapshotTrigger(StrEnum):
    """快照触发点。"""

    TOOL_CALL = "tool_call"  # 工具调用前后
    LLM_CALL = "llm_call"  # LLM 调用前后
    STATE_CHANGE = "state_change"  # Agent 状态变更
    TASK_BOUNDARY = "task_boundary"  # 任务开始/结束
    MANUAL = "manual"  # 显式调用
    INTERVAL = "interval"  # 定时快照


class CheckpointGC(StrEnum):
    """检查点垃圾回收策略。"""

    KEEP_ALL = "keep_all"
    KEEP_LAST_N = "keep_last_n"
    KEEP_AGE = "keep_age"  # 仅保留 N 秒内
    KEEP_MILESTONES = "keep_milestones"  # 仅保留首尾 + N 个分位点


@dataclass
class SnapshotConfig:
    """快照配置。"""

    triggers: set[SnapshotTrigger] = field(
        default_factory=lambda: {
            SnapshotTrigger.MANUAL,
            SnapshotTrigger.TOOL_CALL,
            SnapshotTrigger.LLM_CALL,
            SnapshotTrigger.STATE_CHANGE,
        }
    )
    gc_policy: CheckpointGC = CheckpointGC.KEEP_LAST_N
    gc_param: int = 100  # keep_last_n 的 n 或 keep_age 的秒数
    delta_snapshots: bool = True  # 是否使用增量快照（减少存储）
    max_snapshot_size_mb: float = 10.0


@dataclass
class TimeTravelResult:
    """时间旅行操作结果。"""

    checkpoint: Checkpoint
    thread_id: str
    rewind_depth: int  # 回退了几个 checkpoint
    snapshot_count_before: int  # 重放前的快照数
    can_replay: bool = True


# ── Checkpoint Engine ────────────────────────


class CheckpointEngine:
    """细粒度 Checkpoint 引擎。

    提供每步快照、时间旅行、分支等能力。
    """

    def __init__(
        self,
        checkpointer: CheckpointBackend,
        config: SnapshotConfig | None = None,
    ):
        self._checkpointer = checkpointer
        self._config = config or SnapshotConfig()
        self._snapshot_counters: dict[str, int] = {}  # thread_id → step counter
        self._last_delta: dict[str, dict[str, Any]] = {}  # thread_id → last full state

    # ── Snapshot API ────────────────────────

    async def snapshot(
        self,
        thread_id: str,
        messages: list[dict[str, Any]],
        state: dict[str, Any],
        tools_result: dict[str, Any],
        trigger: SnapshotTrigger = SnapshotTrigger.MANUAL,
        parent_checkpoint_id: str | None = None,
        next_node: str = "",
    ) -> str:
        """创建一次快照。返回 checkpoint_id。"""
        if trigger not in self._config.triggers:
            return ""  # 不在此触发范围内

        step = self._snapshot_counters.get(thread_id, 0) + 1
        self._snapshot_counters[thread_id] = step

        checkpoint_id = f"ckpt-{thread_id}-{step}-{uuid.uuid4().hex[:6]}"

        metadata = CheckpointMetadata(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            parent_checkpoint_id=parent_checkpoint_id,
            step=step,
            tags=[trigger.value],
            summary=self._auto_summary(messages, state),
        )

        checkpoint = Checkpoint(
            metadata=metadata,
            messages=list(messages),
            state=dict(state),
            tools_result=dict(tools_result),
            next_node=next_node,
        )

        await self._checkpointer.put(checkpoint)

        # GC
        await self._maybe_gc(thread_id)

        return checkpoint_id

    async def snapshot_safe(
        self,
        thread_id: str,
        messages: list[dict[str, Any]],
        state: dict[str, Any],
        tools_result: dict[str, Any],
        trigger: SnapshotTrigger = SnapshotTrigger.MANUAL,
        parent_checkpoint_id: str | None = None,
        next_node: str = "",
    ) -> str:
        """安全快照：失败不抛异常，不影响主流程。"""
        try:
            return await self.snapshot(
                thread_id,
                messages,
                state,
                tools_result,
                trigger,
                parent_checkpoint_id,
                next_node,
            )
        except Exception as e:
            logger.error(f"Snapshot failed (non-blocking): {e}")
            return ""

    # ── Time Travel API ─────────────────────

    async def rewind(
        self,
        checkpoint_id: str,
    ) -> TimeTravelResult:
        """时间旅行：回退到指定 checkpoint。"""
        target = await self._checkpointer.get(checkpoint_id)
        if not target:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        thread_id = target.metadata.thread_id

        # 计算回退深度
        current_step = self._snapshot_counters.get(thread_id, 0)
        target_step = target.metadata.step
        rewind_depth = current_step - target_step

        # 删除目标之后的 checkpoint（默认行为，可配置）
        later_checkpoints = await self._checkpointer.list_checkpoints(thread_id)
        deleted = 0
        for cp_meta in later_checkpoints:
            if cp_meta.step > target_step:
                await self._checkpointer.delete_thread(cp_meta.thread_id)
                deleted += 1

        # 重置计数器
        self._snapshot_counters[thread_id] = target_step

        logger.info(
            f"Time travel: rewound {thread_id} by {rewind_depth} steps "
            f"to checkpoint {checkpoint_id} (step {target_step}), deleted {deleted} later checkpoints"
        )

        return TimeTravelResult(
            checkpoint=target,
            thread_id=thread_id,
            rewind_depth=rewind_depth,
            snapshot_count_before=current_step,
        )

    async def time_travel_to_step(
        self,
        thread_id: str,
        step: int,
    ) -> TimeTravelResult | None:
        """按步骤号时间旅行。"""
        checkpoints = await self._checkpointer.list_checkpoints(thread_id, limit=500)

        # 找到最接近目标 step 的 checkpoint
        matching = [cp for cp in checkpoints if cp.step <= step]
        if not matching:
            return None

        target = sorted(matching, key=lambda c: c.step, reverse=True)[0]
        return await self.rewind(target.checkpoint_id)

    async def list_time_travel_points(
        self,
        thread_id: str,
        limit: int = 50,
    ) -> list[CheckpointMetadata]:
        """列出所有可回溯的时间点。"""
        return await self._checkpointer.list_checkpoints(thread_id, limit=limit)

    # ── Branch API ──────────────────────────

    async def branch(
        self,
        from_checkpoint_id: str,
        branch_name: str,
    ) -> str:
        """从某个历史 checkpoint 创建分支执行。"""
        source = await self._checkpointer.get(from_checkpoint_id)
        if not source:
            raise ValueError(f"Source checkpoint {from_checkpoint_id} not found")

        branch_thread_id = (
            f"{source.metadata.thread_id}-branch-{branch_name}-{uuid.uuid4().hex[:4]}"
        )

        # 在新分支中创建起始 checkpoint（引用源 checkpoint 状态）
        branch_checkpoint = Checkpoint(
            metadata=CheckpointMetadata(
                thread_id=branch_thread_id,
                checkpoint_id=f"ckpt-{branch_thread_id}-0",
                parent_checkpoint_id=from_checkpoint_id,
                step=0,
                tags=["branch", branch_name],
                summary=f"Branch '{branch_name}' from {from_checkpoint_id}",
            ),
            messages=list(source.messages),
            state=dict(source.state),
            tools_result=dict(source.tools_result),
            next_node="",
        )

        await self._checkpointer.put(branch_checkpoint)
        self._snapshot_counters[branch_thread_id] = 0

        logger.info(f"Created branch: {branch_thread_id} from {from_checkpoint_id}")
        return branch_thread_id

    async def merge_branch(
        self,
        branch_thread_id: str,
        into_thread_id: str,
    ) -> str:
        """合并分支到主线程。"""
        branch_latest = await self._checkpointer.get_latest(branch_thread_id)
        if not branch_latest:
            raise ValueError(f"Branch {branch_thread_id} has no checkpoints")

        # 在主线程创建一个引用分支状态的快照
        merge_id = await self.snapshot(
            thread_id=into_thread_id,
            messages=branch_latest.messages,
            state=branch_latest.state,
            tools_result=branch_latest.tools_result,
            trigger=SnapshotTrigger.MANUAL,
            parent_checkpoint_id=branch_latest.metadata.checkpoint_id,
        )

        logger.info(f"Merged branch {branch_thread_id} → {into_thread_id} (merge ckpt: {merge_id})")
        return merge_id

    # ── Decorator API ───────────────────────

    def snapshot_on(self, trigger: SnapshotTrigger):
        """装饰器：在调用前后自动快照。

        Usage:
            engine = CheckpointEngine(...)

            @engine.snapshot_on(SnapshotTrigger.TOOL_CALL)
            async def search_database(query: str): ...
        """

        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                thread_id = kwargs.pop("_checkpoint_thread_id", "default")
                state = kwargs.pop("_checkpoint_state", {})

                # Before snapshot
                await self.snapshot_safe(
                    thread_id=thread_id,
                    messages=[{"role": "tool_call", "content": f"{func.__name__}({kwargs})"}],
                    state=state,
                    tools_result={},
                    trigger=trigger,
                )

                result = await func(*args, **kwargs)

                # After snapshot
                await self.snapshot_safe(
                    thread_id=thread_id,
                    messages=[{"role": "tool_result", "content": str(result)[:500]}],
                    state=state,
                    tools_result={"result": str(result)[:1000]},
                    trigger=trigger,
                )

                return result

            return wrapper

        return decorator

    @asynccontextmanager
    async def snapshot_scope(
        self,
        thread_id: str,
        state: dict[str, Any],
        trigger: SnapshotTrigger = SnapshotTrigger.STATE_CHANGE,
    ):
        """上下文管理器：进入和退出作用域时自动快照。

        Usage:
            async with engine.snapshot_scope("thread-1", state):
                await execute_workflow(...)
        """
        await self.snapshot_safe(
            thread_id=thread_id,
            messages=[{"role": "system", "content": f"Enter scope ({trigger.value})"}],
            state=state,
            tools_result={},
            trigger=trigger,
        )
        try:
            yield
        finally:
            await self.snapshot_safe(
                thread_id=thread_id,
                messages=[{"role": "system", "content": f"Exit scope ({trigger.value})"}],
                state=state,
                tools_result={},
                trigger=trigger,
            )

    # ── Query API ───────────────────────────

    async def get_latest(self, thread_id: str) -> Checkpoint | None:
        return await self._checkpointer.get_latest(thread_id)

    async def get_checkpoint_tree(self, thread_id: str, limit: int = 200) -> dict[str, Any]:
        """获取线程的 checkpoint 树结构（用于可视化）。"""
        checkpoints = await self._checkpointer.list_checkpoints(thread_id, limit=limit)

        nodes: list[dict] = []
        edges: list[dict] = []
        by_id: dict[str, CheckpointMetadata] = {}

        for cp in checkpoints:
            by_id[cp.checkpoint_id] = cp
            nodes.append(
                {
                    "id": cp.checkpoint_id,
                    "step": cp.step,
                    "tags": cp.tags,
                    "summary": cp.summary,
                    "created_at": cp.created_at,
                }
            )

        for cp in checkpoints:
            if cp.parent_checkpoint_id and cp.parent_checkpoint_id in by_id:
                edges.append(
                    {
                        "from": cp.parent_checkpoint_id,
                        "to": cp.checkpoint_id,
                    }
                )

        return {
            "thread_id": thread_id,
            "total_checkpoints": len(checkpoints),
            "nodes": nodes,
            "edges": edges,
        }

    # ── Internal ────────────────────────────

    def _auto_summary(self, messages: list[dict[str, Any]], state: dict[str, Any]) -> str:
        """自动生成 checkpoint 摘要。"""
        if messages:
            last = messages[-1]
            role = last.get("role", "unknown")
            content = str(last.get("content", ""))[:100]
            return f"[{role}] {content}"
        return f"State: {len(state)} keys"

    async def _maybe_gc(self, thread_id: str):
        """根据 GC 策略清理旧 checkpoint。"""
        if self._config.gc_policy == CheckpointGC.KEEP_ALL:
            return

        checkpoints = await self._checkpointer.list_checkpoints(thread_id, limit=500)

        if self._config.gc_policy == CheckpointGC.KEEP_LAST_N:
            if len(checkpoints) > self._config.gc_param:
                to_delete = sorted(checkpoints, key=lambda c: c.step)[
                    : len(checkpoints) - self._config.gc_param
                ]
                for cp in to_delete:
                    await self._checkpointer.delete_before(thread_id, cp.step + 1)
                logger.debug(f"GC: removed {len(to_delete)} old checkpoints from {thread_id}")

        elif self._config.gc_policy == CheckpointGC.KEEP_AGE:
            cutoff = time.time() - self._config.gc_param
            deleted = 0
            for cp in checkpoints:
                try:
                    created = (
                        __import__("datetime").datetime.fromisoformat(cp.created_at).timestamp()
                    )
                    if created < cutoff:
                        await self._checkpointer.delete_thread(cp.thread_id)
                        deleted += 1
                except Exception:
                    continue
            if deleted:
                logger.debug(f"GC: removed {deleted} expired checkpoints from {thread_id}")

        elif self._config.gc_policy == CheckpointGC.KEEP_MILESTONES:
            if len(checkpoints) > self._config.gc_param:
                # 保留 first, last, 和均匀分布的 milestones
                sorted_cps = sorted(checkpoints, key=lambda c: c.step)
                keep = {sorted_cps[0].step, sorted_cps[-1].step}

                n_milestones = max(2, self._config.gc_param - 2)
                step_size = max(1, len(sorted_cps) // n_milestones)
                for i in range(1, n_milestones):
                    idx = i * step_size
                    if idx < len(sorted_cps):
                        keep.add(sorted_cps[idx].step)

                for cp in sorted_cps:
                    if cp.step not in keep:
                        await self._checkpointer.delete_thread(cp.thread_id)
                logger.debug(f"GC milestones: kept {len(keep)} of {len(sorted_cps)} in {thread_id}")


# ── Quick Start ──────────────────────────────


async def create_checkpoint_engine(
    backend: str = "sqlite",
    db_path: str = "checkpoints.db",
) -> CheckpointEngine:
    """快速创建 checkpoint 引擎。"""
    from agentos.checkpoint.factory import create_checkpointer

    checkpointer = create_checkpointer(backend, db_path=db_path)
    return CheckpointEngine(checkpointer)
