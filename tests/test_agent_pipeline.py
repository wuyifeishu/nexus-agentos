"""Tests for agentos.agent.pipeline — ConditionalPipeline / ParallelPipeline / RouterAgent."""

from unittest.mock import MagicMock

import pytest

from agentos.agent.pipeline import (
    ConditionalPipeline,
    ParallelPipeline,
    PipelineAgent,
    PipelineResult,
    RouterAgent,
    StepResult,
)

# ── helpers ──────────────────────────────────────────────────────────


def _make_agent(answer: str, success: bool = True, tokens: int = 10, cost: float = 0.01, duration: float = 100.0, error: str | None = None):
    """Build a mock ToolAgent that returns a controlled AgentResult."""
    from agentos.agent.tool_agent import AgentResult

    agent = MagicMock()
    agent.run.return_value = AgentResult(
        success=success,
        final_answer=answer,
        steps=[],
        total_steps=1,
        total_tokens=tokens,
        total_cost_usd=cost,
        total_duration_ms=duration,
        error=error,
    )
    return agent


# ── dataclass tests ───────────────────────────────────────────────


class TestPipelineAgent:
    def test_default_config_none(self):
        fake = MagicMock()
        pa = PipelineAgent(name="test", agent=fake)
        assert pa.name == "test"
        assert pa.agent is fake
        assert pa.config is None

    def test_with_config(self):
        from agentos.agent.tool_agent import AgentConfig

        cfg = AgentConfig(max_steps=3)
        fake = MagicMock()
        pa = PipelineAgent(name="cfg_test", agent=fake, config=cfg)
        assert pa.config is cfg
        assert pa.config.max_steps == 3


class TestPipelineResult:
    def test_output_property(self):
        pr = PipelineResult(final_output="hello")
        assert pr.output == "hello"
        assert pr.final_output == "hello"

    def test_defaults(self):
        pr = PipelineResult()
        assert pr.success is True
        assert pr.steps == []
        assert pr.final_output == ""
        assert pr.total_tokens == 0
        assert pr.total_cost_usd == 0.0
        assert pr.total_duration_ms == 0.0
        assert pr.error == ""


class TestStepResult:
    def test_creation(self):
        from agentos.agent.tool_agent import AgentResult

        ar = AgentResult(final_answer="done")
        sr = StepResult(agent_name="a1", result=ar, output_key="k1")
        assert sr.agent_name == "a1"
        assert sr.result is ar
        assert sr.output_key == "k1"

    def test_output_key_default_none(self):
        from agentos.agent.tool_agent import AgentResult

        sr = StepResult(agent_name="x", result=AgentResult())
        assert sr.output_key is None


# ── ConditionalPipeline ──────────────────────────────────────────


class TestConditionalPipeline:
    def test_single_agent_no_router(self):
        cp = ConditionalPipeline()
        cp.add("a1", _make_agent("result"))
        r = cp.run("task")
        assert r.success is True
        assert r.final_output == "result"
        assert r.steps[0]["agent"] == "a1"
        assert r.steps[0]["output"] == "result"
        assert r.steps[0]["tokens"] == 10

    def test_unknown_start_agent(self):
        cp = ConditionalPipeline()
        cp.add("a", _make_agent("ok"))
        r = cp.run("task", start_agent="nonexistent")
        assert r.success is False
        assert "nonexistent" in r.error

    def test_auto_start_agent_when_not_specified(self):
        cp = ConditionalPipeline()
        cp.add("first", _make_agent("auto"))
        r = cp.run("task")
        assert r.success is True
        assert r.steps[0]["agent"] == "first"

    def test_router_next_agent(self):
        cp = ConditionalPipeline()
        cp.add("classifier", _make_agent("legal"))
        cp.add("legal", _make_agent("合同分析完成"))

        def route(output):
            if "legal" in output:
                return "legal"
            return "__END__"

        r = cp.run("task", router=route)
        assert r.success is True
        assert len(r.steps) == 2
        assert r.steps[0]["agent"] == "classifier"
        assert r.steps[1]["agent"] == "legal"
        assert r.final_output == "合同分析完成"
        assert r.total_tokens == 20

    def test_router_end(self):
        cp = ConditionalPipeline()
        cp.add("a", _make_agent("done"))

        def route(output):
            return "__END__"

        r = cp.run("task", router=route)
        assert r.success is True
        assert len(r.steps) == 1

    def test_router_unknown_next_breaks(self):
        cp = ConditionalPipeline()
        cp.add("a", _make_agent("something"))

        def route(output):
            return "b"  # not registered

        r = cp.run("task", router=route)
        assert r.success is True
        assert len(r.steps) == 1

    def test_agent_failure_stops_pipeline(self):
        cp = ConditionalPipeline()
        cp.add("a", _make_agent("fail", success=False, error="boom"))

        def route(output):
            return "b"

        r = cp.run("task", router=route)
        assert r.success is False
        assert r.error == "boom"
        assert len(r.steps) == 1

    def test_max_hops_limit(self):
        cp = ConditionalPipeline(max_hops=3)
        cp.add("loop", _make_agent("again"))

        def route(output):
            return "loop"

        r = cp.run("task", router=route)
        assert r.success is True
        assert len(r.steps) == 3


# ── ParallelPipeline ──────────────────────────────────────────────


class TestParallelPipeline:
    def test_no_agents(self):
        pp = ParallelPipeline()
        r = pp.run("task")
        assert r.success is False
        assert "No agents" in r.error

    def test_single_agent(self):
        pp = ParallelPipeline()
        pp.add("a", _make_agent("single"))
        r = pp.run("task")
        assert r.success is True
        assert r.final_output == "## a\nsingle"

    def test_multiple_agents(self):
        pp = ParallelPipeline()
        pp.add("a", _make_agent("A output"))
        pp.add("b", _make_agent("B output"))
        pp.add("c", _make_agent("C output"))
        r = pp.run("task")
        assert r.success is True
        assert "A output" in r.final_output
        assert "B output" in r.final_output
        assert "C output" in r.final_output
        # total_duration_ms should be max of individual durations
        assert r.total_duration_ms == 100.0
        assert r.total_tokens == 30
        assert r.total_cost_usd == pytest.approx(0.03)

    def test_with_aggregator(self):
        pp = ParallelPipeline()
        pp.add("a", _make_agent("A"))
        pp.add("b", _make_agent("B"))

        def agg(outputs):
            return " | ".join(outputs.values())

        r = pp.run("task", aggregator=agg)
        assert r.final_output == "A | B"

    def test_partial_errors_but_results_exist(self):
        pp = ParallelPipeline()

        # One agent throws in the thread
        crash = MagicMock()
        crash.run.side_effect = RuntimeError("thread crash")

        pp.add("ok", _make_agent("good"))
        pp.add("bad", crash)
        r = pp.run("task")
        # success is False because errors exist
        assert r.success is False
        assert "thread crash" in r.error
        assert "good" in r.final_output

    def test_all_agents_error(self):
        pp = ParallelPipeline()
        crash1 = MagicMock()
        crash1.run.side_effect = RuntimeError("e1")
        crash2 = MagicMock()
        crash2.run.side_effect = RuntimeError("e2")
        pp.add("a", crash1)
        pp.add("b", crash2)
        r = pp.run("task")
        assert r.success is False
        assert "e1" in r.error or "e2" in r.error


# ── RouterAgent ───────────────────────────────────────────────────


class TestRouterAgent:
    def test_no_routes(self):
        ra = RouterAgent(_make_agent("x"))
        r = ra.run("task")
        assert r.success is False
        assert "No routes" in r.error

    def test_classify_exact_match(self):
        classifier = _make_agent("code")
        ra = RouterAgent(classifier)
        ra.register("code", _make_agent("code result"), "code tasks")
        ra.register("writing", _make_agent("writing result"), "writing tasks")
        r = ra.run("write a function")
        assert r.success is True
        assert r.final_output == "code result"
        assert r.steps[0]["output"] == "Classified as: code"

    def test_classify_substring_match(self):
        classifier = _make_agent("  CODE  ")  # whitespace + mixed case
        ra = RouterAgent(classifier)
        ra.register("code", _make_agent("code result"))
        ra.register("writing", _make_agent("writing result"))
        r = ra.run("task")
        assert r.final_output == "code result"
        assert r.steps[0]["output"] == "Classified as: code"

    def test_classify_no_match_falls_back_to_first(self):
        classifier = _make_agent("unknown_route")
        ra = RouterAgent(classifier)
        ra.register("first", _make_agent("first result"))
        ra.register("second", _make_agent("second result"))
        r = ra.run("task")
        assert r.final_output == "first result"
        assert r.steps[0]["output"] == "Classified as: first"

    def test_agent_failure_propagates(self):
        classifier = _make_agent("target")
        ra = RouterAgent(classifier)
        ra.register("target", _make_agent("fail", success=False, error="agent error"))
        r = ra.run("task")
        assert r.success is False
