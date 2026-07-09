"""Tests for agentos.orchestration.graph_executor — Agent DAG execution engine."""

import pytest

from agentos.orchestration.graph_executor import (
    AgentGraph,
    GraphNode,
    GraphNodeState,
    GraphRecipe,
    GraphResult,
)

# ── GraphNode ─────────────────────────────────────────────────────────

class TestGraphNode:
    def test_defaults(self):
        n = GraphNode(name="test", agent_type="echo", task_template="say: {input}")
        assert n.name == "test"
        assert n.agent_type == "echo"
        assert n.depends_on == []
        assert n.timeout_seconds == 120.0
        assert n.retry_count == 0
        assert n.on_failure == "abort"
        assert n.state == GraphNodeState.PENDING
        assert n.output is None
        assert n.error is None
        assert n.latency_ms == 0.0

    def test_resolve_task_input(self):
        n = GraphNode(name="n", agent_type="t", task_template="process: {input}")
        result = n.resolve_task({"__input__": "hello"})
        assert result == "process: hello"

    def test_resolve_task_node_output(self):
        n = GraphNode(name="n", agent_type="t", task_template="use: {research.output}")
        result = n.resolve_task({"research": "result-42", "__input__": ""})
        assert result == "use: result-42"

    def test_resolve_task_no_placeholders(self):
        n = GraphNode(name="n", agent_type="t", task_template="static task")
        result = n.resolve_task({})
        assert result == "static task"

    def test_resolve_task_mixed(self):
        n = GraphNode(name="n", agent_type="t",
                      task_template="{input} -> {step1.output} -> {step2.output}")
        outputs = {"__input__": "start", "step1": "mid", "step2": "end"}
        result = n.resolve_task(outputs)
        assert result == "start -> mid -> end"

    def test_resolve_task_missing_node(self):
        n = GraphNode(name="n", agent_type="t", task_template="{missing.output}")
        result = n.resolve_task({"__input__": ""})
        assert result == "{missing.output}"


# ── GraphResult ───────────────────────────────────────────────────────

class TestGraphResult:
    def test_defaults(self):
        r = GraphResult()
        assert r.node_results == {}
        assert r.execution_order == []
        assert r.total_latency_ms == 0.0
        assert r.success is True
        assert r.error is None


# ── AgentGraph ────────────────────────────────────────────────────────

class TestAgentGraph:
    def test_add_node(self):
        g = AgentGraph()
        n = GraphNode(name="n", agent_type="t", task_template="task")
        g.add_node(n)
        assert g.node_count == 1

    def test_add_duplicate_node(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="n", agent_type="t", task_template="t1"))
        with pytest.raises(ValueError, match="Duplicate"):
            g.add_node(GraphNode(name="n", agent_type="t", task_template="t2"))

    def test_remove_node(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t"))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="t",
                             depends_on=["a"]))
        g.remove_node("a")
        assert g.node_count == 1
        assert g._nodes["b"].depends_on == []

    def test_remove_node_missing(self):
        g = AgentGraph()
        with pytest.raises(KeyError):
            g.remove_node("nope")

    def test_node_count_edge_count(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t"))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="t",
                             depends_on=["a"]))
        assert g.node_count == 2
        assert g.edge_count == 1

    def test_validate_valid(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t"))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="t",
                             depends_on=["a"]))
        assert g.validate() == []

    def test_validate_missing_dep(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t",
                             depends_on=["ghost"]))
        errors = g.validate()
        assert len(errors) == 1
        assert "ghost" in errors[0]

    def test_validate_self_dep(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t",
                             depends_on=["a"]))
        errors = g.validate()
        assert len(errors) >= 1

    def test_validate_cycle(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t",
                             depends_on=["b"]))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="t",
                             depends_on=["a"]))
        errors = g.validate()
        assert any("Cycle" in e for e in errors)

    def test_topological_order_linear(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="c", agent_type="t", task_template="t",
                             depends_on=["b"]))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="t",
                             depends_on=["a"]))
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t"))
        order = g._topological_order()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_topological_order_diamond(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t"))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="t",
                             depends_on=["a"]))
        g.add_node(GraphNode(name="c", agent_type="t", task_template="t",
                             depends_on=["a"]))
        g.add_node(GraphNode(name="d", agent_type="t", task_template="t",
                             depends_on=["b", "c"]))
        order = g._topological_order()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_topological_order_cycle_raises(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t",
                             depends_on=["b"]))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="t",
                             depends_on=["a"]))
        with pytest.raises(ValueError, match="Cycle"):
            g._topological_order()

    def test_execute_with_executor(self):
        def executor(agent_type, task):
            return f"[{agent_type}] {task}"

        g = AgentGraph(executor=executor)
        g.add_node(GraphNode(name="a", agent_type="echo", task_template="hello from a"))
        g.add_node(GraphNode(name="b", agent_type="wrap", task_template="{a.output}",
                             depends_on=["a"]))
        r = g.execute("start")
        assert r.success is True
        assert r.node_results["a"].output == "[echo] hello from a"
        assert r.node_results["b"].output == "[wrap] [echo] hello from a"

    def test_execute_dep_fails_skip(self):
        def executor(agent_type, task):
            if "fail" in task.lower():
                raise RuntimeError("bang")
            return task

        g = AgentGraph(executor=executor)
        g.add_node(GraphNode(name="a", agent_type="t",
                             task_template="this will fail"))
        g.add_node(GraphNode(name="b", agent_type="t",
                             task_template="use {a.output}", depends_on=["a"]))
        r = g.execute("input")
        assert r.success is False
        assert r.node_results["a"].state == GraphNodeState.FAILED
        assert r.node_results["b"].state == GraphNodeState.SKIPPED

    def test_execute_abort_on_failure(self):
        def executor(agent_type, task):
            if "bad" in task:
                raise RuntimeError("error")
            return "ok"

        g = AgentGraph(executor=executor)
        g.add_node(GraphNode(name="a", agent_type="t", task_template="bad task",
                             on_failure="abort"))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="after"))
        r = g.execute("input")
        assert r.node_results["a"].state == GraphNodeState.FAILED
        assert r.node_results["b"].state == GraphNodeState.SKIPPED

    def test_execute_validation_error(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t",
                             depends_on=["ghost"]))
        r = g.execute("input")
        assert r.success is False
        assert "ghost" in r.error

    def test_execute_cycle_handled(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="t",
                             depends_on=["b"]))
        g.add_node(GraphNode(name="b", agent_type="t", task_template="t",
                             depends_on=["a"]))
        r = g.execute("input")
        assert r.success is False
        assert "Cycle" in r.error

    def test_to_mermaid(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="research", agent_type="researcher",
                             task_template="Research: {input}"))
        g.add_node(GraphNode(name="summarize", agent_type="summarizer",
                             task_template="Summarize: {research.output}",
                             depends_on=["research"]))
        md = g.to_mermaid()
        assert "graph TD" in md
        assert "research" in md
        assert "summarize" in md
        assert "-->" in md

    def test_execute_no_executor_raises(self):
        g = AgentGraph()
        g.add_node(GraphNode(name="a", agent_type="t", task_template="task"))
        with pytest.raises(NotImplementedError):
            g._execute_node("t", "task")


# ── GraphRecipe ───────────────────────────────────────────────────────

class TestGraphRecipe:
    def test_defaults(self):
        r = GraphRecipe(name="test")
        assert r.name == "test"
        assert r.description == ""
        assert r.nodes == []

    def test_from_dict(self):
        data = {
            "name": "my-graph",
            "description": "A test graph",
            "nodes": [
                {"name": "a", "agent_type": "echo", "task_template": "task a"},
                {"name": "b", "agent_type": "echo", "task_template": "{a.output}",
                 "depends_on": ["a"]},
            ],
        }
        r = GraphRecipe.from_dict(data)
        assert r.name == "my-graph"
        assert r.description == "A test graph"
        assert len(r.nodes) == 2

    def test_build(self):
        def executor(agent_type, task):
            return task.upper()

        recipe = GraphRecipe(
            name="pipe",
            nodes=[
                {"name": "a", "agent_type": "echo", "task_template": "hello"},
                {"name": "b", "agent_type": "wrap",
                 "task_template": "{a.output}", "depends_on": ["a"]},
            ],
        )
        graph = recipe.build(executor=executor)
        assert graph.node_count == 2
        r = graph.execute("start")
        assert r.success is True
