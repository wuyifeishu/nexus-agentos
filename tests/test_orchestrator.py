"""Tests for agentos.tools.orchestrator."""

from agentos.tools.orchestrator import (
    CheckpointData,
    ConditionNode,
    DAGBuilder,
    DAGResult,
    DAGSpec,
    NodeResult,
    NodeState,
    ParallelGroup,
    RetryPolicy,
    ToolNode,
    chain_builder,
    if_then_else,
    parallel_then_merge,
)


class TestNodeState:
    def test_values(self):
        assert NodeState.PENDING == "pending"
        assert NodeState.SUCCESS == "success"
        assert NodeState.FAILED == "failed"


class TestNodeResult:
    def test_defaults(self):
        r = NodeResult(node_id="n1", state=NodeState.PENDING)
        assert r.node_id == "n1"
        assert r.state == NodeState.PENDING
        assert r.duration_ms == 0.0
        assert r.retries == 0

    def test_success_result(self):
        r = NodeResult(node_id="n1", state=NodeState.SUCCESS, output=42, duration_ms=10.5)
        assert r.output == 42
        assert r.duration_ms == 10.5

    def test_error_result(self):
        r = NodeResult(node_id="n1", state=NodeState.FAILED, error="boom")
        assert r.error == "boom"


class TestDAGResult:
    def test_defaults(self):
        r = DAGResult(nodes={})
        assert r.success is False
        assert r.final_output is None
        assert r.total_duration_ms == 0.0

    def test_success(self):
        r = DAGResult(nodes={}, success=True, final_output="done", total_duration_ms=100)
        assert r.success is True
        assert r.final_output == "done"


class TestDAGSpec:
    def test_create(self):
        s = DAGSpec(name="test")
        assert s.name == "test"
        assert s.nodes == {}
        assert s.entry == []


class TestRetryPolicy:
    def test_defaults(self):
        rp = RetryPolicy()
        assert rp.max_retries == 3
        assert rp.base_delay == 1.0
        assert rp.max_delay == 30.0
        assert rp.backoff == "exponential"

    def test_custom(self):
        rp = RetryPolicy(max_retries=5, base_delay=2.0, backoff="fixed")
        assert rp.max_retries == 5
        assert rp.backoff == "fixed"


class TestToolNode:
    def test_create(self):
        n = ToolNode(tool_name="search", tool_args={"q": "hello"})
        assert n.tool_name == "search"
        assert n.tool_args == {"q": "hello"}
        assert n.depends_on == []
        assert n.timeout == 60.0

    def test_with_deps(self):
        n = ToolNode(tool_name="summarize", depends_on=["search", "fetch"])
        assert n.depends_on == ["search", "fetch"]


class TestConditionNode:
    def test_create(self):
        cond = lambda outputs: "a" if outputs.get("ok") else "b"
        n = ConditionNode(condition=cond, depends_on=["check"])
        assert n.condition({"ok": True}) == "a"
        assert n.condition({"ok": False}) == "b"
        assert n.depends_on == ["check"]


class TestParallelGroup:
    def test_create(self):
        pg = ParallelGroup(node_ids=["a", "b", "c"])
        assert pg.node_ids == ["a", "b", "c"]
        assert pg.max_concurrency == 5

    def test_with_deps(self):
        pg = ParallelGroup(node_ids=["a", "b"], depends_on=["seed"], max_concurrency=2)
        assert pg.max_concurrency == 2
        assert pg.depends_on == ["seed"]


class TestDAGBuilder:
    def test_build_empty(self):
        b = DAGBuilder("test")
        spec = b.build()
        assert spec.name == "test"

    def test_build_with_nodes(self):
        b = DAGBuilder("test")
        b.node("n1", tool_name="step1")
        b.node("n2", tool_name="step2", depends_on=["n1"])
        spec = b.build()
        assert "n1" in spec.nodes
        assert "n2" in spec.nodes

    def test_build_with_parallel(self):
        b = DAGBuilder("test")
        b.node("n1", tool_name="a")
        b.parallel(["b", "c"], depends_on=["n1"])
        spec = b.build()
        assert len(spec.parallels) >= 1

    def test_build_with_condition(self):
        b = DAGBuilder("test")
        b.condition("cond1", lambda o: "a", depends_on=["init"])
        spec = b.build()
        assert "cond1" in spec.conditions


class TestChainBuilder:
    def test_chain_builder(self):
        spec = chain_builder("my_chain", ["echo", "parse", "save"])
        assert spec.name == "my_chain"
        assert len(spec.nodes) == 3


class TestConditionalHelpers:
    def test_if_then_else(self):
        spec = if_then_else("flow", "check", "true_path", "false_path")
        assert spec.name == "flow"
        assert len(spec.nodes) >= 3


class TestParallelThenMerge:
    def test_basic(self):
        spec = parallel_then_merge("pipeline", ["fetch_a", "fetch_b"], "merge")
        assert spec.name == "pipeline"
        assert len(spec.parallels) >= 1


class TestCheckpointData:
    def test_create(self):
        cd = CheckpointData(
            dag_name="dag1",
            completed_nodes={"a": {"output": 1}},
            pending_nodes=["b", "c"],
            timestamp=1234.5,
        )
        assert cd.dag_name == "dag1"
        assert cd.completed_nodes == {"a": {"output": 1}}
        assert cd.pending_nodes == ["b", "c"]
        assert cd.timestamp == 1234.5

    def test_to_dict(self):
        cd = CheckpointData(dag_name="dag1", completed_nodes={}, pending_nodes=[])
        d = cd.to_dict()
        assert d["dag_name"] == "dag1"
        assert d["version"] == "1.0"

    def test_from_dict(self):
        cd = CheckpointData.from_dict({"dag_name": "d1", "completed_nodes": {}, "pending_nodes": []})
        assert cd.dag_name == "d1"

    def test_to_json_and_back(self):
        cd = CheckpointData(dag_name="dag1", completed_nodes={"n1": {"out": 42}}, pending_nodes=["n2"])
        json_str = cd.to_json()
        cd2 = CheckpointData.from_json(json_str)
        assert cd2.dag_name == "dag1"
        assert cd2.completed_nodes == {"n1": {"out": 42}}
