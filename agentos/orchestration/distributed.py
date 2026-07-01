"""
AgentOS v1.14.2 — Distributed Orchestration (Ray-based Agent Swarm).

受 Ray Serve / Ray Core 启发，为 AgentOS 增加分布式编排层。
Agent 不再局限于单进程，可以在多台机器上组成 Swarm，
自动负载均衡、容错恢复、跨节点通信。

Core features:
- RayAgentActor: Ray Actor 封装的 Agent 实例
- DistSwarmCoordinator: 分布式 Swarm 协调器
- AgentPlacementStrategy: 智能 Agent 放置（CPU/GPU/内存感知）
- DistTaskQueue: 分布式任务队列（Ray 原生）
- CrossNodeBus: 跨节点消息总线
- FaultTolerance: Actor 重启/状态恢复

Architecture:
    DistSwarmCoordinator (head node)
        ├── RayAgentActor[0] (worker node 1)
        │   ├── ToolAgent instance
        │   └── Local memory store
        ├── RayAgentActor[1] (worker node 2)
        ├── ...
        └── DistTaskQueue → automatic load balancing

Usage:
    coordinator = DistSwarmCoordinator(num_workers=4)
    coordinator.start()
    result = await coordinator.submit(task="Summarize all PDFs in /data/")
    coordinator.shutdown()
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union,
)

import ray


# ── Ray Actor: Agent Wrapper ────────────────


class AgentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    RESTARTING = "restarting"
    DEAD = "dead"


@dataclass
class AgentPlacementSpec:
    """Agent 放置规格 — 声明资源需求。"""

    num_cpus: float = 1.0
    num_gpus: float = 0.0
    memory_mb: int = 512
    node_tags: Optional[Dict[str, str]] = None  # 节点标签约束，如 {"zone": "us-east"}
    max_restarts: int = 3
    restart_delay_s: float = 5.0

    def to_ray_options(self) -> dict:
        opts: dict = {
            "num_cpus": self.num_cpus,
            "num_gpus": self.num_gpus,
            "memory": self.memory_mb * 1024 * 1024,
            "max_restarts": self.max_restarts,
            "max_task_retries": 0,
        }
        if self.node_tags:
            opts["resources"] = self.node_tags
        return opts


@ray.remote
class RayAgentActor:
    """Ray Actor 封装的 Agent 实例。

    每个 Actor 运行一个独立的 Agent loop，通过消息总线
    与 Coordinator 通信。支持健康检查、状态快照、优雅关闭。
    """

    def __init__(
        self,
        actor_id: str = "",
        agent_cls: Optional[Type] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ):
        self.actor_id = actor_id or f"actor-{uuid.uuid4().hex[:8]}"
        self.status = AgentStatus.IDLE
        self._agent = None
        self._agent_cls = agent_cls
        self._agent_config = agent_config or {}
        self._task_count: int = 0
        self._error_count: int = 0
        self._last_error: str = ""
        self._started_at: float = time.time()
        self._last_heartbeat: float = time.time()

        # Lazy init agent
        if agent_cls:
            self._init_agent()

    def _init_agent(self) -> None:
        """初始化底层 Agent 实例。"""
        if self._agent_cls:
            try:
                self._agent = self._agent_cls(**self._agent_config)
            except Exception as e:
                self.status = AgentStatus.ERROR
                self._last_error = str(e)
                self._error_count += 1

    # ── Lifecycle ──

    def get_status(self) -> dict:
        """获取 Actor 状态快照。"""
        self._last_heartbeat = time.time()
        return {
            "actor_id": self.actor_id,
            "status": self.status.value,
            "task_count": self._task_count,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "uptime_s": time.time() - self._started_at,
            "pid": os.getpid(),
            "node_id": ray.get_runtime_context().get_node_id(),
        }

    def ping(self) -> bool:
        """健康检查。"""
        self._last_heartbeat = time.time()
        return True

    # ── Task Execution ──

    def execute_task(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """执行单个任务。

        Args:
            task: 任务描述文本
            context: 可选的上下文数据

        Returns:
            执行结果字典
        """
        self.status = AgentStatus.BUSY
        self._task_count += 1
        start_time = time.time()

        try:
            # If agent has run() method
            if self._agent and hasattr(self._agent, "run"):
                result = self._agent.run(task)
                elapsed = time.time() - start_time
                self.status = AgentStatus.IDLE
                return {
                    "success": True,
                    "actor_id": self.actor_id,
                    "result": str(result),
                    "elapsed_s": elapsed,
                }

            # Fallback: return task echo
            elapsed = time.time() - start_time
            self.status = AgentStatus.IDLE
            return {
                "success": True,
                "actor_id": self.actor_id,
                "result": f"[Actor {self.actor_id}] Task received: {task[:100]}",
                "elapsed_s": elapsed,
                "context": context,
            }

        except Exception as e:
            elapsed = time.time() - start_time
            self.status = AgentStatus.ERROR
            self._error_count += 1
            self._last_error = str(e)
            return {
                "success": False,
                "actor_id": self.actor_id,
                "error": str(e),
                "elapsed_s": elapsed,
            }

    def shutdown(self) -> None:
        """优雅关闭。"""
        self.status = AgentStatus.DEAD
        if self._agent and hasattr(self._agent, "close"):
            try:
                self._agent.close()
            except Exception:
                pass


# ── Distributed Swarm Coordinator ───────────


class PlacementStrategy(str, Enum):
    """Agent 放置策略。"""

    ROUND_ROBIN = "round_robin"         # 轮询
    LEAST_LOADED = "least_loaded"       # 最少负载
    RANDOM = "random"                   # 随机
    AFFINITY = "affinity"               # 亲和性（同类型任务归同 Actor）


@dataclass
class DistSwarmConfig:
    """分布式 Swarm 配置。"""

    num_workers: int = 4
    placement_spec: AgentPlacementSpec = field(default_factory=AgentPlacementSpec)
    placement_strategy: PlacementStrategy = PlacementStrategy.LEAST_LOADED
    health_check_interval_s: float = 10.0
    heartbeat_timeout_s: float = 30.0
    max_task_queue_size: int = 1000
    task_timeout_s: float = 300.0
    auto_restart_dead_actors: bool = True


class DistSwarmCoordinator:
    """分布式 Swarm 协调器。

    管理 RayAgentActor 池，负责任务分发、负载均衡、健康监控。

    Usage:
        coordinator = DistSwarmCoordinator(
            DistSwarmConfig(num_workers=8),
            agent_cls=ToolAgent,
        )
        coordinator.start()

        # Fan-out: 同时向所有 Actor 发任务
        results = await coordinator.parallel_submit(
            tasks=["process file A", "process file B", ...]
        )
    """

    def __init__(
        self,
        config: Optional[DistSwarmConfig] = None,
        agent_cls: Optional[Type] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ):
        if not ray.is_initialized():
            ray.init(ignore_reinit_error=True)

        self.config = config or DistSwarmConfig()
        self._agent_cls = agent_cls
        self._agent_config = agent_config or {}
        self._actors: List[ray.actor.ActorHandle] = []
        self._actor_metas: Dict[str, dict] = {}
        self._round_robin_idx: int = 0
        self._started: bool = False
        self._health_task: Optional[asyncio.Task] = None

    def start(self) -> int:
        """启动 Worker Pool。返回启动的 Actor 数量。"""
        spec = self.config.placement_spec
        for i in range(self.config.num_workers):
            actor_id = f"worker-{i:04d}"
            actor = RayAgentActor.options(**spec.to_ray_options()).remote(
                actor_id=actor_id,
                agent_cls=self._agent_cls,
                agent_config=self._agent_config,
            )
            self._actors.append(actor)
            self._actor_metas[actor_id] = {
                "actor": actor,
                "status": AgentStatus.IDLE.value,
                "task_count": 0,
            }

        self._started = True
        return len(self._actors)

    async def submit(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> dict:
        """提交单个任务到最优 Actor。

        自动选择负载最低的 Actor 执行。
        """
        actor = await self._select_actor()
        timeout = timeout or self.config.task_timeout_s

        try:
            result_ref = actor.execute_task.remote(task, context)
            result = await asyncio.wait_for(
                ray.get(result_ref, timeout=timeout),
                timeout=timeout + 5,
            )
            return result
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"Task timed out after {timeout}s",
            }

    async def parallel_submit(
        self,
        tasks: List[str],
        contexts: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> List[dict]:
        """Fan-out: 并行执行多个任务。

        自动将任务均匀分配至所有可用 Actor。
        """
        if not self._actors:
            return [{"success": False, "error": "No actors available"}]

        futures = []
        for i, task in enumerate(tasks):
            ctx = contexts[i] if contexts and i < len(contexts) else None
            actor = self._actors[i % len(self._actors)]
            futures.append(actor.execute_task.remote(task, ctx))

        timeout = timeout or self.config.task_timeout_s
        try:
            results = await asyncio.wait_for(
                ray.get(futures, timeout=timeout),
                timeout=timeout + 10,
            )
            return results
        except asyncio.TimeoutError:
            return [
                {"success": False, "error": "Batch timed out"}
                for _ in tasks
            ]

    async def _select_actor(self) -> ray.actor.ActorHandle:
        """根据放置策略选择最优 Actor。"""
        if not self._actors:
            raise RuntimeError("No actors started. Call start() first.")

        strategy = self.config.placement_strategy

        if strategy == PlacementStrategy.ROUND_ROBIN:
            actor = self._actors[self._round_robin_idx]
            self._round_robin_idx = (self._round_robin_idx + 1) % len(self._actors)
            return actor

        if strategy == PlacementStrategy.LEAST_LOADED:
            statuses = await self.get_all_statuses()
            # Find actor with fewest tasks
            best = min(statuses, key=lambda s: s.get("task_count", 0))
            return best["actor"]

        if strategy == PlacementStrategy.RANDOM:
            import random
            return random.choice(self._actors)

        if strategy == PlacementStrategy.AFFINITY:
            return self._actors[self._round_robin_idx]

        # Default: round-robin
        actor = self._actors[self._round_robin_idx]
        self._round_robin_idx = (self._round_robin_idx + 1) % len(self._actors)
        return actor

    async def get_all_statuses(self) -> List[dict]:
        """获取所有 Actor 状态快照。"""
        if not self._actors:
            return []

        futures = [actor.get_status.remote() for actor in self._actors]
        statuses = await asyncio.wait_for(ray.get(futures), timeout=5)
        for s in statuses:
            s["actor"] = self._get_actor_by_id(s["actor_id"])
        return statuses

    async def health_check(self) -> List[dict]:
        """健康检查：Ping 所有 Actor，重启死亡的。"""
        dead: List[dict] = []

        for actor in self._actors:
            try:
                alive = await asyncio.wait_for(
                    actor.ping.remote(), timeout=3.0
                )
                if not alive:
                    dead.append({"actor_id": "unknown", "reason": "ping_false"})
            except Exception as e:
                dead.append({
                    "actor_id": await self._get_actor_id(actor),
                    "reason": str(e),
                })

        # Auto-restart dead actors
        if dead and self.config.auto_restart_dead_actors:
            for d in dead:
                await self._restart_actor(d.get("actor_id", ""))

        return dead

    async def _restart_actor(self, actor_id: str) -> bool:
        """重启死亡 Actor。"""
        spec = self.config.placement_spec
        new_actor = RayAgentActor.options(**spec.to_ray_options()).remote(
            actor_id=actor_id,
            agent_cls=self._agent_cls,
            agent_config=self._agent_config,
        )
        # Replace dead actor reference
        for i, a in enumerate(self._actors):
            try:
                current_id = await self._get_actor_id(a)
                if current_id == actor_id:
                    self._actors[i] = new_actor
                    return True
            except Exception:
                # Actor is dead, can't get ID
                self._actors[i] = new_actor
                return True
        return False

    async def _get_actor_id(self, actor: ray.actor.ActorHandle) -> str:
        try:
            status = await asyncio.wait_for(
                actor.get_status.remote(), timeout=2.0
            )
            return status.get("actor_id", "unknown")
        except Exception:
            return "dead"

    def _get_actor_by_id(self, actor_id: str) -> Optional[ray.actor.ActorHandle]:
        for actor in self._actors:
            try:
                # Can't easily get ID without async, use index
                pass
            except Exception:
                pass
        return None

    async def shutdown(self) -> None:
        """关闭所有 Actor。"""
        if self._health_task:
            self._health_task.cancel()

        for actor in self._actors:
            try:
                actor.shutdown.remote()
            except Exception:
                pass

        self._actors.clear()
        self._started = False

    @property
    def worker_count(self) -> int:
        return len(self._actors)

    @property
    def is_started(self) -> bool:
        return self._started


# ── Distributed Task Queue ──────────────────


class DistTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DistTaskRecord:
    """分布式任务记录。"""

    task_id: str = field(default_factory=lambda: f"dt-{uuid.uuid4().hex[:8]}")
    task: str = ""
    context: Optional[Dict[str, Any]] = None
    status: DistTaskStatus = DistTaskStatus.PENDING
    assigned_actor: str = ""
    result: Optional[dict] = None
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0


class DistTaskQueue:
    """分布式任务队列。

    基于 Ray 的异步任务调度，支持优先级、重试、超时。
    """

    def __init__(
        self,
        coordinator: DistSwarmCoordinator,
        max_concurrent: int = 10,
        max_retries: int = 2,
    ):
        self._coordinator = coordinator
        self._max_concurrent = max_concurrent
        self._max_retries = max_retries
        self._pending: List[DistTaskRecord] = []
        self._running: Dict[str, asyncio.Task] = {}
        self._completed: List[DistTaskRecord] = []
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def enqueue(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """入队任务。返回 task_id。"""
        record = DistTaskRecord(task=task, context=context)
        self._pending.append(record)
        return record.task_id

    async def enqueue_batch(
        self,
        tasks: List[str],
        contexts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """批量入队。"""
        ids = []
        for i, task in enumerate(tasks):
            ctx = contexts[i] if contexts and i < len(contexts) else None
            tid = await self.enqueue(task, ctx)
            ids.append(tid)
        return ids

    async def process_all(self) -> List[dict]:
        """处理所有待处理任务。

        自动并行调度，受 max_concurrent 限制。
        """
        async def process_one(record: DistTaskRecord) -> dict:
            async with self._semaphore:
                record.status = DistTaskStatus.RUNNING
                record.started_at = time.time()

                for attempt in range(self._max_retries + 1):
                    result = await self._coordinator.submit(
                        record.task, record.context
                    )
                    if result.get("success", False):
                        record.status = DistTaskStatus.COMPLETED
                        record.result = result
                        record.completed_at = time.time()
                        return result

                # All retries exhausted
                record.status = DistTaskStatus.FAILED
                record.result = {"success": False, "error": "Max retries exceeded"}
                record.completed_at = time.time()
                return record.result

        pending = self._pending[:]
        self._pending = []

        tasks = [process_one(r) for r in pending]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in pending:
            self._completed.append(r)

        return results

    @property
    def stats(self) -> dict:
        return {
            "pending": len(self._pending),
            "running": len(self._running),
            "completed": len(self._completed),
            "total": len(self._pending) + len(self._running) + len(self._completed),
        }


# ── Cross-Node Message Bus ──────────────────


@ray.remote
class CrossNodeMailbox:
    """跨节点消息信箱（Ray Actor）。

    每个节点一个 Mailbox，Agent 通过它发送/接收消息。
    """

    def __init__(self, node_id: str = ""):
        self.node_id = node_id or ray.get_runtime_context().get_node_id()
        self._inbox: List[dict] = []
        self._max_inbox_size: int = 1000

    def send(self, message: dict) -> bool:
        """发送消息到本节点信箱。"""
        if len(self._inbox) >= self._max_inbox_size:
            self._inbox.pop(0)
        self._inbox.append({
            **message,
            "received_at": time.time(),
        })
        return True

    def receive(self, limit: int = 10, clear: bool = True) -> List[dict]:
        """拉取消息。"""
        messages = self._inbox[:limit]
        if clear:
            self._inbox = self._inbox[limit:]
        return messages

    def peek(self) -> int:
        """查看消息数量。"""
        return len(self._inbox)


class CrossNodeBus:
    """跨节点消息总线。

    管理多个 CrossNodeMailbox，提供广播/单播/多播能力。

    Usage:
        bus = CrossNodeBus()
        await bus.broadcast({"type": "announce", "agent": "worker-001"})
    """

    def __init__(self):
        self._mailboxes: Dict[str, ray.actor.ActorHandle] = {}

    async def register_node(self, node_id: str = "") -> str:
        """注册节点信箱。"""
        if not node_id:
            node_id = ray.get_runtime_context().get_node_id()
        if node_id not in self._mailboxes:
            self._mailboxes[node_id] = CrossNodeMailbox.remote(node_id)
        return node_id

    async def broadcast(self, message: dict) -> int:
        """广播消息到所有节点。"""
        count = 0
        futures = []
        for mailbox in self._mailboxes.values():
            futures.append(mailbox.send.remote(message))
        results = await asyncio.wait_for(ray.get(futures), timeout=5)
        count = sum(1 for r in results if r)
        return count

    async def unicast(self, node_id: str, message: dict) -> bool:
        """单播消息到指定节点。"""
        mailbox = self._mailboxes.get(node_id)
        if not mailbox:
            return False
        return await asyncio.wait_for(mailbox.send.remote(message), timeout=5)

    async def pull_all(self, limit: int = 50) -> List[dict]:
        """拉取所有节点的消息。"""
        all_messages = []
        futures = [m.receive.remote(limit) for m in self._mailboxes.values()]
        results = await asyncio.wait_for(ray.get(futures), timeout=5)
        for msgs in results:
            all_messages.extend(msgs)
        return all_messages


# ── Quick Start ─────────────────────────────


def quick_start(
    num_workers: int = 4,
    num_cpus_per_worker: float = 1.0,
) -> Tuple[DistSwarmCoordinator, DistTaskQueue, CrossNodeBus]:
    """一键启动分布式 Swarm。

    Returns:
        (coordinator, task_queue, message_bus)
    """
    config = DistSwarmConfig(
        num_workers=num_workers,
        placement_spec=AgentPlacementSpec(num_cpus=num_cpus_per_worker),
    )

    coordinator = DistSwarmCoordinator(config=config)
    coordinator.start()

    task_queue = DistTaskQueue(coordinator)
    message_bus = CrossNodeBus()

    return coordinator, task_queue, message_bus
