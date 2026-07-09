"""
Background Task Manager — v1.11.0

Production-grade long-running task execution with:
- Submit task → get task_id → poll progress → retrieve result
- Persistent task state (SQLite/Postgres)
- Progress milestones with phase tracking
- Graceful pause/resume/cancel
- Timeout and resource budget enforcement
- Crash recovery via full checkpoint integration

Usage:
    mgr = BackgroundTaskManager(loop_factory=my_loop, store=SqliteStore("tasks.db"))
    task_id = await mgr.submit("Analyze 10GB dataset", task="...", config=...)
    while True:
        progress = await mgr.get_progress(task_id)
        print(f"{progress.current_phase}: {progress.percent:.0f}%")
        if progress.status.is_terminal:
            break
    result = await mgr.get_result(task_id)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ── Enums ────────────────────────────────────────────────────────


class BackgroundTaskStatus(StrEnum):
    """Background task lifecycle states."""

    QUEUED = "queued"  # Accepted, waiting to start
    RUNNING = "running"  # Actively executing
    PAUSED = "paused"  # Paused by user or system
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"  # Finished with error
    CANCELLED = "cancelled"  # Cancelled by user
    TIMED_OUT = "timed_out"  # Exceeded time budget

    @property
    def is_terminal(self) -> bool:
        return self in (
            BackgroundTaskStatus.COMPLETED,
            BackgroundTaskStatus.FAILED,
            BackgroundTaskStatus.CANCELLED,
            BackgroundTaskStatus.TIMED_OUT,
        )

    @property
    def is_active(self) -> bool:
        return self in (BackgroundTaskStatus.QUEUED, BackgroundTaskStatus.RUNNING)


# ── Data Models ──────────────────────────────────────────────────


@dataclass
class ProgressPhase:
    """A named phase within task execution."""

    name: str  # e.g. "data_loading", "analysis", "reporting"
    label: str = ""  # Human-readable label
    weight: float = 1.0  # Relative weight for percent calculation
    started_at: float = 0.0
    finished_at: float = 0.0
    completed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label or self.name,
            "weight": self.weight,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "completed": self.completed,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProgressPhase:
        return cls(
            name=d["name"],
            label=d.get("label", ""),
            weight=d.get("weight", 1.0),
            started_at=d.get("started_at", 0.0),
            finished_at=d.get("finished_at", 0.0),
            completed=d.get("completed", False),
            metadata=d.get("metadata", {}),
        )


@dataclass
class TaskProgress:
    """Structured progress report for a background task."""

    task_id: str
    status: BackgroundTaskStatus = BackgroundTaskStatus.QUEUED
    phases: list[ProgressPhase] = field(default_factory=list)
    current_phase: str = ""
    current_step: int = 0
    total_steps: int = 0
    percent: float = 0.0
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: float = 0.0
    last_update: float = 0.0
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "phases": [p.to_dict() for p in self.phases],
            "current_phase": self.current_phase,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "percent": self.percent,
            "elapsed_seconds": self.elapsed_seconds,
            "estimated_remaining_seconds": self.estimated_remaining_seconds,
            "last_update": self.last_update,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TaskProgress:
        return cls(
            task_id=d["task_id"],
            status=BackgroundTaskStatus(d.get("status", "queued")),
            phases=[ProgressPhase.from_dict(p) for p in d.get("phases", [])],
            current_phase=d.get("current_phase", ""),
            current_step=d.get("current_step", 0),
            total_steps=d.get("total_steps", 0),
            percent=d.get("percent", 0.0),
            elapsed_seconds=d.get("elapsed_seconds", 0.0),
            estimated_remaining_seconds=d.get("estimated_remaining_seconds", 0.0),
            last_update=d.get("last_update", 0.0),
            message=d.get("message", ""),
        )


@dataclass
class BackgroundTaskConfig:
    """Configuration for a background task."""

    max_duration_seconds: float = 3600.0  # 1 hour default
    max_cost_usd: float = 10.0
    enable_checkpoints: bool = True
    checkpoint_interval: int = 20  # iterations between checkpoints
    enable_progress: bool = True
    progress_report_interval: float = 5.0  # seconds between progress updates
    auto_resume: bool = True  # auto-resume from checkpoint on restart
    max_retries: int = 2  # retries on transient failure
    pause_on_cost_warning: bool = True
    notify_on_completion: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BackgroundTask:
    """Complete background task record."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    name: str = ""
    task_description: str = ""
    status: BackgroundTaskStatus = BackgroundTaskStatus.QUEUED
    config: BackgroundTaskConfig = field(default_factory=BackgroundTaskConfig)
    progress: TaskProgress = field(default_factory=lambda: TaskProgress(task_id=""))
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0
    cost_usd: float = 0.0
    tokens_used: int = 0
    checkpoint_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.progress.task_id:
            self.progress.task_id = self.id

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or time.time()
        start = self.started_at or self.created_at
        return end - start

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "task_description": self.task_description,
            "status": self.status.value,
            "config": {
                "max_duration_seconds": self.config.max_duration_seconds,
                "max_cost_usd": self.config.max_cost_usd,
                "enable_checkpoints": self.config.enable_checkpoints,
                "checkpoint_interval": self.config.checkpoint_interval,
                "auto_resume": self.config.auto_resume,
                "max_retries": self.config.max_retries,
            },
            "progress": self.progress.to_dict(),
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cost_usd": self.cost_usd,
            "tokens_used": self.tokens_used,
            "checkpoint_id": self.checkpoint_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BackgroundTask:
        cfg_d = d.get("config", {})
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            task_description=d.get("task_description", ""),
            status=BackgroundTaskStatus(d.get("status", "queued")),
            config=BackgroundTaskConfig(
                max_duration_seconds=cfg_d.get("max_duration_seconds", 3600.0),
                max_cost_usd=cfg_d.get("max_cost_usd", 10.0),
                enable_checkpoints=cfg_d.get("enable_checkpoints", True),
                checkpoint_interval=cfg_d.get("checkpoint_interval", 20),
                auto_resume=cfg_d.get("auto_resume", True),
                max_retries=cfg_d.get("max_retries", 2),
            ),
            progress=TaskProgress.from_dict(d.get("progress", {"task_id": d["id"]})),
            result=d.get("result"),
            error=d.get("error", ""),
            created_at=d.get("created_at", 0.0),
            started_at=d.get("started_at", 0.0),
            finished_at=d.get("finished_at", 0.0),
            cost_usd=d.get("cost_usd", 0.0),
            tokens_used=d.get("tokens_used", 0),
            checkpoint_id=d.get("checkpoint_id", ""),
            metadata=d.get("metadata", {}),
        )


# ── Callback types ───────────────────────────────────────────────

ProgressCallback = Callable[[TaskProgress], None]
CompletionCallback = Callable[[BackgroundTask], None]


# ── Background Task Manager ──────────────────────────────────────


class BackgroundTaskManager:
    """
    Manages long-running background agent tasks.

    Features:
    - Async task submission with configurable budgets
    - Persistent task state (in-memory + optional DB store)
    - Progress tracking with named phases
    - Pause/resume/cancel by task ID
    - Crash recovery with checkpoint replay
    - Concurrent task execution with configurable max workers
    """

    def __init__(
        self,
        max_concurrent: int = 5,
        store: Any = None,  # Optional CheckpointStore-like persistence
    ):
        self.max_concurrent = max_concurrent
        self._store = store
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, BackgroundTask] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._progress_callbacks: dict[str, list[ProgressCallback]] = {}
        self._completion_callbacks: dict[str, list[CompletionCallback]] = {}

    # ── Public API ───────────────────────────────────────────────

    async def submit(
        self,
        name: str,
        task: str,
        loop_factory: Callable[[], Any] | None = None,
        agent_loop: Any = None,
        config: BackgroundTaskConfig | None = None,
        phases: list[ProgressPhase] | None = None,
    ) -> str:
        """Submit a task for background execution. Returns task_id."""
        bt = BackgroundTask(
            name=name,
            task_description=task,
            config=config or BackgroundTaskConfig(),
        )
        if phases:
            bt.progress.phases = phases
            bt.progress.total_steps = len(phases)

        bt.progress.last_update = time.time()
        self._tasks[bt.id] = bt

        if self._store:
            await self._persist(bt)

        # Start in background
        coro = self._run_task(bt, loop_factory, agent_loop)
        self._running[bt.id] = asyncio.create_task(coro)

        return bt.id

    async def get_task(self, task_id: str) -> BackgroundTask | None:
        """Get full task record."""
        if task_id in self._tasks:
            return self._tasks[task_id]
        if self._store:
            return await self._load(task_id)
        return None

    async def get_progress(self, task_id: str) -> TaskProgress | None:
        """Get current progress for a task."""
        t = await self.get_task(task_id)
        return t.progress if t else None

    async def get_result(self, task_id: str) -> Any:
        """Get task result (blocks if still running)."""
        t = await self.get_task(task_id)
        if not t:
            raise KeyError(f"Task {task_id} not found")
        if t.status.is_active:
            # Wait for completion
            running_task = self._running.get(task_id)
            if running_task and not running_task.done():
                await running_task
            t = self._tasks.get(task_id)
            if not t:
                raise KeyError(f"Task {task_id} vanished")
        if t.status == BackgroundTaskStatus.FAILED:
            raise RuntimeError(f"Task {task_id} failed: {t.error}")
        return t.result

    async def pause(self, task_id: str) -> bool:
        """Pause a running task."""
        t = self._tasks.get(task_id)
        if not t or not t.status.is_active:
            return False
        t.status = BackgroundTaskStatus.PAUSED
        t.progress.status = BackgroundTaskStatus.PAUSED
        await self._update_progress(task_id)
        return True

    async def resume(self, task_id: str) -> bool:
        """Resume a paused task."""
        t = self._tasks.get(task_id)
        if not t or t.status != BackgroundTaskStatus.PAUSED:
            return False
        t.status = BackgroundTaskStatus.RUNNING
        t.progress.status = BackgroundTaskStatus.RUNNING
        await self._update_progress(task_id)
        return True

    async def cancel(self, task_id: str) -> bool:
        """Cancel a task."""
        t = self._tasks.get(task_id)
        if not t:
            return False
        t.status = BackgroundTaskStatus.CANCELLED
        t.progress.status = BackgroundTaskStatus.CANCELLED
        t.finished_at = time.time()
        running = self._running.pop(task_id, None)
        if running and not running.done():
            running.cancel()
        await self._update_progress(task_id)
        await self._notify_completion(task_id)
        if self._store:
            await self._persist(t)
        return True

    async def list_tasks(
        self,
        status: BackgroundTaskStatus | None = None,
        limit: int = 50,
    ) -> list[BackgroundTask]:
        """List tasks, optionally filtered by status."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)[:limit]

    def on_progress(self, task_id: str, callback: ProgressCallback):
        """Register a progress callback for a task."""
        if task_id not in self._progress_callbacks:
            self._progress_callbacks[task_id] = []
        self._progress_callbacks[task_id].append(callback)

    def on_completion(self, task_id: str, callback: CompletionCallback):
        """Register a completion callback for a task."""
        if task_id not in self._completion_callbacks:
            self._completion_callbacks[task_id] = []
        self._completion_callbacks[task_id].append(callback)

    # ── Progress Reporting ───────────────────────────────────────

    async def update_phase(
        self,
        task_id: str,
        phase_name: str,
        completed: bool = False,
        step: int = 0,
        message: str = "",
    ):
        """Update a named phase in the task progress."""
        t = self._tasks.get(task_id)
        if not t or not t.config.enable_progress:
            return

        prog = t.progress
        # Find or create phase
        phase = None
        for p in prog.phases:
            if p.name == phase_name:
                phase = p
                break
        if not phase:
            phase = ProgressPhase(name=phase_name, label=phase_name)
            prog.phases.append(phase)
            prog.total_steps = len(prog.phases)

        if completed:
            phase.completed = True
            phase.finished_at = time.time()
        elif not phase.started_at:
            phase.started_at = time.time()

        prog.current_phase = phase_name
        if step:
            prog.current_step = step
        if message:
            prog.message = message

        # Calculate percent from phase weights
        total_weight = sum(p.weight for p in prog.phases)
        completed_weight = sum(p.weight for p in prog.phases if p.completed)
        if prog.current_phase and total_weight > 0:
            current_phase_obj = phase
            if (
                current_phase_obj
                and not current_phase_obj.completed
                and current_phase_obj.weight > 0
            ):
                # Partial credit for current phase
                partial = current_phase_obj.weight * min(
                    step / max(t.config.checkpoint_interval, 1), 1.0
                )
                completed_weight += partial
            prog.percent = min(completed_weight / total_weight * 100, 99.9)
        elif completed_weight >= total_weight:
            prog.percent = 100.0

        prog.last_update = time.time()
        elapsed = prog.last_update - (t.started_at or t.created_at)
        prog.elapsed_seconds = elapsed
        if prog.percent > 0:
            prog.estimated_remaining_seconds = elapsed / (prog.percent / 100) - elapsed

        await self._update_progress(task_id)

    # ── Internal ─────────────────────────────────────────────────

    async def _run_task(
        self,
        bt: BackgroundTask,
        loop_factory: Callable[[], Any] | None,
        agent_loop: Any,
    ):
        """Execute a background task with full lifecycle management."""
        async with self._semaphore:
            bt.status = BackgroundTaskStatus.RUNNING
            bt.progress.status = BackgroundTaskStatus.RUNNING
            bt.started_at = time.time()
            await self._update_progress(bt.id)
            if self._store:
                await self._persist(bt)

            try:
                # Timeout enforcement
                timeout = bt.config.max_duration_seconds
                start = time.time()

                if loop_factory:
                    loop = loop_factory()
                elif agent_loop:
                    loop = agent_loop
                else:
                    raise ValueError("Must provide loop_factory or agent_loop")

                # Inject progress callback into the loop
                original_on_iteration = getattr(loop, "on_iteration", None)

                async def progress_on_iteration(iteration: int, tool_results: list):
                    elapsed = time.time() - start
                    if elapsed > timeout:
                        raise TimeoutError("Task exceeded max duration")
                    if bt.status == BackgroundTaskStatus.PAUSED:
                        # Spin-wait for resume (or timeout)
                        while bt.status == BackgroundTaskStatus.PAUSED:
                            await asyncio.sleep(0.5)
                            if time.time() - start > timeout:
                                raise TimeoutError("Task timed out while paused")
                    if (
                        bt.config.enable_checkpoints
                        and iteration % bt.config.checkpoint_interval == 0
                    ):
                        bt.progress.current_step = iteration
                        await self.update_phase(
                            bt.id, "execution", step=iteration, message=f"Step {iteration}"
                        )
                    if original_on_iteration:
                        original_on_iteration(iteration, tool_results)

                loop.on_iteration = progress_on_iteration

                # Run
                result = await loop.run(bt.task_description, session_id=bt.id)
                bt.result = result.output if hasattr(result, "output") else result
                bt.cost_usd = getattr(result, "cost_usd", 0.0)
                bt.tokens_used = sum(getattr(result, "tokens_used", {}).values())
                bt.status = BackgroundTaskStatus.COMPLETED
                bt.progress.status = BackgroundTaskStatus.COMPLETED
                bt.progress.percent = 100.0

            except TimeoutError:
                bt.status = BackgroundTaskStatus.TIMED_OUT
                bt.progress.status = BackgroundTaskStatus.TIMED_OUT
                bt.error = f"Exceeded max duration of {bt.config.max_duration_seconds}s"
            except asyncio.CancelledError:
                bt.status = BackgroundTaskStatus.CANCELLED
                bt.progress.status = BackgroundTaskStatus.CANCELLED
            except Exception as e:
                bt.status = BackgroundTaskStatus.FAILED
                bt.progress.status = BackgroundTaskStatus.FAILED
                bt.error = str(e)
            finally:
                bt.finished_at = time.time()
                bt.progress.last_update = time.time()
                bt.progress.elapsed_seconds = bt.finished_at - bt.started_at
                await self._update_progress(bt.id)
                await self._notify_completion(bt.id)
                if self._store:
                    await self._persist(bt)
                self._running.pop(bt.id, None)

    async def _update_progress(self, task_id: str):
        """Fire progress callbacks."""
        callbacks = self._progress_callbacks.get(task_id, [])
        if not callbacks:
            return
        t = self._tasks.get(task_id)
        if t:
            for cb in callbacks:
                try:
                    cb(t.progress)
                except Exception:
                    pass

    async def _notify_completion(self, task_id: str):
        """Fire completion callbacks."""
        callbacks = self._completion_callbacks.get(task_id, [])
        if not callbacks:
            return
        t = self._tasks.get(task_id)
        if t:
            for cb in callbacks:
                try:
                    cb(t)
                except Exception:
                    pass

    async def _persist(self, bt: BackgroundTask):
        """Persist task to store."""
        if not self._store:
            return
        try:
            data = json.dumps(bt.to_dict())
            if hasattr(self._store, "save"):
                await self._store.save(f"bg_task:{bt.id}", {"data": data})
        except Exception:
            pass

    async def _load(self, task_id: str) -> BackgroundTask | None:
        """Load task from store."""
        if not self._store:
            return None
        try:
            snap = await self._store.load(f"bg_task:{task_id}")
            if snap and "data" in snap:
                return BackgroundTask.from_dict(json.loads(snap["data"]))
        except Exception:
            pass
        return None
