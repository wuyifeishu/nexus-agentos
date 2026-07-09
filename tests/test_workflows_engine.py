"""Tests for agentos.workflows.engine module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentos.workflows.engine import (
    BUILTIN_WORKFLOWS,
    CODE_REVIEW,
    DEBATE,
    QA,
    RESEARCH,
    Workflow,
    WorkflowEngine,
    WorkflowStep,
    WorkflowType,
)


class TestWorkflowType:
    def test_all_values(self):
        assert WorkflowType.CODE_REVIEW == "code_review"
        assert WorkflowType.RESEARCH == "research"
        assert WorkflowType.DEBATE == "debate"
        assert WorkflowType.QA == "qa"
        assert WorkflowType.CUSTOM == "custom"

    def test_count(self):
        assert len(WorkflowType) == 5


class TestWorkflowStep:
    def test_minimal(self):
        s = WorkflowStep("coder", "write code")
        assert s.agent_role == "coder"
        assert s.instruction == "write code"
        assert s.input_from is None
        assert s.parallel is False

    def test_full(self):
        s = WorkflowStep("reviewer", "review", input_from=0, parallel=True)
        assert s.input_from == 0
        assert s.parallel is True


class TestWorkflow:
    def test_minimal(self):
        w = Workflow(name="test", workflow_type=WorkflowType.CUSTOM, steps=[])
        assert w.name == "test"
        assert w.workflow_type == WorkflowType.CUSTOM
        assert w.steps == []
        assert w.max_rounds == 5
        assert w.auto_merge is True
        assert w.metadata == {}

    def test_custom_max_rounds(self):
        w = Workflow(name="x", workflow_type=WorkflowType.CUSTOM, steps=[], max_rounds=10)
        assert w.max_rounds == 10

    def test_with_metadata(self):
        w = Workflow(
            name="x", workflow_type=WorkflowType.CUSTOM, steps=[], metadata={"owner": "alice"}
        )
        assert w.metadata == {"owner": "alice"}


class TestBuiltinWorkflows:
    def test_code_review(self):
        assert CODE_REVIEW.workflow_type == WorkflowType.CODE_REVIEW
        assert len(CODE_REVIEW.steps) == 4
        assert CODE_REVIEW.max_rounds == 1

    def test_research(self):
        assert RESEARCH.workflow_type == WorkflowType.RESEARCH
        assert len(RESEARCH.steps) == 3

    def test_debate(self):
        assert DEBATE.workflow_type == WorkflowType.DEBATE
        assert DEBATE.max_rounds == 3

    def test_qa(self):
        assert QA.workflow_type == WorkflowType.QA
        assert QA.max_rounds == 2

    def test_builtin_workflows_map(self):
        assert BUILTIN_WORKFLOWS[WorkflowType.CODE_REVIEW] is CODE_REVIEW
        assert BUILTIN_WORKFLOWS[WorkflowType.RESEARCH] is RESEARCH
        assert BUILTIN_WORKFLOWS[WorkflowType.DEBATE] is DEBATE
        assert BUILTIN_WORKFLOWS[WorkflowType.QA] is QA
        assert len(BUILTIN_WORKFLOWS) == 4

    def test_steps_have_input_from_chain(self):
        # Research: steps 1 and 2 reference previous steps
        assert RESEARCH.steps[0].input_from is None
        assert RESEARCH.steps[1].input_from == 0
        assert RESEARCH.steps[2].input_from == 1


@pytest.mark.asyncio
class TestWorkflowEngine:
    @pytest.fixture
    def mock_factory(self):
        def _factory(role):
            agent = MagicMock()
            agent.run = AsyncMock(
                return_value={"output": f"result_from_{role}"}
            )
            return agent
        return _factory

    async def test_single_step_workflow(self):
        w = Workflow(
            name="echo",
            workflow_type=WorkflowType.CUSTOM,
            steps=[WorkflowStep("echoer", "repeat")],
            max_rounds=1,
        )

        def factory(role):
            m = MagicMock()
            m.run = AsyncMock(return_value={"output": "ECHO"})
            return m

        engine = WorkflowEngine(w, factory)
        result = await engine.execute("hello")
        assert result == "ECHO"

    async def test_two_step_chain(self):
        w = Workflow(
            name="pipe",
            workflow_type=WorkflowType.CUSTOM,
            steps=[
                WorkflowStep("step1", "first"),
                WorkflowStep("step2", "second", input_from=0),
            ],
            max_rounds=1,
        )

        def factory(role):
            m = MagicMock()
            m.run = AsyncMock(return_value={"output": f"{role}_output"})
            return m

        engine = WorkflowEngine(w, factory)
        result = await engine.execute("start")
        assert result == "step2_output"

    async def test_auto_merge_single_round(self):
        w = Workflow(
            name="auto",
            workflow_type=WorkflowType.CUSTOM,
            steps=[
                WorkflowStep("a", "task"),
                WorkflowStep("b", "task"),
            ],
            max_rounds=3,
            auto_merge=True,
        )

        def factory(role):
            m = MagicMock()
            m.run = AsyncMock(return_value={"output": f"out_{role}"})
            return m

        engine = WorkflowEngine(w, factory)
        result = await engine.execute("input")
        assert result == "out_b"

    async def test_no_auto_merge_multi_round(self):
        w = Workflow(
            name="multi",
            workflow_type=WorkflowType.CUSTOM,
            steps=[
                WorkflowStep("writer", "write"),
            ],
            max_rounds=3,
            auto_merge=False,
        )

        call_count = 0

        def factory(role):
            nonlocal call_count
            m = MagicMock()
            async def _run(prompt, context=None):
                nonlocal call_count
                call_count += 1
                return {"output": f"v{call_count}"}
            m.run = _run
            return m

        engine = WorkflowEngine(w, factory)
        result = await engine.execute("input")
        assert result.startswith("v")
        assert call_count == 3

    async def test_context_passed_to_agent(self):
        w = Workflow(
            name="ctx",
            workflow_type=WorkflowType.CUSTOM,
            steps=[WorkflowStep("ctx_checker", "check")],
            max_rounds=1,
        )

        ctx_capture = {}

        def factory(role):
            m = MagicMock()
            async def _run(prompt, context=None):
                ctx_capture["context"] = context
                return {"output": "ok"}
            m.run = _run
            return m

        engine = WorkflowEngine(w, factory)
        await engine.execute("test", context={"user": "bob"})
        assert ctx_capture["context"] == {"user": "bob"}

    async def test_code_review_workflow_real(self):
        w = CODE_REVIEW
        results = []

        def factory(role):
            m = MagicMock()
            async def _run(prompt, context=None):
                results.append(role)
                return {"output": f"review_{role}"}
            m.run = _run
            return m

        engine = WorkflowEngine(w, factory)
        result = await engine.execute("def foo(): pass")
        assert len(results) == 4
        assert "architect" in results
        assert "security_expert" in results
        assert "performance_expert" in results
        assert "reviewer" in results

    async def test_research_workflow_real(self):
        w = RESEARCH
        results = []

        def factory(role):
            m = MagicMock()
            async def _run(prompt, context=None):
                results.append(role)
                return {"output": f"out_{role}"}
            m.run = _run
            return m

        engine = WorkflowEngine(w, factory)
        result = await engine.execute("AI trends")
        assert len(results) == 3
        assert results == ["researcher", "analyst", "synthesizer"]

    async def test_result_fallback_to_string(self):
        """When result dict has no 'output' key, falls back to str(result)."""
        w = Workflow(
            name="nokey",
            workflow_type=WorkflowType.CUSTOM,
            steps=[WorkflowStep("s", "task")],
            max_rounds=1,
        )

        def factory(role):
            m = MagicMock()
            m.run = AsyncMock(return_value={"not_output": 42})
            return m

        engine = WorkflowEngine(w, factory)
        result = await engine.execute("input")
        assert "not_output" in result
