"""Tests for agentos.orchestration.graph — DAG workflow orchestrator."""

import pytest

from agentos.orchestration.graph import (
    GraphEdge,
    GraphNode,
    GraphOrchestrator,
    GraphResult,
    NodeStatus,
)

# ── GraphNode ────────────────────────────────────────────────────────

class TestGraphNode:
    def test_defaults(self):
        n = GraphNode(name="test", func=lambda: 1)
        assert n.name == "test"
        assert n.status == NodeStatus.PENDING
        assert n.duration == 0.0
        assert n.error is None
        assert n.inputs == {}
        assert n.outputs == {}
        assert n.metadata == {}

    def test_to_dict(self):
        n = GraphNode(id="abc", name="n1", func=lambda: 1, duration=1.5,
                      status=NodeStatus.COMPLETED, inputs={"x": 1},
                      outputs={"y": 2}, metadata={"k": "v"})
        d = n.to_dict()
        assert d["id"] == "abc"
        assert d["name"] == "n1"
        assert d["status"] == "completed"
        assert d["duration"] == 1.5
        assert d["inputs"] == {"x": 1}
        assert d["outputs"] == {"y": 2}
        assert d["metadata"] == {"k": "v"}

    def test_unique_id(self):
        n1 = GraphNode(name="a")
        n2 = GraphNode(name="b")
        assert n1.id != n2.id
        assert len(n1.id) == 12


# ── GraphEdge ─────────────────────────────────────────────────────────

class TestGraphEdge:
    def test_basic(self):
        e = GraphEdge(source="a", target="b")
        assert e.source == "a"
        assert e.target == "b"
        assert e.condition is None
        assert e.metadata == {}

    def test_with_condition(self):
        cond = lambda d: d.get("go", True)
        e = GraphEdge(source="a", target="b", condition=cond)
        assert e.condition({"go": True}) is True
        assert e.condition({"go": False}) is False

    def test_to_dict(self):
        e = GraphEdge(source="a", target="b")
        d = e.to_dict()
        assert d == {"source": "a", "target": "b", "metadata": {}}


# ── GraphResult ───────────────────────────────────────────────────────

class TestGraphResult:
    def test_defaults(self):
        r = GraphResult()
        assert r.success is True
        assert r.error is None
        assert r.total_duration == 0.0
        assert r.node_results == {}

    def test_to_dict(self):
        r = GraphResult(id="g1", total_duration=2.5, success=False,
                        error="bad", node_results={"a": {"status": "failed"}})
        d = r.to_dict()
        assert d["id"] == "g1"
        assert d["total_duration"] == 2.5
        assert d["success"] is False
        assert d["error"] == "bad"
        assert d["node_results"] == {"a": {"status": "failed"}}


# ── GraphOrchestrator ────────────────────────────────────────────────

class TestGraphOrchestrator:
    def test_add_node(self):
        g = GraphOrchestrator()
        n = g.add_node("step1", lambda x: x + 1)
        assert isinstance(n, GraphNode)
        assert n.name == "step1"
        assert g.get_node("step1") is n

    def test_add_node_first_is_start(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        assert g._start_nodes == ["a"]

    def test_get_node_missing(self):
        g = GraphOrchestrator()
        assert g.get_node("nope") is None

    def test_list_nodes(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        assert set(g.list_nodes()) == {"a", "b"}

    def test_list_edges(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        g.add_edge("a", "b")
        assert g.list_edges() == [("a", "b")]

    def test_add_edge_source_missing(self):
        g = GraphOrchestrator()
        g.add_node("b", lambda: 2)
        with pytest.raises(ValueError, match="Source node not found"):
            g.add_edge("a", "b")

    def test_add_edge_target_missing(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        with pytest.raises(ValueError, match="Target node not found"):
            g.add_edge("a", "b")

    def test_remove_node(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        assert g.remove_node("a") is True
        assert g.get_node("a") is None
        assert g.list_nodes() == ["b"]

    def test_remove_node_missing(self):
        g = GraphOrchestrator()
        assert g.remove_node("nope") is False

    def test_remove_node_cleans_edges(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        g.add_edge("a", "b")
        g.remove_node("a")
        assert g.list_edges() == []

    def test_remove_edge(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        g.add_edge("a", "b")
        assert g.remove_edge("a", "b") is True
        assert g.list_edges() == []

    def test_remove_edge_missing(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        assert g.remove_edge("a", "b") is False

    def test_clear(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        g.add_edge("a", "b")
        g.clear()
        assert g.list_nodes() == []
        assert g.list_edges() == []
        assert g._start_nodes == []
        assert g._end_nodes == []

    @pytest.mark.asyncio
    async def test_simple_linear(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda **kw: {"step": "a", "val": 1})
        g.add_node("b", lambda **kw: {"step": "b", "val": kw.get("val", 0) + 1})
        g.add_node("c", lambda **kw: {"step": "c", "val": kw.get("val", 0) + 1})
        g.add_edge("a", "b")
        g.add_edge("b", "c")

        r = await g.execute({})
        assert r.success is True
        assert r.node_results["c"]["outputs"]["val"] == 3

    @pytest.mark.asyncio
    async def test_parallel_branches(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda **kw: {"x": 1})
        g.add_node("b", lambda **kw: {"y": kw.get("x", 0) + 10})
        g.add_node("c", lambda **kw: {"z": kw.get("x", 0) + 20})
        g.add_edge("a", "b")
        g.add_edge("a", "c")

        r = await g.execute({})
        assert r.success is True
        assert r.node_results["b"]["outputs"]["y"] == 11
        assert r.node_results["c"]["outputs"]["z"] == 21

    @pytest.mark.asyncio
    async def test_node_failure(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda **kw: (_ for _ in ()).throw(Exception("boom")))
        g.add_node("b", lambda **kw: {"ok": True})
        g.add_edge("a", "b")

        r = await g.execute({})
        assert r.success is False
        assert r.node_results["a"]["status"] == "failed"
        assert "boom" in r.node_results["a"]["error"]

    @pytest.mark.asyncio
    async def test_condition_skip(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda **kw: {"go": False})
        g.add_node("b", lambda **kw: {"ran": True})
        g.add_edge("a", "b", condition=lambda d: d.get("go", True))

        r = await g.execute({})
        assert r.success is True
        r_node = r.node_results.get("b")
        if r_node:
            assert r_node["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_condition_pass(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda **kw: {"go": True})
        g.add_node("b", lambda **kw: {"ran": True})
        g.add_edge("a", "b", condition=lambda d: d.get("go", True))

        r = await g.execute({})
        assert r.success is True
        assert r.node_results["b"]["status"] == "completed"

    def test_get_execution_order_linear(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        g.add_node("c", lambda: 3)
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        assert g.get_execution_order() == ["a", "b", "c"]

    def test_get_execution_order_diamond(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        g.add_node("c", lambda: 3)
        g.add_node("d", lambda: 4)
        g.add_edge("a", "b")
        g.add_edge("a", "c")
        g.add_edge("b", "d")
        g.add_edge("c", "d")
        order = g.get_execution_order()
        assert order[0] in ("a",)  # a first
        assert order[-1] == "d"     # d last
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_validate_valid(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda: 1)
        g.add_node("b", lambda: 2)
        g.add_edge("a", "b")
        assert g.validate() is True

    def test_validate_no_nodes(self):
        g = GraphOrchestrator()
        assert g.validate() is False

    @pytest.mark.asyncio
    async def test_async_node(self):
        async def async_node(**kw):
            return {"async": True}

        g = GraphOrchestrator()
        g.add_node("a", async_node)
        r = await g.execute({})
        assert r.success is True
        assert r.node_results["a"]["outputs"]["async"] is True

    @pytest.mark.asyncio
    async def test_non_dict_output(self):
        g = GraphOrchestrator()
        g.add_node("a", lambda **kw: 42)
        r = await g.execute({})
        out = r.node_results["a"]["outputs"]
        assert out == {"result": 42}

    def test_add_node_metadata(self):
        g = GraphOrchestrator()
        n = g.add_node("step", lambda: 1, timeout=30, priority="high")
        assert n.metadata == {"timeout": 30, "priority": "high"}
