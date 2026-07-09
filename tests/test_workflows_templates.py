"""Tests for agentos.workflows.templates module."""

import json

import yaml

from agentos.workflows.templates import (
    BUILTIN_TEMPLATES,
    RetryPolicy,
    StepType,
    WorkflowStep,
    WorkflowTemplate,
)


class TestStepType:
    def test_all_values(self):
        assert StepType.AGENT.value == "agent"
        assert StepType.TOOL.value == "tool"
        assert StepType.CONDITION.value == "condition"
        assert StepType.PARALLEL.value == "parallel"
        assert StepType.HUMAN_REVIEW.value == "human_review"
        assert StepType.TRANSFORM.value == "transform"
        assert StepType.WAIT.value == "wait"

    def test_count(self):
        assert len(StepType) == 7


class TestRetryPolicy:
    def test_values(self):
        assert RetryPolicy.NONE.value == "none"
        assert RetryPolicy.LINEAR.value == "linear"
        assert RetryPolicy.EXPONENTIAL.value == "exponential"


class TestWorkflowStep:
    def test_minimal(self):
        s = WorkflowStep(name="step1")
        assert s.name == "step1"
        assert s.step_type == StepType.AGENT
        assert s.agent_type == "default"
        assert s.max_retries == 3
        assert s.retry_policy == RetryPolicy.NONE

    def test_full_agent_step(self):
        s = WorkflowStep(
            name="research",
            step_type=StepType.AGENT,
            agent_type="researcher",
            task_template="Research {{topic}}",
            output_key="result",
            depends_on=["prior"],
            retry_policy=RetryPolicy.EXPONENTIAL,
            max_retries=5,
        )
        assert s.agent_type == "researcher"
        assert s.output_key == "result"
        assert s.depends_on == ["prior"]
        assert s.retry_policy == RetryPolicy.EXPONENTIAL
        assert s.max_retries == 5

    def test_condition_step(self):
        s = WorkflowStep(
            name="check",
            step_type=StepType.CONDITION,
            condition="result > 0.8",
            then_steps=[WorkflowStep(name="good")],
            else_steps=[WorkflowStep(name="bad")],
        )
        assert s.condition == "result > 0.8"
        assert len(s.then_steps) == 1
        assert len(s.else_steps) == 1

    def test_parallel_step(self):
        s = WorkflowStep(
            name="parallel_tasks",
            step_type=StepType.PARALLEL,
            sub_steps=[WorkflowStep(name="a"), WorkflowStep(name="b")],
            max_concurrency=2,
        )
        assert len(s.sub_steps) == 2
        assert s.max_concurrency == 2

    def test_human_review_step(self):
        s = WorkflowStep(
            name="approval",
            step_type=StepType.HUMAN_REVIEW,
            review_prompt="Approve?",
            timeout_minutes=15,
        )
        assert s.review_prompt == "Approve?"
        assert s.timeout_minutes == 15

    def test_transform_step(self):
        s = WorkflowStep(
            name="transform",
            step_type=StepType.TRANSFORM,
            transform_expr="x.upper()",
        )
        assert s.transform_expr == "x.upper()"


class TestWorkflowTemplateBasic:
    def test_minimal(self):
        t = WorkflowTemplate(name="wf")
        assert t.name == "wf"
        assert t.description == ""
        assert t.version == "1.0"
        assert t.steps == []
        assert t.metadata == {}

    def test_with_steps_and_metadata(self):
        t = WorkflowTemplate(
            name="wf",
            description="test",
            version="2.0",
            steps=[WorkflowStep(name="s1")],
            metadata={"author": "alice"},
        )
        assert t.description == "test"
        assert t.version == "2.0"
        assert len(t.steps) == 1
        assert t.metadata == {"author": "alice"}


class TestWorkflowTemplateSerialization:
    def test_to_dict_roundtrip(self):
        t = WorkflowTemplate(
            name="test_wf",
            description="A test workflow",
            steps=[
                WorkflowStep(name="step1", agent_type="coder", output_key="code"),
                WorkflowStep(
                    name="step2",
                    step_type=StepType.CONDITION,
                    condition="code != ''",
                    then_steps=[WorkflowStep(name="ok")],
                ),
            ],
        )
        d = t.to_dict()
        assert d["name"] == "test_wf"
        assert len(d["steps"]) == 2

        t2 = WorkflowTemplate.from_dict(d)
        assert t2.name == t.name
        assert len(t2.steps) == 2
        assert t2.steps[0].output_key == "code"

    def test_to_dict_omits_defaults(self):
        t = WorkflowTemplate(name="wf", steps=[WorkflowStep(name="s1")])
        d = t.to_dict()
        s = d["steps"][0]
        assert "agent_type" not in s
        assert "retry_policy" not in s

    def test_to_dict_includes_retry(self):
        t = WorkflowTemplate(
            name="wf",
            steps=[WorkflowStep(name="s1", retry_policy=RetryPolicy.LINEAR, max_retries=2)],
        )
        d = t.to_dict()
        s = d["steps"][0]
        assert s["retry_policy"] == "linear"
        assert s["max_retries"] == 2

    def test_to_json(self):
        t = WorkflowTemplate(name="wf", steps=[WorkflowStep(name="s1")])
        j = t.to_json()
        assert "wf" in j
        d = json.loads(j)
        assert d["name"] == "wf"

    def test_from_json(self):
        j = '{"name": "wf", "steps": [{"name": "s1"}]}'
        t = WorkflowTemplate.from_json(j)
        assert t.name == "wf"
        assert len(t.steps) == 1

    def test_to_yaml(self):
        t = WorkflowTemplate(name="wf", steps=[WorkflowStep(name="s1")])
        y = t.to_yaml()
        assert "wf" in y
        d = yaml.safe_load(y)
        assert d["name"] == "wf"

    def test_from_yaml(self):
        y = "name: wf\nsteps:\n  - name: s1"
        t = WorkflowTemplate.from_yaml(y)
        assert t.name == "wf"
        assert t.steps[0].name == "s1"

    def test_nested_steps_roundtrip(self):
        inner = WorkflowStep(name="inner")
        outer = WorkflowStep(
            name="outer",
            step_type=StepType.CONDITION,
            condition="true",
            then_steps=[inner],
        )
        t = WorkflowTemplate(name="nested", steps=[outer])
        d = t.to_dict()
        t2 = WorkflowTemplate.from_dict(d)
        assert len(t2.steps[0].then_steps) == 1
        assert t2.steps[0].then_steps[0].name == "inner"

    def test_else_steps_roundtrip(self):
        """else_steps serialized in _step_to_dict."""
        t = WorkflowTemplate(
            name="cond_wf",
            steps=[
                WorkflowStep(
                    name="check",
                    step_type=StepType.CONDITION,
                    condition="x > 0",
                    then_steps=[WorkflowStep(name="then_step")],
                    else_steps=[WorkflowStep(name="else_step")],
                )
            ],
        )
        d = t.to_dict()
        t2 = WorkflowTemplate.from_dict(d)
        assert len(t2.steps[0].else_steps) == 1
        assert t2.steps[0].else_steps[0].name == "else_step"

    def test_sub_steps_roundtrip(self):
        t = WorkflowTemplate(
            name="parallel",
            steps=[
                WorkflowStep(
                    name="p",
                    step_type=StepType.PARALLEL,
                    sub_steps=[WorkflowStep(name="a"), WorkflowStep(name="b")],
                    max_concurrency=3,
                )
            ],
        )
        d = t.to_dict()
        t2 = WorkflowTemplate.from_dict(d)
        assert len(t2.steps[0].sub_steps) == 2
        assert t2.steps[0].max_concurrency == 3


class TestWorkflowTemplateNavigation:
    def test_get_step_root(self):
        t = WorkflowTemplate(
            name="wf",
            steps=[WorkflowStep(name="s1"), WorkflowStep(name="s2")],
        )
        assert t.get_step("s1") is not None
        assert t.get_step("s2") is not None
        assert t.get_step("s3") is None

    def test_get_step_nested(self):
        t = WorkflowTemplate(
            name="wf",
            steps=[
                WorkflowStep(
                    name="parent",
                    then_steps=[WorkflowStep(name="child")],
                )
            ],
        )
        assert t.get_step("child") is not None

    def test_get_step_deep_nested(self):
        t = WorkflowTemplate(
            name="wf",
            steps=[
                WorkflowStep(
                    name="a",
                    then_steps=[
                        WorkflowStep(
                            name="b",
                            then_steps=[WorkflowStep(name="c")],
                        )
                    ],
                )
            ],
        )
        assert t.get_step("c") is not None

    def test_get_step_in_sub_steps(self):
        t = WorkflowTemplate(
            name="wf",
            steps=[
                WorkflowStep(
                    name="p",
                    step_type=StepType.PARALLEL,
                    sub_steps=[WorkflowStep(name="inner")],
                )
            ],
        )
        assert t.get_step("inner") is not None

    def test_flatten_steps(self):
        t = WorkflowTemplate(
            name="wf",
            steps=[
                WorkflowStep(name="a"),
                WorkflowStep(
                    name="b",
                    then_steps=[WorkflowStep(name="c")],
                    else_steps=[WorkflowStep(name="d")],
                ),
            ],
        )
        flat = t.flatten_steps()
        names = [s.name for s in flat]
        assert names == ["a", "b", "c", "d"]

    def test_step_count(self):
        t = WorkflowTemplate(
            name="wf",
            steps=[
                WorkflowStep(name="a"),
                WorkflowStep(name="b", then_steps=[WorkflowStep(name="c")]),
            ],
        )
        assert t.step_count == 3


class TestBuiltinTemplates:
    def test_research_report_exists(self):
        t = BUILTIN_TEMPLATES.get("research_report")
        assert t is not None
        assert t.name == "research_report"
        assert t.step_count == 3

    def test_code_review_exists(self):
        t = BUILTIN_TEMPLATES.get("code_review")
        assert t is not None
        assert t.name == "code_review"
        assert t.step_count >= 4

    def test_serialization_roundtrip(self):
        for name, template in BUILTIN_TEMPLATES.items():
            d = template.to_dict()
            t2 = WorkflowTemplate.from_dict(d)
            assert t2.name == template.name
            assert t2.step_count == template.step_count
