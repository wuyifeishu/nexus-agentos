"""
Tests for Task Decomposer 2.0 (v1.14.7).
"""

import pytest

from agentos.orchestration.task_decomposer import (
    DecompositionStrategy,
    TaskDAG,
    TaskDecomposer,
    TaskEdge,
    TaskNode,
    TaskNodeStatus,
)


class TestTaskDAG:

    def test_empty_dag(self):
        dag = TaskDAG(root_task="test")
        assert len(dag.nodes) == 0
        assert len(dag.edges) == 0

    def test_topological_order_linear(self):
        dag = TaskDAG(root_task="test")
        dag.nodes["A"] = TaskNode(id="A", description="A")
        dag.nodes["B"] = TaskNode(id="B", description="B")
        dag.nodes["C"] = TaskNode(id="C", description="C")
        dag.edges = [
            TaskEdge(from_node="A", to_node="B"),
            TaskEdge(from_node="B", to_node="C"),
        ]
        order = dag.topological_order()
        assert order == ["A", "B", "C"]

    def test_topological_order_parallel(self):
        dag = TaskDAG(root_task="test")
        dag.nodes["A"] = TaskNode(id="A", description="A")
        dag.nodes["B"] = TaskNode(id="B", description="B")
        dag.nodes["C"] = TaskNode(id="C", description="C")
        dag.nodes["D"] = TaskNode(id="D", description="D")
        dag.edges = [
            TaskEdge(from_node="A", to_node="B"),
            TaskEdge(from_node="A", to_node="C"),
            TaskEdge(from_node="B", to_node="D"),
            TaskEdge(from_node="C", to_node="D"),
        ]
        order = dag.topological_order()
        assert order[0] == "A"
        assert order[-1] == "D"
        assert set(order[1:3]) == {"B", "C"}

    def test_cycle_detection(self):
        dag = TaskDAG(root_task="test")
        dag.nodes["A"] = TaskNode(id="A", description="A")
        dag.nodes["B"] = TaskNode(id="B", description="B")
        dag.nodes["C"] = TaskNode(id="C", description="C")
        dag.edges = [
            TaskEdge(from_node="A", to_node="B"),
            TaskEdge(from_node="B", to_node="C"),
            TaskEdge(from_node="C", to_node="A"),  # creates cycle
        ]
        cycles = dag.detect_cycles()
        assert len(cycles) > 0
        assert "A" in cycles or "B" in cycles or "C" in cycles

        with pytest.raises(ValueError, match="Cycle detected"):
            dag.topological_order()

    def test_parallel_groups(self):
        dag = TaskDAG(root_task="test")
        dag.nodes["A"] = TaskNode(id="A", description="A")
        dag.nodes["B"] = TaskNode(id="B", description="B")
        dag.nodes["C"] = TaskNode(id="C", description="C")
        dag.edges = [
            TaskEdge(from_node="A", to_node="B"),
            TaskEdge(from_node="A", to_node="C"),
        ]
        groups = dag.parallel_groups()
        assert groups == [["A"], ["B", "C"]]

    def test_no_cycle_detection_on_valid_dag(self):
        dag = TaskDAG(root_task="test")
        dag.nodes["A"] = TaskNode(id="A", description="A")
        dag.nodes["B"] = TaskNode(id="B", description="B")
        dag.edges = [TaskEdge(from_node="A", to_node="B")]
        cycles = dag.detect_cycles()
        assert len(cycles) == 0


class TestTaskDecomposer:

    def test_decompose_simple_task(self):
        decomposer = TaskDecomposer()
        dag = decomposer.decompose("Extract anomalies from log files and generate a report")
        assert dag is not None
        assert len(dag.nodes) > 0
        # Should have decomposed into multiple nodes
        assert len(dag.nodes) >= 2

    def test_decompose_compare_task(self):
        decomposer = TaskDecomposer()
        dag = decomposer.decompose("compare agentos vs langgraph on task planning")
        assert dag is not None
        assert len(dag.nodes) > 0

    def test_decompose_transform_task(self):
        decomposer = TaskDecomposer()
        dag = decomposer.decompose("migrate database from postgres to mysql")
        assert dag is not None
        assert len(dag.nodes) >= 2

    def test_decompose_atomic_task_no_split(self):
        """Very simple task should not be deeply decomposed."""
        decomposer = TaskDecomposer()
        dag = decomposer.decompose("say hello")
        assert dag is not None

    def test_decompose_with_context(self):
        decomposer = TaskDecomposer()
        dag = decomposer.decompose("analyze data", context={"tools": ["pandas", "matplotlib"]})
        assert dag.metadata == {"tools": ["pandas", "matplotlib"]}

    def test_validate_valid_dag(self):
        decomposer = TaskDecomposer()
        dag = decomposer.decompose("extract data and create chart")
        valid, msg = decomposer.validate_dag(dag)
        assert valid, f"DAG should be valid, got: {msg}"

    def test_replan_on_failure(self):
        decomposer = TaskDecomposer()
        dag = decomposer.decompose("extract data, analyze, generate report")
        original_count = len(dag.nodes)

        # Mark a middle node as failed
        nodes = list(dag.nodes.keys())
        if len(nodes) > 1:
            dag.nodes[nodes[1]].status = TaskNodeStatus.FAILED
            dag.nodes[nodes[1]].error = "connection timeout"

            new_dag = decomposer.replan(dag, [nodes[1]])
            assert new_dag is not None
            # Should have a replan trace
            traces = decomposer.get_trace()
            assert len(traces) > 0
            assert any(t.action == "replan" for t in traces)

    def test_trace_output(self):
        decomposer = TaskDecomposer()
        decomposer.decompose("collect data, process, output results")
        traces = decomposer.get_trace()
        assert len(traces) > 0
        for t in traces:
            assert t.action in ("split", "merge", "refine", "replan")
            assert t.iteration >= 1

    def test_create_decomposer_factory(self):
        from agentos.orchestration.task_decomposer import create_decomposer
        d = create_decomposer(strategy=DecompositionStrategy.TOP_DOWN)
        assert d._strategy == DecompositionStrategy.TOP_DOWN


class TestDecompositionStrategies:

    def test_all_strategies(self):
        for strategy in DecompositionStrategy:
            decomposer = TaskDecomposer(strategy=strategy)
            dag = decomposer.decompose("complex multi-step task")
            assert dag is not None
            assert dag.strategy == strategy
