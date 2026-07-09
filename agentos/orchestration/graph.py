"""
Graph Orchestrator for NexusAgent.

DAG-based workflow orchestration. Allows defining
complex workflows as graphs with nodes and edges.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeStatus(StrEnum):
    """Node execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class GraphNode:
    """
    Node in execution graph.

    Attributes:
        id: Unique identifier
        name: Node name
        func: Node function
        inputs: Input parameters
        outputs: Output values
        status: Execution status
        duration: Execution duration
        error: Error message (if failed)
        metadata: Additional metadata
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    func: Callable[..., Any] = None
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    status: NodeStatus = NodeStatus.PENDING
    duration: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "name": self.name,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "status": self.status.value,
            "duration": self.duration,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class GraphEdge:
    """
    Edge in execution graph.

    Attributes:
        source: Source node ID
        target: Target node ID
        condition: Optional condition function
        metadata: Additional metadata
    """

    source: str
    target: str
    condition: Callable[[dict[str, Any]], bool] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "source": self.source,
            "target": self.target,
            "metadata": self.metadata,
        }


@dataclass
class GraphResult:
    """
    Result of graph execution.

    Attributes:
        id: Unique identifier
        node_results: Node execution results
        total_duration: Total execution duration
        success: Whether execution succeeded
        error: Error message (if failed)
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    node_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_duration: float = 0.0
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "node_results": self.node_results,
            "total_duration": self.total_duration,
            "success": self.success,
            "error": self.error,
        }


class GraphOrchestrator:
    """
    DAG-based workflow orchestrator.

    Allows defining complex workflows as graphs:
    - Nodes represent tasks
    - Edges represent dependencies
    - Conditions for branching

    Usage:
        orchestrator = GraphOrchestrator()

        # Add nodes
        orchestrator.add_node("step1", step1_func)
        orchestrator.add_node("step2", step2_func)

        # Add edges
        orchestrator.add_edge("step1", "step2")

        # Execute
        result = await orchestrator.execute({"input": "data"})
    """

    def __init__(self):
        """Initialize graph orchestrator."""
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._start_nodes: list[str] = []
        self._end_nodes: list[str] = []

    def add_node(self, name: str, func: Callable[..., Any], **metadata) -> GraphNode:
        """
        Add a node to the graph.

        Args:
            name: Node name
            func: Node function
            **metadata: Additional metadata

        Returns:
            Created GraphNode
        """
        node = GraphNode(
            name=name,
            func=func,
            metadata=metadata,
        )
        self._nodes[name] = node

        # If first node, mark as start
        if len(self._nodes) == 1:
            self._start_nodes.append(name)

        return node

    def remove_node(self, name: str) -> bool:
        """
        Remove a node from the graph.

        Args:
            name: Node name

        Returns:
            True if removed, False if not found
        """
        if name not in self._nodes:
            return False

        del self._nodes[name]

        # Remove edges
        self._edges = [e for e in self._edges if e.source != name and e.target != name]

        # Update start/end nodes
        if name in self._start_nodes:
            self._start_nodes.remove(name)
        if name in self._end_nodes:
            self._end_nodes.remove(name)

        return True

    def add_edge(
        self,
        source: str,
        target: str,
        condition: Callable[[dict[str, Any]], bool] | None = None,
        **metadata,
    ) -> GraphEdge:
        """
        Add an edge to the graph.

        Args:
            source: Source node name
            target: Target node name
            condition: Optional condition function
            **metadata: Additional metadata

        Returns:
            Created GraphEdge
        """
        if source not in self._nodes:
            raise ValueError(f"Source node not found: {source}")
        if target not in self._nodes:
            raise ValueError(f"Target node not found: {target}")

        edge = GraphEdge(
            source=source,
            target=target,
            condition=condition,
            metadata=metadata,
        )
        self._edges.append(edge)

        # Update start/end nodes
        if target in self._start_nodes:
            self._start_nodes.remove(target)
        if source in self._end_nodes:
            self._end_nodes.remove(source)

        if source not in [e.target for e in self._edges]:
            if source not in self._start_nodes:
                self._start_nodes.append(source)

        if target not in [e.source for e in self._edges]:
            if target not in self._end_nodes:
                self._end_nodes.append(target)

        return edge

    def remove_edge(self, source: str, target: str) -> bool:
        """
        Remove an edge from the graph.

        Args:
            source: Source node name
            target: Target node name

        Returns:
            True if removed, False if not found
        """
        for edge in self._edges:
            if edge.source == source and edge.target == target:
                self._edges.remove(edge)
                return True
        return False

    def get_node(self, name: str) -> GraphNode | None:
        """
        Get a node by name.

        Args:
            name: Node name

        Returns:
            GraphNode if found, None otherwise
        """
        return self._nodes.get(name)

    def list_nodes(self) -> list[str]:
        """
        List all nodes.

        Returns:
            List of node names
        """
        return list(self._nodes.keys())

    def list_edges(self) -> list[tuple[str, str]]:
        """
        List all edges.

        Returns:
            List of (source, target) tuples
        """
        return [(e.source, e.target) for e in self._edges]

    async def execute(self, inputs: dict[str, Any], **metadata) -> GraphResult:
        """
        Execute the graph.

        Args:
            inputs: Input parameters
            **metadata: Additional metadata

        Returns:
            GraphResult
        """
        start_time = time.time()
        result = GraphResult()

        # Reset node status
        for node in self._nodes.values():
            node.status = NodeStatus.PENDING
            node.outputs = {}
            node.error = None

        # Execute start nodes
        try:
            await self._execute_nodes(self._start_nodes, inputs, result, metadata)

            # Execute remaining nodes in topological order
            executed = set(self._start_nodes)
            while len(executed) < len(self._nodes):
                next_nodes = self._get_next_nodes(executed)
                if not next_nodes:
                    break
                await self._execute_nodes(next_nodes, inputs, result, metadata)
                executed.update(next_nodes)

        except Exception as e:
            result.success = False
            result.error = str(e)

        result.total_duration = time.time() - start_time

        return result

    async def _execute_nodes(
        self,
        node_names: list[str],
        inputs: dict[str, Any],
        result: GraphResult,
        metadata: dict[str, Any],
    ) -> None:
        """Execute multiple nodes."""
        tasks = []
        for name in node_names:
            node = self._nodes.get(name)
            if node:
                tasks.append(self._execute_node(node, inputs, result, metadata))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_node(
        self,
        node: GraphNode,
        inputs: dict[str, Any],
        result: GraphResult,
        metadata: dict[str, Any],
    ) -> None:
        """Execute a single node."""
        # Check conditions
        for edge in self._edges:
            if edge.target == node.name and edge.condition:
                if not edge.condition(inputs):
                    node.status = NodeStatus.SKIPPED
                    result.node_results[node.name] = node.to_dict()
                    return

        # Execute node
        node.status = NodeStatus.RUNNING
        start_time = time.time()

        try:
            if asyncio.iscoroutinefunction(node.func):
                output = await node.func(**inputs, **metadata)
            else:
                output = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: node.func(**inputs, **metadata)
                )

            node.outputs = output if isinstance(output, dict) else {"result": output}
            node.status = NodeStatus.COMPLETED
            node.duration = time.time() - start_time

        except Exception as e:
            node.status = NodeStatus.FAILED
            node.error = str(e)
            node.duration = time.time() - start_time
            result.success = False

        result.node_results[node.name] = node.to_dict()

        # Update inputs for next nodes
        inputs.update(node.outputs)

    def _get_next_nodes(self, executed: set[str]) -> list[str]:
        """Get next nodes to execute."""
        next_nodes = []

        for edge in self._edges:
            if edge.source in executed and edge.target not in executed:
                # Check if all dependencies are executed
                deps = [e.source for e in self._edges if e.target == edge.target]
                if all(d in executed for d in deps):
                    next_nodes.append(edge.target)

        return next_nodes

    def get_execution_order(self) -> list[str]:
        """
        Get topological execution order.

        Returns:
            List of node names in execution order
        """
        order = []
        visited = set()

        def visit(node_name: str):
            if node_name in visited:
                return
            visited.add(node_name)

            # Visit dependencies first
            for edge in self._edges:
                if edge.target == node_name:
                    visit(edge.source)

            order.append(node_name)

        for node_name in self._nodes.keys():
            visit(node_name)

        return order

    def validate(self) -> bool:
        """
        Validate the graph.

        Returns:
            True if valid, False otherwise
        """
        # Check for cycles
        try:
            self.get_execution_order()
        except Exception:
            return False

        # Check for disconnected nodes
        if not self._start_nodes or not self._end_nodes:
            return False

        return True

    def clear(self) -> None:
        """Clear the graph."""
        self._nodes.clear()
        self._edges.clear()
        self._start_nodes.clear()
        self._end_nodes.clear()
