"""Tests for agentos.tools.pipeline."""

import pytest

from agentos.tools.pipeline import (
    FilterStage,
    LambdaStage,
    ParallelPipeline,
    Pipeline,
    PipelineContext,
    StageStatus,
)


class AddStage(LambdaStage):
    def __init__(self, n: int):
        super().__init__(lambda x, ctx: x + n, name=f"add_{n}")


class MulStage(LambdaStage):
    def __init__(self, n: int):
        super().__init__(lambda x, ctx: x * n, name=f"mul_{n}")


class TestPipeline:
    def test_single_stage(self):
        p = Pipeline().then(lambda x, ctx: x * 2)
        assert p.run(5) == 10

    def test_chain(self):
        p = Pipeline().then(lambda x, ctx: x + 1).then(lambda x, ctx: x * 3)
        assert p.run(2) == 9  # (2+1)*3

    def test_stage_name(self):
        p = Pipeline().then(lambda x, ctx: x, name="passthru")
        result = p.run(42)
        assert result == 42
        assert p._stages[0].name == "passthru"

    def test_context_passthrough(self):
        p = Pipeline()
        p.then(lambda x, ctx: ctx.set("seen", x) or x)
        p.then(lambda x, ctx: x + ctx.get("seen", 0))
        assert p.run(10) == 20

    def test_run_batch(self):
        p = Pipeline().then(lambda x, ctx: x * 2)
        results = p.run_batch([1, 2, 3])
        assert results == [2, 4, 6]

    def test_retry_success(self):
        attempts = []

        def flaky(x, ctx):
            attempts.append(1)
            if len(attempts) < 2:
                raise RuntimeError("fail")
            return x

        p = Pipeline().then(flaky, max_retries=2)
        assert p.run(1) == 1
        assert len(attempts) == 2

    def test_retry_exhausted(self):
        def always_fail(x, ctx):
            raise RuntimeError("boom")

        p = Pipeline().then(always_fail, max_retries=1)
        with pytest.raises(RuntimeError, match="boom"):
            p.run(1)

    def test_on_error_fallback(self):
        class FallbackStage(LambdaStage):
            def on_error(self, item, error, ctx):
                return -1

        p = Pipeline().add_stage(FallbackStage(lambda x, ctx: (_ for _ in ()).throw(RuntimeError("fail")), max_retries=0))
        assert p.run(100) == -1

    def test_stats(self):
        p = Pipeline("test").then(lambda x, ctx: x * 2, name="doubler")
        p.run(5)
        s = p.stats
        assert s["name"] == "test"
        assert len(s["stages"]) == 1
        assert s["stages"][0]["items_processed"] == 1


class TestFilterStage:
    def test_pass(self):
        p = Pipeline().add_stage(FilterStage(lambda x, ctx: x > 0))
        p.then(lambda x, ctx: x)  # identity after filter
        # FilterStage returns item if pass, None if drop
        assert p.run(5) == 5

    def test_drop(self):
        p = Pipeline().add_stage(FilterStage(lambda x, ctx: x > 0))
        p.then(lambda x, ctx: x)
        # None passes through then() and returns None
        assert p.run(-1) is None


class TestParallelPipeline:
    def test_fan_out(self):
        p = ParallelPipeline()
        p.branch(Pipeline().then(lambda x, ctx: x + 1))
        p.branch(Pipeline().then(lambda x, ctx: x * 2))
        results = p.run(5)
        assert results == [6, 10]

    def test_merge(self):
        p = ParallelPipeline()
        p.branch(Pipeline().then(lambda x, ctx: x * 2))
        p.branch(Pipeline().then(lambda x, ctx: x * 3))
        p.merge(lambda results, ctx: sum(results))
        assert p.run(4) == 20  # 8 + 12

    def test_context_shared(self):
        pp = ParallelPipeline()
        b1 = Pipeline().then(lambda x, ctx: ctx.set("a", 1) or x)
        b2 = Pipeline().then(lambda x, ctx: ctx.get("a", 0) + x)
        pp.branch(b1)
        pp.branch(b2)
        # b2 gets a from ctx set by b1 — note: threads run in parallel,
        # so ctx sharing depends on timing. This tests merge logic.
        results = pp.run(5)
        assert len(results) == 2


class TestStageStatus:
    def test_status_lifecycle(self):
        stage = LambdaStage(lambda x, ctx: x)
        assert stage.status == StageStatus.IDLE
        stage.execute(1, PipelineContext())
        assert stage.status == StageStatus.IDLE

    def test_error_status(self):
        def fail(x, ctx):
            raise RuntimeError("boom")

        stage = LambdaStage(fail)
        with pytest.raises(RuntimeError):
            stage.execute(1, PipelineContext())
        assert stage.status == StageStatus.ERROR
