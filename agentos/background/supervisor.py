"""
Agent Supervision Tree — v1.11.0

Resource-bounded agent hierarchy with monitoring, quotas, and auto-recovery.
Inspired by OS process supervision (systemd, supervisord).

Features:
- Hierarchical supervision tree: parent monitors children
- Resource quotas per agent (time, cost, tokens, concurrency)
- Heartbeat-based health monitoring
- Auto-kill for runaway agents exceeding quotas
- Graceful degradation: kill child, preserve parent
- Aggregate progress across the tree
- Supervision events for external monitoring

Usage:
    sup = AgentSupervisor()
    child = await sup.spawn(
        name="data_analyzer",
        loop_factory=lambda: AgentLoop(...),
        quotas=AgentQuota(max_duration=600, max_cost_usd=2.0),
    )
    result = await sup.await_child(child.id, timeout=600)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional


# ── Enums ────────────────────────────────────────────────────────

class SupervisionEventType(str, Enum):
    """Types of supervision events."""
    SPAWNED = "spawned"
    STARTED = "started"
    HEARTBEAT = "heartbeat"
    PROGRESS = "progress"
    QUOTA_WARNING = "quota_warning"    # Nearing quota limit
    QUOTA_EXCEEDED = "quota_exceeded"  # Quota hit, killed
    HEARTBEAT_LOST = "heartbeat_lost"   # Child unresponsive
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    KILLED = "killed"                   # Killed by supervisor


@dataclass
class SupervisionEvent:
    """Event emitted by the supervision tree."""
    type: SupervisionEventType
    child_id: str
    child_name: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type.value, "child_id": self.child_id,
            "child_name": self.child_name, "timestamp": self.timestamp,
            "data": self.data, "message": self.message,
        }


# ── Data Models ──────────────────────────────────────────────────

@dataclass
class AgentQuota:
    """Resource limits for a supervised agent."""
    max_duration_seconds: float = 3600.0      # Wall-clock time budget
    max_cost_usd: float = 10.0                # Cost budget
    max_tokens: int = 1_000_000               # Token budget
    max_iterations: int = 500                 # Max loop iterations
    heartbeat_interval: float = 10.0          # Seconds between heartbeats
    heartbeat_timeout: float = 30.0           # Seconds before considered dead
    max_retries: int = 0                      # Auto-restart on failure (0=no restart)
    retry_delay: float = 5.0                  # Delay before restart
    cooldown_period: float = 60.0             # Rate limit on restarts


@dataclass
class AgentQuotaUsage:
    """Current resource consumption of a supervised agent."""
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
        return 0.0  # Set externally with quota context

    @property
    def cost_percent(self) -> float:
        return 0.0

    def to_dict(self) -> dict:
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "cost_usd": self.cost_usd, "tokens_used": self.tokens_used,
            "iterations": self.iterations, "heartbeats_received": self.heartbeats_received,
            "last_heartbeat": self.last_heartbeat, "restarts": self.restarts,
        }


@dataclass
class SupervisedAgent:
    """An agent running under supervision."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    quotas: AgentQuota = field(default_factory=AgentQuota)
    usage: AgentQuotaUsage = field(default_factory=AgentQuotaUsage)
    status: str = "pending"           # pending/running/paused/completed/failed/killed
    started_at: float = 0.0
    finished_at: float = 0.0
    result: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # Internal
    _task: asyncio.Task | None = field(default=None, repr=False)
    _heartbeat_task: asyncio.Task | None = field(default=None, repr=False)
    _pause_event: asyncio.Event | None = field(default=None, repr=False)
    _kill_event: asyncio.Event | None = field(default=None, repr=False)

    @property
    def is_alive(self) -> bool:
        return self.status in ("running", "paused")

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at if self.started_at else 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name,
            "quotas": {
                "max_duration_seconds": self.quotas.max_duration_seconds,
                "max_cost_usd": self.quotas.max_cost_usd,
                "max_tokens": self.quotas.max_tokens,
                "max_iterations": self.quotas.max_iterations,
            },
            "usage": self.usage.to_dict(),
            "status": self.status, "started_at": self.started_at,
            "finished_at": self.finished_at, "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class SupervisorConfig:
    """Global supervisor configuration."""
    max_children: int = 20
    monitor_interval: float = 1.0       # Seconds between health checks
    event_history_size: int = 500       # Max events to retain
    auto_kill_on_quota: bool = True
    log_events: bool = True


# ── Callback types ───────────────────────────────────────────────

EventCallback = Callable[[SupervisionEvent], None]


# ── Agent Supervisor ─────────────────────────────────────────────

class AgentSupervisor:
    """
    Hierarchical supervision tree for long-running multi-agent tasks.

    Monitors children for:
    - Resource quota violations (time, cost, tokens)
    - Heartbeat loss (crash/hang detection)
    - Progress stalls

    Actions:
    - Auto-kill runaway agents
    - Graceful restart (optional)
    - Event emission for external monitoring
    """

    def __init__(
        self,
        config: SupervisorConfig | None = None,
        on_event: EventCallback | None = None,
    ):
        self.config = config or SupervisorConfig()
        self._on_event = on_event
        self._children: dict[str, SupervisedAgent] = {}
        self._events: list[SupervisionEvent] = []
        self._monitor_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ── Public API ───────────────────────────────────────────────

    async def spawn(
        self,
        name: str,
        task: str = "",
        loop_factory: Callable[[], Any] | None = None,
        agent_loop: Any = None,
        quotas: AgentQuota | None = None,
        on_heartbeat: Callable[[], Coroutine] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Spawn a new child agent under supervision.

        Returns child_id for monitoring/control.
        """
        async with self._lock:
            if len(self._children) >= self.config.max_children:
                raise RuntimeError(f"Max children ({self.config.max_children}) reached")

            child = SupervisedAgent(
                name=name, quotas=quotas or AgentQuota(),
                metadata=metadata or {},
            )
            child._pause_event = asyncio.Event()
            child._pause_event.set()  # Not paused
            child._kill_event = asyncio.Event()

            self._children[child.id] = child
            self._emit(SupervisionEvent(SupervisionEventType.SPAWNED, child.id, name))

        # Start monitoring in background
        if not self._monitor_task or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())

        # Start heartbeat task
        if on_heartbeat:
            child._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(child, on_heartbeat)
            )

        # Start execution
        child._task = asyncio.create_task(
            self._run_child(child, task, loop_factory, agent_loop)
        )

        return child.id

    async def get_child(self, child_id: str) -> SupervisedAgent | None:
        """Get child agent by ID."""
        return self._children.get(child_id)

    async def list_children(self) -> list[SupervisedAgent]:
        """List all children with their status."""
        return list(self._children.values())

    async def await_child(self, child_id: str, timeout: float | None = None) -> Any:
        """Wait for a child to complete, return its result."""
        child = self._children.get(child_id)
        if not child:
            raise KeyError(f"Child {child_id} not found")
        if not child._task:
            raise RuntimeError(f"Child {child_id} has no running task")

        try:
            return await asyncio.wait_for(child._task, timeout=timeout)
        except asyncio.TimeoutError:
            # Kill the child on timeout
            await self.kill_child(child_id, reason="await timeout")
            raise

    async def pause_child(self, child_id: str) -> bool:
        """Pause a running child."""
        child = self._children.get(child_id)
        if not child or not child.is_alive or not child._pause_event:
            return False
        child._pause_event.clear()
        child.status = "paused"
        return True

    async def resume_child(self, child_id: str) -> bool:
        """Resume a paused child."""
        child = self._children.get(child_id)
        if not child or child.status != "paused" or not child._pause_event:
            return False
        child._pause_event.set()
        child.status = "running"
        self._emit(SupervisionEvent(SupervisionEventType.PROGRESS, child.id, child.name,
                                    message="Resumed"))
        return True

    async def kill_child(self, child_id: str, reason: str = "") -> bool:
        """Force-kill a child agent."""
        child = self._children.get(child_id)
        if not child or not child.is_alive:
            return False

        if child._kill_event:
            child._kill_event.set()
        if child._task and not child._task.done():
            child._task.cancel()

        child.status = "killed"
        child.finished_at = time.time()
        child.error = reason

        self._emit(SupervisionEvent(
            SupervisionEventType.KILLED, child.id, child.name,
            message=reason,
        ))
        return True

    async def aggregate_progress(self) -> dict[str, Any]:
        """Aggregate progress across all children."""
        children = list(self._children.values())
        total = len(children)
        completed = sum(1 for c in children if c.status == "completed")
        failed = sum(1 for c in children if c.status in ("failed", "killed"))
        running = sum(1 for c in children if c.status == "running")

        # Aggregate costs
        total_cost = sum(c.usage.cost_usd for c in children)
        total_tokens = sum(c.usage.tokens_used for c in children)

        return {
            "total_children": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "total_cost_usd": total_cost,
            "total_tokens": total_tokens,
            "percent_complete": (completed / total * 100) if total > 0 else 0,
            "children": [c.to_dict() for c in children],
        }

    async def shutdown(self, timeout: float = 10.0):
        """Graceful shutdown: pause new spawns, wait for children, kill stragglers."""
        # Kill all running children
        for child_id in list(self._children.keys()):
            await self.kill_child(child_id, reason="supervisor shutdown")

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()

        # Wait for children to die
        deadline = time.time() + timeout
        for child in self._children.values():
            if child._task and not child._task.done():
                remaining = max(0, deadline - time.time())
                try:
                    await asyncio.wait_for(child._task, timeout=remaining)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

    # ── Internal ─────────────────────────────────────────────────

    async def _run_child(
        self, child: SupervisedAgent, task: str,
        loop_factory: Callable[[], Any] | None,
        agent_loop: Any,
    ):
        """Execute a child agent with full supervision."""
        child.status = "running"
        child.started_at = time.time()
        self._emit(SupervisionEvent(SupervisionEventType.STARTED, child.id, child.name))

        try:
            if loop_factory:
                loop = loop_factory()
            elif agent_loop:
                loop = agent_loop
            else:
                raise ValueError("Must provide loop_factory or agent_loop")

            # Wrap loop to check for pause/kill signals
            original_on_iteration = getattr(loop, 'on_iteration', None)

            async def supervised_on_iteration(iteration: int, tool_results: list):
                # Check kill signal
                if child._kill_event and child._kill_event.is_set():
                    raise asyncio.CancelledError("Killed by supervisor")

                # Check pause signal
                if child._pause_event:
                    await child._pause_event.wait()

                # Update usage
                child.usage.iterations = iteration
                child.usage.elapsed_seconds = time.time() - child.started_at

                # Quota checks
                if child.usage.elapsed_seconds > child.quotas.max_duration_seconds:
                    if self.config.auto_kill_on_quota:
                        child._kill_event.set()
                        raise asyncio.TimeoutError("Duration quota exceeded")
                    else:
                        self._emit(SupervisionEvent(
                            SupervisionEventType.QUOTA_WARNING, child.id, child.name,
                            message=f"Duration at {child.usage.elapsed_seconds:.0f}s / {child.quotas.max_duration_seconds}s",
                        ))

                if original_on_iteration:
                    original_on_iteration(iteration, tool_results)

            loop.on_iteration = supervised_on_iteration

            # Run with retry logic
            for attempt in range(child.quotas.max_retries + 1):
                try:
                    result = await loop.run(task, session_id=child.id)
                    child.result = result.output if hasattr(result, 'output') else result
                    child.usage.cost_usd = getattr(result, 'cost_usd', 0.0)
                    child.usage.tokens_used = sum(getattr(result, 'tokens_used', {}).values())
                    child.status = "completed"
                    child.finished_at = time.time()
                    self._emit(SupervisionEvent(SupervisionEventType.COMPLETED, child.id, child.name))
                    return child.result
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    raise
                except Exception as e:
                    if attempt < child.quotas.max_retries:
                        # Check cooldown
                        since_last = time.time() - child.usage.last_restart
                        if child.usage.restarts > 0 and since_last < child.quotas.cooldown_period:
                            await asyncio.sleep(child.quotas.cooldown_period - since_last)
                        child.usage.restarts += 1
                        child.usage.last_restart = time.time()
                        await asyncio.sleep(child.quotas.retry_delay)
                        continue
                    child.status = "failed"
                    child.finished_at = time.time()
                    child.error = str(e)
                    self._emit(SupervisionEvent(
                        SupervisionEventType.FAILED, child.id, child.name,
                        message=str(e),
                    ))
                    raise

        except asyncio.CancelledError:
            child.status = "killed"
            child.finished_at = time.time()
        except Exception as e:
            child.status = "failed"
            child.finished_at = time.time()
            child.error = str(e)
            self._emit(SupervisionEvent(
                SupervisionEventType.FAILED, child.id, child.name,
                message=str(e),
            ))

    async def _heartbeat_loop(
        self, child: SupervisedAgent,
        on_heartbeat: Callable[[], Coroutine],
    ):
        """Send periodic heartbeats and update usage."""
        interval = child.quotas.heartbeat_interval
        while child.is_alive:
            try:
                await asyncio.sleep(interval)
                if not child.is_alive:
                    break
                await on_heartbeat()
                child.usage.heartbeats_received += 1
                child.usage.last_heartbeat = time.time()
                self._emit(SupervisionEvent(
                    SupervisionEventType.HEARTBEAT, child.id, child.name,
                    data={"heartbeats": child.usage.heartbeats_received},
                ))
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _monitor_loop(self):
        """Monitor all children for health and quota violations."""
        while True:
            try:
                await asyncio.sleep(self.config.monitor_interval)
                now = time.time()

                for child in list(self._children.values()):
                    if not child.is_alive:
                        continue

                    # Heartbeat timeout check
                    if (child.quotas.heartbeat_timeout > 0 and
                        child.usage.last_heartbeat > 0 and
                        now - child.usage.last_heartbeat > child.quotas.heartbeat_timeout):
                        self._emit(SupervisionEvent(
                            SupervisionEventType.HEARTBEAT_LOST, child.id, child.name,
                            message=f"No heartbeat for {now - child.usage.last_heartbeat:.0f}s",
                        ))
                        await self.kill_child(child.id, reason="heartbeat lost")

                    # Duration check
                    elapsed = now - child.started_at if child.started_at else 0
                    if elapsed > child.quotas.max_duration_seconds * 0.9:
                        self._emit(SupervisionEvent(
                            SupervisionEventType.QUOTA_WARNING, child.id, child.name,
                            message=f"90% duration used: {elapsed:.0f}s / {child.quotas.max_duration_seconds}s",
                        ))

            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def _emit(self, event: SupervisionEvent):
        """Emit a supervision event."""
        if self.config.log_events:
            self._events.append(event)
            if len(self._events) > self.config.event_history_size:
                self._events = self._events[-self.config.event_history_size:]

        if self._on_event:
            try:
                self._on_event(event)
            except Exception:
                pass
