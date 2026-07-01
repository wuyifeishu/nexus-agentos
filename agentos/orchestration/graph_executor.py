"""
Agent Graph — DAG-based multi-agent execution engine.

Build complex agent pipelines as directed acyclic graphs where each node
is an agent invocation and edges define data flow dependencies.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class GraphNodeState(Enum):
    """Execution state of a graph orchestrator node."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class GraphNode:
    """A single node in the agent execution graph."""

    name: str
    agent_type: str
    task_template: str
    """Template string with {input} or {node_name.output} placeholders."""

    depends_on: list[str] = field(default_factory=list)
    """Node names this node depends on."""

    timeout_seconds: float = 120.0
    retry_count: int = 0
    on_failure: str = "abort"
    """Action on failure: 'abort', 'skip', 'continue'."""

    state: GraphNodeState = GraphNodeState.PENDING
    output: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0

    def resolve_task(self, node_outputs: dict[str, Any]) -> str:
        """Resolve template placeholders using outputs from completed nodes."""
        task = self.task_template
        task = task.replace("{input}", str(node_outputs.get("__input__", "")))
        for name, output in node_outputs.items():
            placeholder = f"{{{name}.output}}"
            if placeholder in task:
                task = task.replace(placeholder, str(output))
        return task


@dataclass
class GraphResult:
    """Result of graph execution."""

    node_results: dict[str, GraphNode] = field(default_factory=dict)
    execution_order: list[str] = field(default_factory=list)
    total_latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None


class AgentGraph:
    """
    DAG-based multi-agent execution engine.

    Define execution graphs declaratively, resolve dependencies automatically,
    execute nodes in topological order with parallelism for independent nodes.

    Example::

        graph = AgentGraph()
        graph.add_node(GraphNode(
            name="research",
            agent_type="researcher",
            task_template="Research: {input}"
        ))
        graph.add_node(GraphNode(
            name="summarize",
            agent_type="summarizer",
            task_template="Summarize: {research.output}",
            depends_on=["research"]
        ))
        result = graph.execute("quantum computing advances")
    """

    def __init__(self, executor: Optional[Callable[[str, str], Any]] = None):
        """
        Args:
            executor: Callable(agent_type, task) -> output. If not provided,
                      subclasses must override _execute_node.
        """
        self._nodes: dict[str, GraphNode] = {}
        self._executor = executor

    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph. Raises ValueError on duplicate name."""
        if node.name in self._nodes:
            raise ValueError(f"Duplicate node name: {node.name}")
        self._nodes[node.name] = node

    def remove_node(self, name: str) -> None:
        """Remove a node and all edges referencing it."""
        if name not in self._nodes:
            raise KeyError(f"Node not found: {name}")
        del self._nodes[name]
        for node in self._nodes.values():
            node.depends_on = [d for d in node.depends_on if d != name]

    def validate(self) -> list[str]:
        """
        Validate graph integrity.

        Returns:
            List of error messages (empty if valid).
        """
        errors: list[str] = []

        for name, node in self._nodes.items():
            for dep in node.depends_on:
                if dep not in self._nodes:
                    errors.append(f"Node '{name}' depends on unknown node '{dep}'")
                if dep == name:
                    errors.append(f"Node '{name}' cannot depend on itself")

        # Check for cycles using topological sort
        if not errors:
            try:
                self._topological_order()
            except ValueError as e:
                errors.append(str(e))

        return errors

    def _topological_order(self) -> list[str]:
        """Return nodes in topological order. Raises ValueError on cycle."""
        in_degree: dict[str, int] = {name: 0 for name in self._nodes}
        adjacency: dict[str, list[str]] = {name: [] for name in self._nodes}

        for name, node in self._nodes.items():
            for dep in node.depends_on:
                adjacency[dep].append(name)
                in_degree[name] += 1

        queue = deque([name for name, deg in in_degree.items() if deg == 0])
        order: list[str] = []

        while queue:
            current = queue.popleft()
            order.append(current)
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self._nodes):
            remaining = set(self._nodes) - set(order)
            raise ValueError(f"Cycle detected involving nodes: {remaining}")

        return order

    def execute(self, input_data: str) -> GraphResult:
        """
        Execute the graph with given input.

        Args:
            input_data: Initial task input, accessible as {input} in templates.

        Returns:
            GraphResult with per-node outputs and execution metadata.
        """
        errors = self.validate()
        if errors:
            return GraphResult(success=False, error="; ".join(errors))

        t0 = time.perf_counter()
        node_outputs: dict[str, Any] = {"__input__": input_data}
        results: dict[str, GraphNode] = {}
        order: list[str] = []

        # Reset all nodes
        for node in self._nodes.values():
            node.state = GraphNodeState.PENDING
            node.output = None
            node.error = None
            node.latency_ms = 0.0

        try:
            topo = self._topological_order()
        except ValueError as e:
            return GraphResult(success=False, error=str(e))

        abort = False
        for name in topo:
            if abort:
                self._nodes[name].state = GraphNodeState.SKIPPED
                results[name] = self._nodes[name]
                continue

            node = self._nodes[name]
            results[name] = node
            order.append(name)

            # Check dependencies
            deps_failed = False
            for dep in node.depends_on:
                if results[dep].state == GraphNodeState.FAILED:
                    deps_failed = True
                    break

            if deps_failed:
                node.state = GraphNodeState.SKIPPED
                continue

            task = node.resolve_task(node_outputs)
            node_t0 = time.perf_counter()

            try:
                node.state = GraphNodeState.RUNNING
                output = self._execute_node(node.agent_type, task)
                node.output = output
                node.state = GraphNodeState.COMPLETED
                node_outputs[name] = output
            except Exception as exc:
                node.state = GraphNodeState.FAILED
                node.error = f"{type(exc).__name__}: {exc}"
                node_outputs[name] = None
                if node.on_failure == "abort":
                    abort = True

            node.latency_ms = (time.perf_counter() - node_t0) * 1000

        success = all(
            n.state in (GraphNodeState.COMPLETED, GraphNodeState.SKIPPED)
            for n in results.values()
        )
        total_latency = (time.perf_counter() - t0) * 1000

        return GraphResult(
            node_results=results,
            execution_order=order,
            total_latency_ms=total_latency,
            success=success,
        )

    def _execute_node(self, agent_type: str, task: str) -> Any:
        """Execute a single node. Override or provide executor callback."""
        if self._executor:
            return self._executor(agent_type, task)
        raise NotImplementedError(
            "No executor provided. Pass executor to __init__ or override _execute_node."
        )

    def to_mermaid(self) -> str:
        """Export graph as Mermaid flowchart."""
        lines = ["graph TD"]
        for name, node in self._nodes.items():
            safe = name.replace("-", "_").replace(" ", "_")
            lines.append(f"    {safe}[\"{name}\\n({node.agent_type})\"]")
        for name, node in self._nodes.items():
            safe = name.replace("-", "_").replace(" ", "_")
            for dep in node.depends_on:
                safe_dep = dep.replace("-", "_").replace(" ", "_")
                lines.append(f"    {safe_dep} --> {safe}")
        return "\n".join(lines)

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(n.depends_on) for n in self._nodes.values())


@dataclass
class GraphRecipe:
    """Declarative graph definition (YAML-friendly)."""

    name: str
    description: str = ""
    nodes: list[dict[str, Any]] = field(default_factory=list)
    """List of node dicts with keys: name, agent_type, task_template, depends_on, timeout_seconds, on_failure."""

    @classmethod
    def from_dict(cls, data: dict) -> "GraphRecipe":
        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            nodes=data.get("nodes", []),
        )

    def build(self, executor: Optional[Callable] = None) -> AgentGraph:
        """Build an AgentGraph from this recipe."""
        graph = AgentGraph(executor=executor)
        for spec in self.nodes:
            graph.add_node(GraphNode(
                name=spec["name"],
                agent_type=spec.get("agent_type", "default"),
                task_template=spec["task_template"],
                depends_on=spec.get("depends_on", []),
                timeout_seconds=spec.get("timeout_seconds", 120.0),
                retry_count=spec.get("retry_count", 0),
                on_failure=spec.get("on_failure", "abort"),
            ))
        return graph
