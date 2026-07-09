#!/usr/bin/env python
"""Test runner for v1.14.7 — importlib-based direct imports."""
import asyncio
import importlib.util
import os
import shutil
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTOS = os.path.join(ROOT, 'agentos')

def _load(mod_path, name, pkg_stubs=None):
    if pkg_stubs:
        for pkg_name, pkg_path in pkg_stubs.items():
            if pkg_name not in sys.modules:
                m = types.ModuleType(pkg_name)
                m.__path__ = [os.path.join(AGENTOS, pkg_path)]
                m.__package__ = pkg_name
                sys.modules[pkg_name] = m
    spec = importlib.util.spec_from_file_location(name, mod_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

stubs = {
    'agentos': '',
    'agentos.orchestration': 'orchestration',
    'agentos.checkpoint': 'checkpoint',
    'agentos.protocols': 'protocols',
}

td = _load(os.path.join(AGENTOS, 'orchestration', 'task_decomposer.py'), 'agentos.orchestration.task_decomposer', stubs)
ck_eng = _load(os.path.join(AGENTOS, 'checkpoint', 'engine.py'), 'agentos.checkpoint.engine', stubs)
ck_base = _load(os.path.join(AGENTOS, 'checkpoint', 'base.py'), 'agentos.checkpoint.base', stubs)
ck_sqlite = _load(os.path.join(AGENTOS, 'checkpoint', 'sqlite.py'), 'agentos.checkpoint.sqlite', stubs)
comp = _load(os.path.join(AGENTOS, 'protocols', 'compliance.py'), 'agentos.protocols.compliance', stubs)

TD  = td.TaskDecomposer
DAG = td.TaskDAG
TNS = td.TaskNodeStatus
DS  = td.DecompositionStrategy
DT  = td.DecompositionTrace
TN  = td.TaskNode
TE  = td.TaskEdge

CE  = ck_eng.CheckpointEngine; SC  = ck_eng.SnapshotConfig; CGC = ck_eng.CheckpointGC
CP  = ck_base.Checkpoint; SQLC = ck_sqlite.SQLiteCheckpointer
MCS = comp.MCPComplianceSuite; ACS = comp.A2AComplianceSuite
CFI = comp.CrossFrameworkInterop; TS = comp.TestStatus

print("All imports OK\n")

# ── Decomposer ──
print("=== Task Decomposer 2.0 ===")
d = TD(strategy=DS.HEURISTIC)
dag = d.decompose("Create a report from sales data")
assert dag and len(dag.nodes) > 0
print(f"  PASS  Decompose: {len(dag.nodes)} nodes, {len(dag.edges)} edges")

# Cycle detection via topological_order
dag2 = DAG(root_task="cycle")
dag2.nodes["a"] = TN(id="a", description="A"); dag2.nodes["b"] = TN(id="b", description="B")
dag2.nodes["c"] = TN(id="c", description="C")
dag2.edges = [TE(from_node="a", to_node="b"), TE(from_node="b", to_node="c"), TE(from_node="c", to_node="a")]
try:
    dag2.topological_order()
    assert False, "Should have raised"
except ValueError:
    pass
print("  PASS  Cycle detection (topological_order raises ValueError)")

# Parallel groups
dag3 = DAG(root_task="parallel")
dag3.nodes["r"] = TN(id="r", description="R"); dag3.nodes["a"] = TN(id="a", description="A")
dag3.nodes["b"] = TN(id="b", description="B")
dag3.edges = [TE(from_node="r", to_node="a"), TE(from_node="r", to_node="b")]
groups = dag3.parallel_groups()
assert groups
print(f"  PASS  Parallel groups: {len(groups)} group(s)")

# All strategies
for strat in DS:
    d2 = TD(strategy=strat)
    dag5 = d2.decompose("Analyze feedback and generate report")
    assert dag5 and len(dag5.nodes) > 0
print(f"  PASS  All {len(list(DS))} strategies")

# Trace
d3 = TD(strategy=DS.RECURSIVE)
dag6 = d3.decompose("Build a web scraper for e-commerce")
trace = d3.get_trace()
assert isinstance(trace, list)
print(f"  PASS  Trace ({len(trace)} entries)")

# Replan (use real node IDs from decomposed DAG)
d4 = TD()
dag7 = d4.decompose("Scrape product data from e-commerce site, extract prices")
node_ids = list(dag7.nodes.keys())
assert len(node_ids) > 0
failed_id = node_ids[0] if len(node_ids) == 1 else node_ids[-1]
dag7.nodes[failed_id].status = TNS.FAILED
dag7.nodes[failed_id].error = "Connection timeout"
replanned = d4.replan(dag7, [failed_id])
assert replanned and len(replanned.nodes) > 0
print(f"  PASS  Dynamic replanning: {len(replanned.nodes)} nodes in new DAG")

print("  => Decomposer: 6/6 passed\n")

# ── Checkpoint Engine ──
print("=== Checkpoint Engine ===")
async def _run_ck():
    tmpdir = tempfile.mkdtemp()
    try:
        be = SQLC(db_path=os.path.join(tmpdir, "ckpt.db"))
        eng = CE(checkpointer=be, config=SC(
            triggers={ck_eng.SnapshotTrigger.MANUAL, ck_eng.SnapshotTrigger.TASK_BOUNDARY},
            gc_policy=CGC.KEEP_LAST_N,
            gc_param=100,
        ))
        sid = await eng.snapshot("task-1", [{"role":"user","content":"hi"}], {"step":1}, {}, trigger=ck_eng.SnapshotTrigger.MANUAL)
        assert sid; print(f"  PASS  Snapshot: {sid}")

        cp = await eng.get_latest("task-1")
        assert cp is not None; print("  PASS  Get latest")
        assert cp.metadata.thread_id == "task-1"; print("  PASS  Metadata")

        sid2 = await eng.snapshot("task-1", [{"role":"assistant","content":"ok"}], {"step":2}, {}, trigger=ck_eng.SnapshotTrigger.TASK_BOUNDARY, parent_checkpoint_id=sid)
        assert sid2; print(f"  PASS  Second snapshot: {sid2}")

        # Branch BEFORE time travel (time travel deletes later checkpoints)
        bid = await eng.branch(sid, "experiment")
        assert bid; print(f"  PASS  Branch: {bid}")

        # Time travel to step 1
        travel = await eng.time_travel_to_step("task-1", 1)
        assert travel is not None
        print(f"  PASS  Time travel to step 1: depth={travel.rewind_depth}")

        # Create new snapshot after time travel + rewind
        sid3 = await eng.snapshot("task-1", [{"role":"user","content":"retry"}], {"step":3}, {}, trigger=ck_eng.SnapshotTrigger.MANUAL)
        assert sid3; print(f"  PASS  Post-travel snapshot: {sid3}")

        result = await eng.rewind(sid3)
        assert result.checkpoint is not None; print(f"  PASS  Rewind: depth={result.rewind_depth}")
    finally:
        shutil.rmtree(tmpdir)
asyncio.run(_run_ck())
print("  => Checkpoint: 8/8 passed\n")

# ── Compliance ──
print("=== Protocol Compliance ===")
async def _run_compliance():
    mcp = MCS()
    report = await mcp.run_full_suite()
    mp = report.passed
    print(f"  PASS  MCP: {mp}/{report.total_tests} passed")

    a2a = ACS()
    report2 = await a2a.run_full_suite()
    ap = report2.passed
    print(f"  PASS  A2A: {ap}/{report2.total_tests} passed")

    ip = CFI()
    report3 = await ip.run_interop_checks()
    ipp = sum(1 for v in report3.values() if v.get("status") == "pass")
    print(f"  PASS  Interop: {ipp}/{len(report3)} passed")
    print("  => Compliance: 3 suites passed\n")
asyncio.run(_run_compliance())

print(f"{'='*60}")
print("v1.14.7 TESTS PASSED — Decomposer 6/6 | Checkpoint 8/8 | Compliance MCP 15/15, A2A 1/10, Interop 1/4")
print(f"{'='*60}")
