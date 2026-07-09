"""
Tests for Fine-grained Checkpoint Engine (v1.14.7).
"""


import pytest

from agentos.checkpoint.engine import (
    CheckpointEngine,
    CheckpointGC,
    SnapshotConfig,
    SnapshotTrigger,
    TimeTravelResult,
)
from agentos.checkpoint.sqlite import SQLiteCheckpointer


@pytest.fixture
def temp_db(tmp_path):
    db_path = str(tmp_path / "test_checkpoints.db")
    return db_path


@pytest.fixture
async def engine(temp_db):
    checkpointer = SQLiteCheckpointer(db_path=temp_db)
    engine = CheckpointEngine(checkpointer)
    yield engine
    # cleanup
    import os
    if os.path.exists(temp_db):
        os.remove(temp_db)


class TestCheckpointEngine:

    @pytest.mark.asyncio
    async def test_snapshot_single(self, engine):
        cid = await engine.snapshot(
            thread_id="test-thread",
            messages=[{"role": "user", "content": "hello"}],
            state={"step": 1},
            tools_result={},
        )
        assert cid.startswith("ckpt-test-thread-1-")

    @pytest.mark.asyncio
    async def test_snapshot_increments_step(self, engine):
        cid1 = await engine.snapshot("t1", [{"role": "user", "content": "a"}], {"s": 1}, {})
        cid2 = await engine.snapshot("t1", [{"role": "user", "content": "b"}], {"s": 2}, {})
        assert "-1-" in cid1
        assert "-2-" in cid2

    @pytest.mark.asyncio
    async def test_get_latest(self, engine):
        await engine.snapshot("t2", [{"role": "user", "content": "a"}], {"s": 1}, {})
        await engine.snapshot("t2", [{"role": "user", "content": "b"}], {"s": 2}, {})
        latest = await engine.get_latest("t2")
        assert latest is not None
        assert latest.state["s"] == 2

    @pytest.mark.asyncio
    async def test_snapshot_safe_no_exception(self, engine):
        """Safe snapshot should never throw."""
        cid = await engine.snapshot_safe("t3", [], {"s": 1}, {})
        assert isinstance(cid, str)

    @pytest.mark.asyncio
    async def test_trigger_filter_respected(self, engine):
        config = SnapshotConfig(triggers={SnapshotTrigger.TOOL_CALL})
        engine._config = config

        # Should trigger
        cid1 = await engine.snapshot(
            "t4", [{"role": "tool", "content": "call"}], {"s": 1}, {},
            trigger=SnapshotTrigger.TOOL_CALL,
        )
        assert cid1 != ""

        # Should NOT trigger
        cid2 = await engine.snapshot(
            "t5", [{"role": "user", "content": "hi"}], {"s": 1}, {},
            trigger=SnapshotTrigger.LLM_CALL,
        )
        assert cid2 == ""

    @pytest.mark.asyncio
    async def test_snapshot_not_in_trigger_set(self, engine):
        # Only TOOL_CALL in trigger set
        engine._config = SnapshotConfig(triggers={SnapshotTrigger.TOOL_CALL})
        cid = await engine.snapshot(
            "t6", [], {}, {},
            trigger=SnapshotTrigger.LLM_CALL,
        )
        assert cid == ""


class TestTimeTravel:

    @pytest.mark.asyncio
    async def test_rewind(self, engine):
        await engine.snapshot("tt1", [{"role": "user", "content": "step1"}], {"s": 1}, {})
        cid2 = await engine.snapshot("tt1", [{"role": "user", "content": "step2"}], {"s": 2}, {})
        await engine.snapshot("tt1", [{"role": "user", "content": "step3"}], {"s": 3}, {})

        result = await engine.rewind(cid2)
        assert isinstance(result, TimeTravelResult)
        assert result.thread_id == "tt1"
        assert result.rewind_depth == 1
        assert result.checkpoint.state["s"] == 2

    @pytest.mark.asyncio
    async def test_time_travel_to_step(self, engine):
        await engine.snapshot("tt2", [{"role": "user", "content": "a"}], {"s": 1}, {})
        await engine.snapshot("tt2", [{"role": "user", "content": "b"}], {"s": 2}, {})
        await engine.snapshot("tt2", [{"role": "user", "content": "c"}], {"s": 3}, {})

        result = await engine.time_travel_to_step("tt2", 1)
        assert result is not None
        assert result.checkpoint.state["s"] == 1

    @pytest.mark.asyncio
    async def test_list_time_travel_points(self, engine):
        await engine.snapshot("tt3", [], {"s": 1}, {})
        await engine.snapshot("tt3", [], {"s": 2}, {})

        points = await engine.list_time_travel_points("tt3")
        assert len(points) == 2

    @pytest.mark.asyncio
    async def test_rewind_nonexistent(self, engine):
        with pytest.raises(ValueError, match="not found"):
            await engine.rewind("nonexistent-ckpt")


class TestBranching:

    @pytest.mark.asyncio
    async def test_branch(self, engine):
        cid = await engine.snapshot("main", [{"role": "user", "content": "start"}], {"x": 0}, {})
        branch_id = await engine.branch(cid, "experiment")
        assert "branch-experiment" in branch_id

    @pytest.mark.asyncio
    async def test_branch_starts_from_source_state(self, engine):
        cid = await engine.snapshot("main2", [{"role": "user", "content": "init"}], {"x": 42}, {})
        branch_id = await engine.branch(cid, "test-branch")

        latest = await engine.get_latest(branch_id)
        assert latest is not None
        assert latest.state["x"] == 42

    @pytest.mark.asyncio
    async def test_merge_branch(self, engine):
        cid = await engine.snapshot("main3", [{"role": "user", "content": "init"}], {"x": 0}, {})
        branch_id = await engine.branch(cid, "feature")
        # Add work on branch
        await engine.snapshot(branch_id, [{"role": "user", "content": "work"}], {"x": 100}, {})

        merge_id = await engine.merge_branch(branch_id, "main3")
        assert merge_id is not None

    @pytest.mark.asyncio
    async def test_branch_nonexistent_source(self, engine):
        with pytest.raises(ValueError, match="not found"):
            await engine.branch("nonexistent", "fail")


class TestCheckpointTree:

    @pytest.mark.asyncio
    async def test_tree_structure(self, engine):
        cid1 = await engine.snapshot("tree1", [], {"s": 1}, {})
        cid2 = await engine.snapshot("tree1", [], {"s": 2}, {}, parent_checkpoint_id=cid1)
        cid3 = await engine.snapshot("tree1", [], {"s": 3}, {}, parent_checkpoint_id=cid2)

        tree = await engine.get_checkpoint_tree("tree1")
        assert tree["total_checkpoints"] == 3
        assert len(tree["nodes"]) == 3
        assert len(tree["edges"]) == 2


class TestGarbageCollection:

    @pytest.mark.asyncio
    async def test_keep_last_n(self, engine, temp_db):
        engine._config = SnapshotConfig(gc_policy=CheckpointGC.KEEP_LAST_N, gc_param=3)

        for i in range(10):
            await engine.snapshot("gc1", [], {"s": i}, {})

        checkpoints = await engine._checkpointer.list_checkpoints("gc1")
        assert len(checkpoints) <= 3

    @pytest.mark.asyncio
    async def test_keep_all(self, engine, temp_db):
        engine._config = SnapshotConfig(gc_policy=CheckpointGC.KEEP_ALL)

        for i in range(5):
            await engine.snapshot("gc2", [], {"s": i}, {})

        checkpoints = await engine._checkpointer.list_checkpoints("gc2")
        assert len(checkpoints) == 5
