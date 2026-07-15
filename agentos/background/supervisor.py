"""AgentSupervisor — spawn, monitor, and manage child agents with quotas."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine


# ── Enums ──────────────────────────────────────────────────────────


class SupervisionEventType(str, Enum):
    SPAWNED = "spawned"
    STARTED = "started"
    HEARTBEAT = "heartbeat"
    PROGRESS = "progress"
    QUOTA_WARNING = "quota_warning"
    QUOTA_EXCEEDED = "quota_exceeded"
    HEARTBEAT_LOST = "heartbeat_lost"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    KILLED = "killed"


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class SupervisionEvent:
    type: SupervisionEventType
    child_id: str
    child_name: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "child_id": self.child_id,
            "child_name": self.child_name,
            "timestamp": self.timestamp,
            "data": self.data,
            "message": self.message,
        }


@dataclass
class AgentQuota:
    max_duration_seconds: float = 3600.0
    max_cost_usd: float = 10.0
    max_tokens: int = 1_000_000
    max_iterations: int = 500
    heartbeat_interval: float = 10.0
    heartbeat_timeout: float = 30.0
    max_retries: int = 0
    retry_delay: float = 5.0
    cooldown_period: float = 60.0


@dataclass
class AgentQuotaUsage:
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0
    tokens_used: int = 0
    iterations: int = 0
    heartbeats_received: int = 0
    last_heartbeat: float = 0.0
    restarts: int = 0
    last_restart: float = 0.0

    @property
    def duration_percent(self) -> float:
        return 0.0

    @property
    def cost_percent(self) -> float:
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "cost_usd": self.cost_usd,
            "tokens_used": self.tokens_used,
            "iterations": self.iterations,
            "heartbeats_received": self.heartbeats_received,
            "last_heartbeat": self.last_heartbeat,
            "restarts": self.restarts,
            "last_restart": self.last_restart,
        }


@dataclass
class SupervisedAgent:
    id: str = field(default_factory=lambda: secrets.token_hex(6))
    name: str = ""
    quotas: AgentQuota = field(default_factory=AgentQuota)
    usage: AgentQuotaUsage = field(default_factory=AgentQuotaUsage)
    status: str = "pending"
    started_at: float = 0.0
    finished_at: float = 0.0
    result: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # internal (not serialized)
    _task: asyncio.Task[Any] | None = field(default=None, repr=False)
    _pause_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _kill_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def is_alive(self) -> bool:
        return self.status in ("running", "paused")

    @property
    def duration_seconds(self) -> float:
        if self.started_at == 0.0:
            return 0.0
        end = self.finished_at if self.finished_at > 0.0 else time.time()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "metadata": self.metadata,
            "quotas": {
                "max_duration_seconds": self.quotas.max_duration_seconds,
                "max_cost_usd": self.quotas.max_cost_usd,
                "max_tokens": self.quotas.max_tokens,
                "max_iterations": self.quotas.max_iterations,
            },
            "usage": self.usage.to_dict(),
        }


@dataclass
class SupervisorConfig:
    max_children: int = 20
    monitor_interval: float = 1.0
    event_history_size: int = 500
    auto_kill_on_quota: bool = True
    log_events: bool = True


# ── AgentSupervisor ────────────────────────────────────────────────


class AgentSupervisor:
    """Spawns, monitors, and manages child agents with quota enforcement."""

    def __init__(
        self,
        config: SupervisorConfig | None = None,
        on_event: Callable[[SupervisionEvent], None] | None = None,
    ) -> None:
        self.config = config or SupervisorConfig()
        self._on_event: Callable[[SupervisionEvent], None] | None = on_event
        self._children: dict[str, SupervisedAgent] = {}
        self._events: list[SupervisionEvent] = []
        self._monitor_task: asyncio.Task[Any] | None = None

    # ── Public API ─────────────────────────────────────────────

    async def spawn(
        self,
        name: str,
        task: str,
        loop_factory: Callable[[], Any] | None = None,
        agent_loop: Any = None,
        quotas: AgentQuota | None = None,
        on_heartbeat: Callable[[], Coroutine[Any, Any, None]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Spawn a new child agent."""
        if len(self._children) >= self.config.max_children:
            raise RuntimeError("Max children limit reached")

        child = SupervisedAgent(
            name=name,
            quotas=quotas or AgentQuota(),
            metadata=metadata or {},
        )
        self._children[child.id] = child

        self._emit(SupervisionEvent(
            type=SupervisionEventType.SPAWNED,
            child_id=child.id,
            child_name=name,
        ))

        # Start the child
        loop = agent_loop if agent_loop is not None else (loop_factory() if loop_factory else None)
        child._task = asyncio.create_task(
            self._run_child(child, task, loop_factory, loop)
        )

        # Start heartbeat if callback provided
        if on_heartbeat:
            asyncio.create_task(self._heartbeat_loop(child, on_heartbeat))

        # Start monitor if not already started
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())

        return child.id

    async def get_child(self, child_id: str) -> SupervisedAgent | None:
        """Get a child by ID."""
        return self._children.get(child_id)

    async def list_children(self) -> list[SupervisedAgent]:
        """List all children."""
        return list(self._children.values())

    async def await_child(self, child_id: str, timeout: float | None = None) -> Any | None:
        """Wait for a child to complete."""
        child = self._children.get(child_id)
        if child is None:
            raise KeyError(f"Child '{child_id}' not found")
        if child._task is None:
            raise RuntimeError(f"Child '{child_id}' has no running task")

        try:
            if timeout is not None:
                return await asyncio.wait_for(child._task, timeout=timeout)
            return await child._task
        except asyncio.TimeoutError:
            # kill the child
            await self.kill_child(child_id, reason="await_child timeout")
            return None

    async def pause_child(self, child_id: str) -> bool:
        """Pause a running child."""
        child = self._children.get(child_id)
        if child is None or child.status != "running":
            return False
        child._pause_event.clear()
        child.status = "paused"
        self._emit(SupervisionEvent(
            type=SupervisionEventType.CANCELLED,
            child_id=child_id,
            child_name=child.name,
            message="paused",
        ))
        return True

    async def resume_child(self, child_id: str) -> bool:
        """Resume a paused child."""
        child = self._children.get(child_id)
        if child is None or child.status != "paused":
            return False
        child._pause_event.set()
        child.status = "running"
        self._emit(SupervisionEvent(
            type=SupervisionEventType.STARTED,
            child_id=child_id,
            child_name=child.name,
            message="resumed",
        ))
        return True

    async def kill_child(self, child_id: str, reason: str = "") -> bool:
        """Kill a running child."""
        child = self._children.get(child_id)
        if child is None:
            return False
        if child._kill_event.is_set():
            return False
        child._kill_event.set()
        if child._task and not child._task.done():
            child._task.cancel()
        child.status = "killed"
        if reason:
            child.error = reason
        self._emit(SupervisionEvent(
            type=SupervisionEventType.KILLED,
            child_id=child_id,
            child_name=child.name,
            message=reason,
        ))
        return True

    async def aggregate_progress(self) -> dict[str, Any]:
        """Aggregate progress across all children."""
        children_list = list(self._children.values())
        total = len(children_list)
        completed = sum(1 for c in children_list if c.status == "completed")
        return {
            "total_children": total,
            "completed": completed,
            "percent_complete": (completed / total * 100.0) if total > 0 else 0,
            "children": [c.to_dict() for c in children_list],
        }

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Shut down the supervisor and all children."""
        # Kill all alive children
        for child in self._children.values():
            if child.is_alive:
                child._kill_event.set()
                if child._task and not child._task.done():
                    child._task.cancel()
                child.status = "killed"

        # Cancel monitor
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await asyncio.wait_for(self._monitor_task, timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        # Wait for children
        for child in self._children.values():
            if child._task and not child._task.done():
                try:
                    await asyncio.wait_for(child._task, timeout=timeout)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

    # ── Internal ───────────────────────────────────────────────

    def _emit(self, event: SupervisionEvent) -> None:
        """Emit a supervision event (add to history + call callback)."""
        if self.config.log_events:
            self._events.append(event)
            # Cap history size
            while len(self._events) > self.config.event_history_size:
                self._events.pop(0)

        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass  # callback errors must not crash the supervisor

    async def _run_child(
        self,
        child: SupervisedAgent,
        task: str,
        loop_factory: Callable[[], Any] | None,
        agent_loop: Any,
    ) -> None:
        """Internal: run a child agent with retry and quota enforcement."""
        child.status = "running"
        child.started_at = time.time()
        self._emit(SupervisionEvent(
            type=SupervisionEventType.STARTED,
            child_id=child.id,
            child_name=child.name,
        ))

        # Resolve the loop
        if agent_loop is not None:
            loop = agent_loop
        elif loop_factory is not None:
            loop = loop_factory()
        else:
            child.status = "failed"
            child.error = "Must provide agent_loop or loop_factory"
            self._emit(SupervisionEvent(
                type=SupervisionEventType.FAILED,
                child_id=child.id,
                child_name=child.name,
                message=child.error,
            ))
            return

        retries = 0
        while retries <= child.quotas.max_retries:
            try:
                # Run the agent
                original_on_iteration = getattr(loop, "on_iteration", None)

                async def supervised_on_iteration(iteration: int, tool_results: Any) -> None:
                    """Wrapper that injects supervisor checks into each iteration."""
                    # Check kill signal
                    if child._kill_event.is_set():
                        child._task.cancel()
                        return

                    # Check pause
                    await child._pause_event.wait()

                    # Update usage
                    child.usage.iterations = max(child.usage.iterations, iteration + 1)
                    child.usage.elapsed_seconds = time.time() - child.started_at

                    # Duration quota check
                    if child.usage.elapsed_seconds > child.quotas.max_duration_seconds:
                        if self.config.auto_kill_on_quota:
                            child._kill_event.set()
                            self._emit(SupervisionEvent(
                                type=SupervisionEventType.QUOTA_EXCEEDED,
                                child_id=child.id,
                                child_name=child.name,
                                message=f"Duration quota exceeded: {child.usage.elapsed_seconds:.1f}s",
                            ))
                            child._task.cancel()
                            return
                        else:
                            self._emit(SupervisionEvent(
                                type=SupervisionEventType.QUOTA_WARNING,
                                child_id=child.id,
                                child_name=child.name,
                                message=f"Duration quota warning: {child.usage.elapsed_seconds:.1f}s",
                            ))

                    # Call original on_iteration if present
                    if original_on_iteration is not None:
                        result = original_on_iteration(iteration, tool_results)
                        if asyncio.iscoroutine(result):
                            await result

                loop.on_iteration = supervised_on_iteration

                result = await loop.run(task, child.id)

                child.result = getattr(result, "output", result)
                child.usage.cost_usd = getattr(result, "cost_usd", 0.0)
                tokens_raw = getattr(result, "tokens_used", 0)
                child.usage.tokens_used = sum(tokens_raw.values()) if isinstance(tokens_raw, dict) else tokens_raw
                child.status = "completed"
                child.finished_at = time.time()
                self._emit(SupervisionEvent(
                    type=SupervisionEventType.COMPLETED,
                    child_id=child.id,
                    child_name=child.name,
                ))
                return

            except asyncio.CancelledError:
                if child._kill_event.is_set():
                    child.status = "killed"
                else:
                    child.status = "cancelled"
                child.finished_at = time.time()
                self._emit(SupervisionEvent(
                    type=SupervisionEventType.KILLED,
                    child_id=child.id,
                    child_name=child.name,
                ))
                raise

            except Exception as exc:
                retries += 1
                child.usage.restarts += 1
                child.usage.last_restart = time.time()
                if retries > child.quotas.max_retries:
                    child.status = "failed"
                    child.error = str(exc)
                    child.finished_at = time.time()
                    self._emit(SupervisionEvent(
                        type=SupervisionEventType.FAILED,
                        child_id=child.id,
                        child_name=child.name,
                        message=str(exc),
                    ))
                    return

                # Cooldown before retry
                await asyncio.sleep(child.quotas.retry_delay)

    async def _heartbeat_loop(
        self,
        child: SupervisedAgent,
        on_heartbeat: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Internal: periodic heartbeat for a child."""
        while child.is_alive:
            try:
                await asyncio.sleep(child.quotas.heartbeat_interval)
                if not child.is_alive:
                    break
                try:
                    await on_heartbeat()
                    child.usage.heartbeats_received += 1
                    child.usage.last_heartbeat = time.time()
                except Exception:
                    pass  # heartbeat callback failure is non-fatal
            except asyncio.CancelledError:
                break

    async def _monitor_loop(self) -> None:
        """Internal: monitor all children for heartbeat loss and quota violations."""
        while True:
            try:
                await asyncio.sleep(self.config.monitor_interval)

                for child in list(self._children.values()):
                    try:
                        if not child.is_alive:
                            continue

                        # Heartbeat timeout check
                        if child.quotas.heartbeat_timeout > 0:
                            now = time.time()
                            if child.usage.last_heartbeat > 0 and now - child.usage.last_heartbeat > child.quotas.heartbeat_timeout:
                                self._emit(SupervisionEvent(
                                    type=SupervisionEventType.HEARTBEAT_LOST,
                                    child_id=child.id,
                                    child_name=child.name,
                                    message=f"No heartbeat for {now - child.usage.last_heartbeat:.1f}s",
                                ))
                                if self.config.auto_kill_on_quota:
                                    child._kill_event.set()
                                    if child._task and not child._task.done():
                                        child._task.cancel()
                                    child.status = "killed"

                        # Duration quota check
                        elapsed = child.duration_seconds
                        if elapsed > child.quotas.max_duration_seconds * 0.8:
                            self._emit(SupervisionEvent(
                                type=SupervisionEventType.QUOTA_WARNING,
                                child_id=child.id,
                                child_name=child.name,
                                message=f"Approaching duration quota: {child.usage.elapsed_seconds:.1f}s",
                            ))
                    except Exception:
                        pass  # individual child errors must not crash the monitor

            except asyncio.CancelledError:
                break
            except Exception:
                pass  # ensure loop never crashes
