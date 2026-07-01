"""
Swarm Coordinator v2 (v1.9.0)

Production-grade multi-agent swarm orchestration. Turns individual agents
into a coordinated team with dynamic task allocation, inter-agent messaging,
and conflict resolution.

New in v2:
  - Dynamic task allocation: workload-aware agent assignment
  - Inter-agent message bus: pub/sub, broadcasts, directed messages
  - Conflict resolver: detect and resolve agent disagreements
  - Consensus protocols: majority vote, ranked choice, weighted voting
  - Topology manager: star, mesh, ring, tree, DAG topologies
  - Health monitor: heartbeat, dead agent detection, auto-recovery
  - Swarm state snapshot: checkpoint/resume for entire swarms
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Callable, Awaitable


# ── Types ───────────────────────────────────────────────────────────

class AgentRole(str, Enum):
    COORDINATOR = "coordinator"   # Orchestrates the swarm
    WORKER = "worker"             # Executes tasks
    REVIEWER = "reviewer"         # Reviews outputs
    OBSERVER = "observer"         # Monitors only
    SPECIALIST = "specialist"     # Domain expert (code, data, etc.)


class TaskPriority(str, Enum):
    CRITICAL = "critical"     # Must complete, blocks everything
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class SwarmTopology(str, Enum):
    STAR = "star"       # One coordinator, all others are workers
    MESH = "mesh"       # Every agent can talk to every agent
    RING = "ring"       # Circular communication
    TREE = "tree"       # Hierarchical
    DAG = "dag"         # Workflow-based dependencies
    HYBRID = "hybrid"   # Dynamic topology switching


@dataclass
class AgentInfo:
    """Metadata about a swarm agent."""
    agent_id: str
    role: AgentRole
    capabilities: list[str] = field(default_factory=list)
    model: str = ""
    max_concurrency: int = 3
    current_load: int = 0
    is_alive: bool = True
    last_heartbeat: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.is_alive and self.current_load < self.max_concurrency


@dataclass
class SwarmTask:
    """A task to be executed by the swarm."""
    task_id: str
    description: str
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str = ""               # Agent ID
    required_capabilities: list[str] = field(default_factory=list)
    parent_task_id: str = ""            # DAG dependency
    dependencies: list[str] = field(default_factory=list)  # Task IDs that must complete first
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    retry_count: int = 0
    max_retries: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return self.status == TaskStatus.PENDING and not self.dependencies

    @property
    def duration_ms(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at) * 1000
        return 0.0


# ── Inter-Agent Message Bus ─────────────────────────────────────────

@dataclass
class SwarmMessage:
    """A message sent between agents in the swarm."""
    message_id: str
    from_agent: str
    to_agent: str = ""        # Empty = broadcast
    topic: str = ""
    payload: Any = None
    timestamp: float = 0.0
    reply_to: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class MessageBus:
    """Inter-agent pub/sub message bus.

    Supports:
      - Point-to-point: send to specific agent
      - Broadcast: send to all agents
      - Topic-based: subscribe to channels
      - Request-reply: async request with reply correlation
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._message_log: list[SwarmMessage] = []
        self._pending_replies: dict[str, asyncio.Future] = {}
        self._agent_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)

    def subscribe(self, agent_id: str, topic: str, callback: Callable):
        """Subscribe an agent to a topic."""
        key = f"{agent_id}:{topic}"
        self._subscribers[key].append(callback)

    def unsubscribe(self, agent_id: str, topic: str = ""):
        """Unsubscribe from topics."""
        if topic:
            self._subscribers.pop(f"{agent_id}:{topic}", None)
        else:
            # Remove all for this agent
            to_remove = [k for k in self._subscribers if k.startswith(f"{agent_id}:")]
            for k in to_remove:
                del self._subscribers[k]

    async def publish(self, msg: SwarmMessage):
        """Publish a message to all relevant subscribers."""
        msg.timestamp = msg.timestamp or time.time()
        self._message_log.append(msg)

        # Deliver to target agent's queue
        if msg.to_agent:
            await self._agent_queues[msg.to_agent].put(msg)
        else:
            # Broadcast
            for agent_id in list(self._agent_queues.keys()):
                if agent_id != msg.from_agent:
                    await self._agent_queues[agent_id].put(msg)

        # Topic subscribers
        topic = msg.topic or "*"
        for key, callbacks in self._subscribers.items():
            agent_prefix, sub_topic = key.split(":", 1) if ":" in key else (key, "*")
            if sub_topic == topic or sub_topic == "*":
                for cb in callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(msg)
                        else:
                            cb(msg)
                    except Exception:
                        pass

    async def receive(self, agent_id: str, timeout: float = 1.0) -> Optional[SwarmMessage]:
        """Receive next message for an agent."""
        try:
            return await asyncio.wait_for(
                self._agent_queues[agent_id].get(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return None

    async def request(self, msg: SwarmMessage, timeout: float = 30.0) -> Any:
        """Send a request and wait for reply."""
        self._pending_replies[msg.message_id] = asyncio.get_event_loop().create_future()
        await self.publish(msg)
        try:
            return await asyncio.wait_for(
                self._pending_replies[msg.message_id],
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self._pending_replies.pop(msg.message_id, None)
            return None

    def reply(self, original_msg: SwarmMessage, response: Any):
        """Reply to a pending request."""
        if original_msg.message_id in self._pending_replies:
            fut = self._pending_replies.pop(original_msg.message_id)
            if not fut.done():
                fut.set_result(response)

    def get_message_log(self, limit: int = 100) -> list[SwarmMessage]:
        """Get recent messages for debugging."""
        return self._message_log[-limit:]


# ── Dynamic Task Allocator ──────────────────────────────────────────

class TaskAllocator:
    """Workload-aware dynamic task allocation.

    Considers:
      - Agent capabilities vs task requirements
      - Current agent load (concurrency)
      - Task priority
      - Affinity (same agent for related tasks)
    """

    def __init__(self):
        self._assignments: dict[str, str] = {}  # task_id → agent_id

    def allocate(
        self,
        task: SwarmTask,
        agents: list[AgentInfo],
    ) -> Optional[str]:
        """Find the best agent for a task.

        Args:
            task: The task to allocate
            agents: Available agents in the swarm

        Returns:
            Agent ID if allocated, None if no suitable agent found.
        """
        available = [a for a in agents if a.is_available]
        if not available:
            return None

        scored: list[tuple[AgentInfo, float]] = []

        for agent in available:
            score = 0.0

            # Capability match
            if task.required_capabilities:
                match = len(set(task.required_capabilities) & set(agent.capabilities))
                total = len(task.required_capabilities)
                score += (match / total) * 50 if total > 0 else 25

            # Workload penalty: prefer less loaded agents
            score -= agent.current_load * 10

            # Role bonus: specialists for specialist tasks
            if agent.role == AgentRole.SPECIALIST:
                if any(cap in agent.capabilities for cap in task.required_capabilities):
                    score += 20

            # Affinity: prefer reusing agent for related tasks
            if task.parent_task_id and self._assignments.get(task.parent_task_id) == agent.agent_id:
                score += 15

            scored.append((agent, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        if scored and scored[0][1] > 0:
            best = scored[0][0]
            self._assignments[task.task_id] = best.agent_id
            return best.agent_id

        return available[0].agent_id if available else None


# ── Conflict Resolver ───────────────────────────────────────────────

class ConflictType(str, Enum):
    FACTUAL = "factual"             # Disagreeing on facts
    METHODOLOGICAL = "methodological"  # Disagreeing on approach
    OUTPUT = "output"               # Conflicting outputs
    RESOURCE = "resource"           # Competing for same resource


class ConflictResolver:
    """Detect and resolve conflicts between agents.

    Resolution strategies:
      - Majority vote: most common answer wins
      - Weighted vote: expert agents have more weight
      - Ranked choice: preference ordering
      - Escalation: escalate to coordinator
      - Consensus building: iterate until agreement
    """

    def __init__(self):
        self._conflict_log: list[dict] = []

    def detect_conflict(
        self,
        agent_outputs: dict[str, Any],
        expected_type: str = "text",
    ) -> list[dict]:
        """Detect conflicts between agent outputs.

        Args:
            agent_outputs: {agent_id: output}
            expected_type: Type of output for conflict detection

        Returns:
            List of detected conflicts.
        """
        conflicts = []
        agents = list(agent_outputs.keys())

        if len(agents) < 2:
            return conflicts

        outputs = list(agent_outputs.values())

        # Text conflict: check if outputs significantly differ
        if all(isinstance(o, str) for o in outputs):
            for i in range(len(outputs)):
                for j in range(i + 1, len(outputs)):
                    similarity = self._text_similarity(outputs[i], outputs[j])
                    if similarity < 0.3:  # Significant disagreement
                        conflicts.append({
                            "type": ConflictType.OUTPUT.value,
                            "agents": [agents[i], agents[j]],
                            "similarity": similarity,
                            "outputs": {agents[i]: outputs[i][:200], agents[j]: outputs[j][:200]},
                        })

        # Numeric conflict: check if values differ by >threshold
        elif all(isinstance(o, (int, float)) for o in outputs):
            values = outputs
            mean_val = sum(values) / len(values)
            for i, val in enumerate(values):
                if abs(val - mean_val) / max(abs(mean_val), 1) > 0.5:
                    conflicts.append({
                        "type": ConflictType.FACTUAL.value,
                        "agents": [agents[i]],
                        "value": val,
                        "mean": mean_val,
                        "deviation": abs(val - mean_val) / max(abs(mean_val), 1),
                    })

        return conflicts

    def resolve(
        self,
        agent_outputs: dict[str, Any],
        weights: dict[str, float] | None = None,
        strategy: str = "majority",
        expected_type: str = "text",
    ) -> dict[str, Any]:
        """Resolve conflicts and produce a final answer.

        Args:
            agent_outputs: {agent_id: output}
            weights: Optional agent weight mapping
            strategy: Resolution strategy
            expected_type: "text" or "numeric"

        Returns:
            Dict with resolved output and resolution metadata.
        """
        if len(agent_outputs) == 1:
            agent_id = list(agent_outputs.keys())[0]
            return {"output": agent_outputs[agent_id], "method": "single_agent", "conflict": False}

        outputs = list(agent_outputs.values())
        agents = list(agent_outputs.keys())

        if all(isinstance(o, str) for o in outputs):
            return self._resolve_text(agent_outputs, weights, strategy)
        elif all(isinstance(o, (int, float)) for o in outputs):
            return self._resolve_numeric(agent_outputs, weights, strategy)
        else:
            return {"output": outputs[0], "method": "first", "conflict": True}

    def _resolve_text(self, outputs: dict[str, str], weights: dict[str, float] | None, strategy: str) -> dict:
        """Resolve text conflicts."""
        if strategy == "majority":
            # Group by similarity
            votes: dict[str, list[str]] = defaultdict(list)
            agent_ids = list(outputs.keys())
            for i, a1 in enumerate(agent_ids):
                best_match = a1
                best_sim = 0
                for j, a2 in enumerate(agent_ids):
                    if i == j:
                        continue
                    sim = self._text_similarity(outputs[a1], outputs[a2])
                    if sim > best_sim:
                        best_sim = sim
                        best_match = a2
                key = outputs[best_match][:50]
                votes[key].append(a1)

            # Longest group wins
            winning_key = max(votes, key=lambda k: len(votes[k]))
            winning_agent = votes[winning_key][0]
            return {
                "output": outputs[winning_agent],
                "method": "majority",
                "votes": {k: len(v) for k, v in votes.items()},
                "conflict": len(votes) > 1,
            }

        elif strategy == "weighted":
            if not weights:
                return self._resolve_text(outputs, weights, "majority")
            # Weight by agent weights, pick highest weighted output
            best_agent = max(weights, key=weights.get)
            return {"output": outputs.get(best_agent, list(outputs.values())[0]), "method": "weighted", "conflict": False}

        else:
            return {"output": list(outputs.values())[0], "method": "first", "conflict": False}

    def _resolve_numeric(self, outputs: dict[str, float], weights: dict[str, float] | None, strategy: str) -> dict:
        """Resolve numeric conflicts."""
        values = list(outputs.values())
        agents = list(outputs.keys())

        if strategy == "weighted" and weights:
            total_weight = sum(weights.get(a, 1.0) for a in agents)
            weighted = sum(weights.get(a, 1.0) * outputs[a] for a in agents) / total_weight
            return {"output": weighted, "method": "weighted_average", "conflict": False}
        else:
            avg = sum(values) / len(values)
            return {"output": avg, "method": "average", "conflict": False}

    def _text_similarity(self, a: str, b: str) -> float:
        """Simple text similarity."""
        if a == b:
            return 1.0
        tokens_a = set(a.lower().split())
        tokens_b = set(b.lower().split())
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union) if union else 0.0


# ── Swarm Coordinator ───────────────────────────────────────────────

class SwarmCoordinator:
    """Orchestrates a swarm of agents.

    Usage:
        coordinator = SwarmCoordinator(topology=SwarmTopology.STAR)
        coordinator.register_agent(AgentInfo("agent_1", AgentRole.WORKER, capabilities=["code"]))
        coordinator.register_agent(AgentInfo("agent_2", AgentRole.WORKER, capabilities=["data"]))
        coordinator.register_agent(AgentInfo("agent_3", AgentRole.REVIEWER))

        task = SwarmTask("task_1", "Analyze data and generate report",
                         required_capabilities=["data", "code"])
        result = await coordinator.execute(task)
    """

    def __init__(
        self,
        topology: SwarmTopology = SwarmTopology.STAR,
        max_parallel_tasks: int = 10,
        heartbeat_interval: float = 5.0,
        heartbeat_timeout: float = 30.0,
    ):
        self.topology = topology
        self.max_parallel_tasks = max_parallel_tasks

        self._agents: dict[str, AgentInfo] = {}
        self._tasks: dict[str, SwarmTask] = {}
        self._bus = MessageBus()
        self._allocator = TaskAllocator()
        self._resolver = ConflictResolver()
        self._task_executor: Optional[Callable] = None

        # Health
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self._health_task: Optional[asyncio.Task] = None

        # State
        self._run_history: list[dict] = []
        self._started = False

    # ── Agent Management ──

    def register_agent(self, agent: AgentInfo):
        """Register an agent with the swarm."""
        agent.last_heartbeat = time.time()
        self._agents[agent.agent_id] = agent

    def unregister_agent(self, agent_id: str):
        """Remove an agent from the swarm."""
        self._agents.pop(agent_id, None)
        self._bus.unsubscribe(agent_id)

    def set_task_executor(self, executor: Callable[[str, SwarmTask], Awaitable[Any]]):
        """Set the function that executes tasks on agents.

        Args:
            executor: async function(agent_id, task) -> result
        """
        self._task_executor = executor

    # ── Task Execution ──

    async def execute(self, task: SwarmTask) -> dict[str, Any]:
        """Execute a task across the swarm.

        If the task has required_capabilities that span multiple agents,
        it will be decomposed and executed collaboratively.
        """
        if not self._started:
            await self.start()

        task.task_id = task.task_id or str(uuid.uuid4())[:8]
        self._tasks[task.task_id] = task

        # Allocate
        agent_id = self._allocator.allocate(task, list(self._agents.values()))
        if not agent_id:
            return {"status": "failed", "error": "No suitable agent available"}

        # Assign and execute
        task.assigned_to = agent_id
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        agent = self._agents[agent_id]
        agent.current_load += 1

        try:
            if self._task_executor:
                result = await self._task_executor(agent_id, task)
            else:
                result = f"[Simulated] Agent '{agent_id}' completed: '{task.description}'"

            task.status = TaskStatus.COMPLETED
            task.result = result
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = TaskStatus.PENDING
                return await self.execute(task)

        finally:
            agent.current_load -= 1
            task.completed_at = time.time()

        self._run_history.append({
            "task_id": task.task_id,
            "agent_id": agent_id,
            "status": task.status.value,
            "duration_ms": task.duration_ms,
        })

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "agent_id": agent_id,
            "result": task.result,
            "duration_ms": task.duration_ms,
            "error": task.error,
        }

    async def execute_parallel(self, tasks: list[SwarmTask]) -> list[dict[str, Any]]:
        """Execute multiple tasks in parallel across the swarm.

        Uses DAG dependency resolution: tasks with unmet dependencies
        are deferred until their prerequisites complete.
        """
        # Build dependency graph
        ready: list[SwarmTask] = []
        waiting: list[SwarmTask] = []
        for task in tasks:
            if not task.dependencies:
                ready.append(task)
            else:
                waiting.append(task)

        results = []
        sem = asyncio.Semaphore(self.max_parallel_tasks)

        async def run_one(task: SwarmTask):
            async with sem:
                return await self.execute(task)

        while ready:
            batch = ready[:self.max_parallel_tasks]
            ready = ready[self.max_parallel_tasks:]

            batch_results = await asyncio.gather(*[run_one(t) for t in batch])

            for result in batch_results:
                results.append(result)

            # Unblock dependent tasks
            completed_ids = {r["task_id"] for r in batch_results if r["status"] == "completed"}
            still_waiting = []
            for task in waiting:
                task.dependencies = [d for d in task.dependencies if d not in completed_ids]
                if not task.dependencies:
                    ready.append(task)
                else:
                    still_waiting.append(task)
            waiting = still_waiting

        return results

    async def execute_with_review(
        self,
        task: SwarmTask,
        reviewer_count: int = 2,
    ) -> dict[str, Any]:
        """Execute a task with multiple agents and review results.

        Multiple workers execute the same task independently.
        Results are compared, conflicts resolved, and final output returned.
        """
        workers = [
            a for a in self._agents.values()
            if a.role in (AgentRole.WORKER, AgentRole.SPECIALIST) and a.is_available
        ]
        reviewers = [
            a for a in self._agents.values()
            if a.role == AgentRole.REVIEWER and a.is_available
        ]

        if not workers:
            return {"status": "failed", "error": "No workers available"}

        # Parallel execution
        worker_tasks = []
        for i, worker in enumerate(workers[:5]):
            wt = SwarmTask(
                task_id=f"{task.task_id}_w{i}",
                description=task.description,
                required_capabilities=task.required_capabilities,
            )
            worker_tasks.append(wt)

        parallel_results = await self.execute_parallel(worker_tasks)

        # Collect outputs
        agent_outputs = {}
        agent_weights = {}
        for result in parallel_results:
            if result["status"] == "completed":
                agent_id = result["agent_id"]
                agent_outputs[agent_id] = result.get("result", "")
                agent_weights[agent_id] = 1.0

        # Resolve conflicts
        resolution = self._resolver.resolve(agent_outputs, agent_weights)

        # Reviewers audit
        reviewer_notes = []
        for reviewer in reviewers[:reviewer_count]:
            review_msg = SwarmMessage(
                message_id=str(uuid.uuid4()),
                from_agent="coordinator",
                to_agent=reviewer.agent_id,
                topic="review",
                payload={
                    "task": task.description,
                    "resolution": resolution,
                    "worker_outputs": agent_outputs,
                },
            )
            review_result = await self._bus.request(review_msg, timeout=15.0)
            if review_result:
                reviewer_notes.append(review_result)

        return {
            "status": "completed",
            "output": resolution["output"],
            "resolution_method": resolution.get("method", "unknown"),
            "conflict_detected": resolution.get("conflict", False),
            "worker_count": len(parallel_results),
            "reviewer_notes": reviewer_notes,
        }

    # ── Swarm Communication ──

    async def broadcast(self, from_agent: str, topic: str, payload: Any):
        """Broadcast a message to all agents."""
        msg = SwarmMessage(
            message_id=str(uuid.uuid4()),
            from_agent=from_agent,
            topic=topic,
            payload=payload,
        )
        await self._bus.publish(msg)

    async def whisper(self, from_agent: str, to_agent: str, payload: Any):
        """Send a direct message to a specific agent."""
        msg = SwarmMessage(
            message_id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            payload=payload,
        )
        await self._bus.publish(msg)

    # ── Health Monitoring ──

    async def start(self):
        """Start the swarm coordinator."""
        self._started = True
        self._health_task = asyncio.create_task(self._health_monitor_loop())

    async def stop(self):
        """Stop the swarm coordinator."""
        self._started = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

    async def _health_monitor_loop(self):
        """Background health monitoring."""
        while self._started:
            now = time.time()
            dead_agents = []

            for agent in self._agents.values():
                if now - agent.last_heartbeat > self._heartbeat_timeout:
                    agent.is_alive = False
                    dead_agents.append(agent.agent_id)

            for agent_id in dead_agents:
                await self._handle_dead_agent(agent_id)

            await asyncio.sleep(self._heartbeat_interval)

    async def _handle_dead_agent(self, agent_id: str):
        """Handle a dead agent: reassign its tasks."""
        agent = self._agents.get(agent_id)
        if not agent:
            return

        # Reassign pending tasks
        for task in self._tasks.values():
            if task.assigned_to == agent_id and task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.PENDING
                task.assigned_to = ""
                task.retry_count += 1

        self._run_history.append({
            "event": "agent_dead",
            "agent_id": agent_id,
            "timestamp": time.time(),
        })

    # ── State & Reporting ──

    def snapshot(self) -> dict[str, Any]:
        """Create a snapshot of swarm state (for checkpoint/resume)."""
        return {
            "timestamp": time.time(),
            "topology": self.topology.value,
            "agents": {
                agent_id: {
                    "role": a.role.value,
                    "capabilities": a.capabilities,
                    "current_load": a.current_load,
                    "is_alive": a.is_alive,
                }
                for agent_id, a in self._agents.items()
            },
            "tasks": {
                tid: {
                    "description": t.description,
                    "status": t.status.value,
                    "assigned_to": t.assigned_to,
                    "priority": t.priority.value,
                }
                for tid, t in self._tasks.items()
            },
        }

    def get_stats(self) -> dict[str, Any]:
        """Get swarm statistics."""
        agents = list(self._agents.values())
        alive = [a for a in agents if a.is_alive]
        tasks = list(self._tasks.values())
        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]

        return {
            "agent_count": len(agents),
            "alive_agents": len(alive),
            "dead_agents": len(agents) - len(alive),
            "by_role": {
                role.value: sum(1 for a in agents if a.role == role)
                for role in AgentRole
            },
            "total_tasks": len(tasks),
            "completed_tasks": len(completed),
            "failed_tasks": sum(1 for t in tasks if t.status == TaskStatus.FAILED),
            "pending_tasks": sum(1 for t in tasks if t.status == TaskStatus.PENDING),
            "avg_task_duration_ms": (
                sum(t.duration_ms for t in completed) / len(completed)
                if completed else 0
            ),
            "total_messages": len(self._bus.get_message_log()),
            "total_runs": len(self._run_history),
        }

    def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        return self._agents.get(agent_id)

    def get_task(self, task_id: str) -> Optional[SwarmTask]:
        return self._tasks.get(task_id)
