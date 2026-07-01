"""
Workflow Templates — Declarative, reusable multi-step agent workflows.

Define workflows as YAML/JSON templates with conditional branching,
parallel execution, retry policies, and human-in-the-loop checkpoints.
"""

from __future__ import annotations

import json
import yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class StepType(Enum):

    """步骤类型枚举。"""

    AGENT = "agent"
    TOOL = "tool"
    CONDITION = "condition"
    PARALLEL = "parallel"
    HUMAN_REVIEW = "human_review"
    TRANSFORM = "transform"
    WAIT = "wait"


class RetryPolicy(Enum):

    """重试策略类。"""

    NONE = "none"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


@dataclass
class WorkflowStep:
    """Single step in a workflow template."""

    name: str
    step_type: StepType = StepType.AGENT
    description: str = ""

    # Agent/Tool step
    agent_type: str = "default"
    task_template: str = ""
    tool_name: str = ""

    # Condition step
    condition: str = ""
    """Python expression evaluated with step outputs as variables."""

    then_steps: list["WorkflowStep"] = field(default_factory=list)
    else_steps: list["WorkflowStep"] = field(default_factory=list)

    # Parallel step
    sub_steps: list["WorkflowStep"] = field(default_factory=list)
    max_concurrency: int = 5

    # Human review
    review_prompt: str = ""
    timeout_minutes: int = 30

    # Retry
    retry_policy: RetryPolicy = RetryPolicy.NONE
    max_retries: int = 3
    retry_delay_seconds: float = 1.0

    # Transform
    transform_expr: str = ""
    """Python expression to transform output."""

    # Input/output
    depends_on: list[str] = field(default_factory=list)
    output_key: str = ""
    """Store output under this key for downstream steps."""


@dataclass
class WorkflowTemplate:
    """
    Declarative workflow template.

    Example (YAML)::

        name: research_report
        description: Research a topic and generate a report
        steps:
          - name: research
            step_type: agent
            agent_type: researcher
            task_template: "Research: {{input.topic}}"
            output_key: research_result
          - name: review
            step_type: human_review
            review_prompt: "Review the research: {{research_result}}"
            depends_on: [research]
          - name: write_report
            step_type: agent
            agent_type: writer
            task_template: "Write report based on: {{research_result}}"
            depends_on: [review]
            output_key: final_report
    """

    name: str
    description: str = ""
    version: str = "1.0"
    steps: list[WorkflowStep] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "steps": [self._step_to_dict(s) for s in self.steps],
            "metadata": self.metadata,
        }

    def _step_to_dict(self, step: WorkflowStep) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": step.name,
            "step_type": step.step_type.value,
            "description": step.description,
        }
        if step.agent_type != "default":
            d["agent_type"] = step.agent_type
        if step.task_template:
            d["task_template"] = step.task_template
        if step.tool_name:
            d["tool_name"] = step.tool_name
        if step.output_key:
            d["output_key"] = step.output_key
        if step.condition:
            d["condition"] = step.condition
        if step.depends_on:
            d["depends_on"] = step.depends_on
        if step.then_steps:
            d["then_steps"] = [self._step_to_dict(s) for s in step.then_steps]
        if step.else_steps:
            d["else_steps"] = [self._step_to_dict(s) for s in step.else_steps]
        if step.sub_steps:
            d["sub_steps"] = [self._step_to_dict(s) for s in step.sub_steps]
            d["max_concurrency"] = step.max_concurrency
        if step.retry_policy != RetryPolicy.NONE:
            d["retry_policy"] = step.retry_policy.value
            d["max_retries"] = step.max_retries
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowTemplate":
        """Deserialize from dict."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            steps=[cls._step_from_dict(s) for s in data.get("steps", [])],
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def _step_from_dict(cls, data: dict[str, Any]) -> WorkflowStep:
        return WorkflowStep(
            name=data["name"],
            step_type=StepType(data.get("step_type", "agent")),
            description=data.get("description", ""),
            agent_type=data.get("agent_type", "default"),
            task_template=data.get("task_template", ""),
            tool_name=data.get("tool_name", ""),
            output_key=data.get("output_key", ""),
            condition=data.get("condition", ""),
            depends_on=data.get("depends_on", []),
            then_steps=[cls._step_from_dict(s) for s in data.get("then_steps", [])],
            else_steps=[cls._step_from_dict(s) for s in data.get("else_steps", [])],
            sub_steps=[cls._step_from_dict(s) for s in data.get("sub_steps", [])],
            max_concurrency=data.get("max_concurrency", 5),
            retry_policy=RetryPolicy(data.get("retry_policy", "none")),
            max_retries=data.get("max_retries", 3),
            retry_delay_seconds=data.get("retry_delay_seconds", 1.0),
        )

    def to_yaml(self) -> str:
        """Export workflow as YAML string."""
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    def to_json(self, indent: int = 2) -> str:
        """Export workflow as JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "WorkflowTemplate":
        """Load workflow from YAML string."""
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)

    @classmethod
    def from_json(cls, json_str: str) -> "WorkflowTemplate":
        """Load workflow from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def get_step(self, name: str) -> Optional[WorkflowStep]:
        """Find a step by name (searches recursively)."""
        for step in self.steps:
            result = self._find_step(step, name)
            if result:
                return result
        return None

    def _find_step(self, step: WorkflowStep, name: str) -> Optional[WorkflowStep]:
        if step.name == name:
            return step
        for sub in step.then_steps + step.else_steps + step.sub_steps:
            result = self._find_step(sub, name)
            if result:
                return result
        return None

    def flatten_steps(self) -> list[WorkflowStep]:
        """Return all steps in a flat list."""
        result: list[WorkflowStep] = []
        for step in self.steps:
            self._flatten(step, result)
        return result

    def _flatten(self, step: WorkflowStep, result: list[WorkflowStep]) -> None:
        result.append(step)
        for sub in step.then_steps + step.else_steps + step.sub_steps:
            self._flatten(sub, result)

    @property
    def step_count(self) -> int:
        return len(self.flatten_steps())


# ---- Built-in Workflow Templates ----

BUILTIN_TEMPLATES: dict[str, WorkflowTemplate] = {}


def _init_builtins() -> None:
    """Initialize built-in workflow templates."""
    # Research → Summarize → Report
    BUILTIN_TEMPLATES["research_report"] = WorkflowTemplate(
        name="research_report",
        description="Research a topic, summarize findings, generate report",
        steps=[
            WorkflowStep(
                name="research",
                step_type=StepType.AGENT,
                agent_type="researcher",
                task_template="Deep research on: {{input.topic}}",
                output_key="research",
            ),
            WorkflowStep(
                name="summarize",
                step_type=StepType.AGENT,
                agent_type="summarizer",
                task_template="Summarize key findings from: {{research}}",
                depends_on=["research"],
                output_key="summary",
            ),
            WorkflowStep(
                name="report",
                step_type=StepType.AGENT,
                agent_type="writer",
                task_template="Write a comprehensive report based on: {{research}}\\nSummary: {{summary}}",
                depends_on=["research", "summarize"],
                output_key="report",
            ),
        ],
    )

    # Code Review → Fix → Test
    BUILTIN_TEMPLATES["code_review"] = WorkflowTemplate(
        name="code_review",
        description="Review code, apply fixes, run tests",
        steps=[
            WorkflowStep(
                name="review",
                step_type=StepType.AGENT,
                agent_type="code_reviewer",
                task_template="Review this code for bugs and improvements:\\n```\\n{{input.code}}\\n```",
                output_key="review_feedback",
            ),
            WorkflowStep(
                name="human_approval",
                step_type=StepType.HUMAN_REVIEW,
                review_prompt="Approve fixes based on: {{review_feedback}}",
                depends_on=["review"],
            ),
            WorkflowStep(
                name="apply_fixes",
                step_type=StepType.AGENT,
                agent_type="coder",
                task_template="Apply fixes based on review:\\n{{review_feedback}}\\n\\nOriginal code:\\n```\\n{{input.code}}\\n```",
                depends_on=["human_approval"],
                output_key="fixed_code",
                retry_policy=RetryPolicy.EXPONENTIAL,
                max_retries=3,
            ),
            WorkflowStep(
                name="test",
                step_type=StepType.TOOL,
                tool_name="run_tests",
                depends_on=["apply_fixes"],
            ),
        ],
    )


_init_builtins()
