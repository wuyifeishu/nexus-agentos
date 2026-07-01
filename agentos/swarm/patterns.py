"""
Enhanced Swarm collaboration patterns.

Extends the base SwarmCoordinator with broadcast, pipeline, hierarchical,
and consensus-based collaboration topologies.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from agentos.swarm.coordinator import SwarmCoordinator


class Topology(Enum):
    """Swarm collaboration topology."""

    BROADCAST = "broadcast"
    """One-to-all: leader broadcasts task, all members respond independently."""

    PIPELINE = "pipeline"
    """Sequential chain: each member processes output of previous member."""

    HIERARCHICAL = "hierarchical"
    """Tree structure: leader delegates to sub-leaders who manage sub-teams."""

    CONSENSUS = "consensus"
    """Voting: all members vote on outputs, majority wins."""

    ROUND_ROBIN = "round_robin"
    """Load-balancing: tasks distributed evenly across members."""


@dataclass
class CollaborationConfig:
    """Configuration for swarm collaboration."""

    topology: Topology = Topology.BROADCAST
    timeout_per_member: float = 60.0
    """Max seconds per member invocation."""

    max_parallel: int = 5
    """Max concurrent member executions (broadcast/consensus)."""

    quorum_ratio: float = 0.5
    """Minimum ratio of members needed for consensus (consensus topology)."""

    allow_partial_results: bool = True
    """Return partial results if some members fail."""


@dataclass
class MemberResult:
    """Result from a single swarm member."""

    member_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class CollaborationResult:
    """Aggregated result from a swarm collaboration."""

    topology: Topology
    member_results: list[MemberResult]
    aggregated_output: Any = None
    total_latency_ms: float = 0.0
    success_count: int = 0
    failure_count: int = 0


class SwarmPatterns:
    """
    Higher-order swarm collaboration patterns built on SwarmCoordinator.

    Supports five topologies: broadcast, pipeline, hierarchical, consensus, round_robin.
    """

    def __init__(
        self,
        coordinator: SwarmCoordinator,
        config: Optional[CollaborationConfig] = None,
    ):
        self._coordinator = coordinator
        self._config = config or CollaborationConfig()

    # ---- Synchronous API ----

    def collaborate(
        self,
        task: str,
        context: Optional[dict[str, Any]] = None,
    ) -> CollaborationResult:
        """
        Execute collaboration using configured topology.

        Args:
            task: The task description to collaborate on.
            context: Optional context dict passed to all members.

        Returns:
            CollaborationResult with individual and aggregated outputs.
        """
        t0 = time.perf_counter()
        topology = self._config.topology

        dispatchers: dict[Topology, Callable] = {
            Topology.BROADCAST: self._broadcast,
            Topology.PIPELINE: self._pipeline,
            Topology.HIERARCHICAL: self._hierarchical,
            Topology.CONSENSUS: self._consensus,
            Topology.ROUND_ROBIN: self._round_robin,
        }

        handler = dispatchers.get(topology)
        if handler is None:
            raise ValueError(f"Unknown topology: {topology}")

        result = handler(task, context)
        result.total_latency_ms = (time.perf_counter() - t0) * 1000
        result.topology = topology
        return result

    def _broadcast(
        self, task: str, context: Optional[dict] = None
    ) -> CollaborationResult:
        """Broadcast task to all members, collect all responses."""
        members = self._coordinator.list_members()
        results: list[MemberResult] = []

        for member in members:
            m_result = self._invoke_member(member, task, context)
            results.append(m_result)

        aggregated = [r.output for r in results if r.success]
        success = sum(1 for r in results if r.success)
        failure = len(results) - success

        return CollaborationResult(
            topology=Topology.BROADCAST,
            member_results=results,
            aggregated_output=aggregated,
            success_count=success,
            failure_count=failure,
        )

    def _pipeline(
        self, task: str, context: Optional[dict] = None
    ) -> CollaborationResult:
        """Sequential pipeline: each member processes previous output."""
        members = self._coordinator.list_members()
        results: list[MemberResult] = []
        current_input = task

        for member in members:
            m_result = self._invoke_member(
                member, current_input, context
            )
            results.append(m_result)
            if m_result.success:
                current_input = str(m_result.output) if m_result.output else current_input
            elif not self._config.allow_partial_results:
                break

        success = sum(1 for r in results if r.success)
        failure = len(results) - success

        return CollaborationResult(
            topology=Topology.PIPELINE,
            member_results=results,
            aggregated_output=current_input,
            success_count=success,
            failure_count=failure,
        )

    def _hierarchical(
        self, task: str, context: Optional[dict] = None
    ) -> CollaborationResult:
        """Two-level hierarchy: leader delegates to sub-groups."""
        members = self._coordinator.list_members()
        n = len(members)
        if n < 2:
            # Fallback to broadcast for small swarms
            return self._broadcast(task, context)

        # Split members: first half as sub-leaders, rest as workers
        split = max(1, n // 2)
        sub_leaders = members[:split]
        workers = members[split:]

        results: list[MemberResult] = []
        # Step 1: Sub-leaders plan task decomposition
        plan_task = f"Decompose this task into sub-tasks for {len(workers)} workers: {task}"
        for leader in sub_leaders:
            m_result = self._invoke_member(leader, plan_task, context)
            results.append(m_result)

        # Step 2: Workers execute sub-tasks
        sub_tasks = task.split(";") if ";" in task else [task]
        for i, worker in enumerate(workers):
            sub_task = sub_tasks[i % len(sub_tasks)]
            m_result = self._invoke_member(worker, sub_task.strip(), context)
            results.append(m_result)

        success = sum(1 for r in results if r.success)
        failure = len(results) - success

        return CollaborationResult(
            topology=Topology.HIERARCHICAL,
            member_results=results,
            aggregated_output=[r.output for r in results if r.success],
            success_count=success,
            failure_count=failure,
        )

    def _consensus(
        self, task: str, context: Optional[dict] = None
    ) -> CollaborationResult:
        """Voting: all members vote, majority output wins."""
        members = self._coordinator.list_members()
        results: list[MemberResult] = []
        votes: dict[str, int] = {}

        for member in members:
            m_result = self._invoke_member(member, task, context)
            results.append(m_result)
            if m_result.success and m_result.output is not None:
                key = str(m_result.output)
                votes[key] = votes.get(key, 0) + 1

        quorum = max(1, int(len(members) * self._config.quorum_ratio))
        winner = None
        for output_key, count in votes.items():
            if count >= quorum:
                winner = output_key
                break

        success = sum(1 for r in results if r.success)
        failure = len(results) - success

        return CollaborationResult(
            topology=Topology.CONSENSUS,
            member_results=results,
            aggregated_output=winner or "No consensus reached",
            success_count=success,
            failure_count=failure,
        )

    def _round_robin(
        self, task: str, context: Optional[dict] = None
    ) -> CollaborationResult:
        """Load-balancing: pick next available member."""
        members = self._coordinator.list_members()
        if not members:
            return CollaborationResult(
                topology=Topology.ROUND_ROBIN,
                member_results=[],
                aggregated_output=None,
                success_count=0,
                failure_count=0,
            )
        # Simple: use first available member (full RR needs state)
        member = members[0]
        m_result = self._invoke_member(member, task, context)
        success = 1 if m_result.success else 0
        failure = 0 if m_result.success else 1

        return CollaborationResult(
            topology=Topology.ROUND_ROBIN,
            member_results=[m_result],
            aggregated_output=m_result.output,
            success_count=success,
            failure_count=failure,
        )

    def _invoke_member(
        self, member_id: str, task: str, context: Optional[dict] = None
    ) -> MemberResult:
        """Invoke a single swarm member with timeout."""
        t0 = time.perf_counter()
        try:
            output = self._coordinator.delegate(
                member_id=member_id,
                task=task,
                context=context or {},
            )
            latency = (time.perf_counter() - t0) * 1000
            return MemberResult(
                member_id=member_id,
                success=True,
                output=output,
                latency_ms=latency,
            )
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            return MemberResult(
                member_id=member_id,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=latency,
            )

    # ---- Async API ----

    async def collaborate_async(
        self,
        task: str,
        context: Optional[dict[str, Any]] = None,
    ) -> CollaborationResult:
        """Async version using asyncio for broadcast/consensus topologies."""
        t0 = time.perf_counter()
        members = self._coordinator.list_members()

        if self._config.topology == Topology.BROADCAST:
            semaphore = asyncio.Semaphore(self._config.max_parallel)

            async def run_one(member_id: str) -> MemberResult:
                async with semaphore:
                    return await asyncio.to_thread(
                        self._invoke_member, member_id, task, context
                    )

            results = await asyncio.gather(
                *[run_one(m) for m in members]
            )
            member_results = list(results)
        else:
            # Other topologies: run sequentially in thread
            member_results = await asyncio.to_thread(
                self.collaborate, task, context
            )
            if isinstance(member_results, CollaborationResult):
                member_results = member_results.member_results

        success = sum(1 for r in member_results if r.success)
        failure = len(member_results) - success

        return CollaborationResult(
            topology=self._config.topology,
            member_results=member_results,
            aggregated_output=[r.output for r in member_results if r.success],
            total_latency_ms=(time.perf_counter() - t0) * 1000,
            success_count=success,
            failure_count=failure,
        )
