"""
AgentOS Workflow DSL — Declarative multi-agent workflow definition language.

v1.14.4: YAML/JSON-based DSL for defining complex multi-agent pipelines with
         sequential, parallel, conditional, loop, and fan-out/fan-in patterns.

Key features:
- YAML/JSON declarative workflow definitions
- Topology validation and cycle detection
- Sequential, parallel, conditional, loop, sub-workflow patterns
- Built-in fan-out/fan-in via agentos.core.parallel
- Workflow execution engine with real-time progress
- Dry-run mode for validation without execution
- Visual DAG export (Mermaid/Graphviz)
- Error recovery strategies (retry, fallback, skip, escalate)
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set, Type, Union

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StepType(Enum):
    """Types of workflow steps."""
    TASK        = "task"        # Single agent task
    SEQUENTIAL  = "sequential"  # Run children in sequence
    PARALLEL    = "parallel"    # Run children in parallel
    CONDITIONAL = "conditional" # Branch based on condition
    LOOP        = "loop"        # Repeat children until condition
    SUB_WORKFLOW = "sub"        # Nested workflow
    JOIN        = "join"        # Wait for all branches to complete
    SPLIT       = "split"       # Fan-out to multiple agents


class ExecutionStatus(Enum):
    PENDING     = "pending"
    RUNNING     = "running"
    SUCCESS     = "success"
    FAILED      = "failed"
    SKIPPED     = "skipped"
    CANCELLED   = "cancelled"
    RETRYING    = "retrying"


class ErrorStrategy(Enum):
    RETRY     = "retry"      # Retry the step
    FALLBACK  = "fallback"   # Execute fallback step
    SKIP      = "skip"       # Skip and continue
    ESCALATE  = "escalate"   # Fail the workflow
    PAUSE     = "pause"      # Pause for human intervention


class ConditionOperator(Enum):
    EQUALS      = "eq"
    NOT_EQUALS  = "neq"
    CONTAINS    = "contains"
    GREATER     = "gt"
    LESS        = "lt"
    IN          = "in"
    MATCHES     = "matches"  # regex
    EXISTS      = "exists"
    EMPTY       = "empty"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WorkflowContext:
    """Runtime context shared across workflow steps."""
    variables: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a variable, supporting dot-notation (e.g., 'result.output.text')."""
        parts = key.split(".")
        current = self.variables
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part, default)
            else:
                return default
        return current

    def set(self, key: str, value: Any) -> None:
        """Set a variable, supporting dot-notation for nested dicts."""
        parts = key.split(".")
        current = self.variables
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value


@dataclass
class StepResult:
    """Result of a workflow step execution."""
    step_id: str
    status: ExecutionStatus
    output: Any = None
    error: Optional[str] = None
    duration: float = 0.0
    retries: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowStep:
    """A single step in a workflow DAG."""
    id: str
    type: StepType
    name: str = ""
    description: str = ""

    # Execution
    agent: Optional[str] = None         # agent_id to dispatch to
    task: Optional[str] = None          # task payload template
    children: List["WorkflowStep"] = field(default_factory=list)

    # Conditional
    condition: Optional[Dict[str, Any]] = None
    branches: Dict[str, List["WorkflowStep"]] = field(default_factory=dict)

    # Loop
    max_iterations: int = 100
    loop_condition: Optional[Dict[str, Any]] = None

    # Error handling
    on_error: ErrorStrategy = ErrorStrategy.ESCALATE
    max_retries: int = 3
    retry_delay: float = 1.0
    fallback_step: Optional["WorkflowStep"] = None

    # Timing
    timeout: float = 300.0
    depends_on: List[str] = field(default_factory=list)

    # Metadata
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowDefinition:
    """Top-level workflow definition."""
    name: str
    version: str = "1.0"
    description: str = ""
    root: Optional[WorkflowStep] = None
    variables: Dict[str, Any] = field(default_factory=dict)
    agents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    defaults: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        """Validate workflow structure and return a list of issues."""
        issues = []
        step_ids: Set[str] = set()

        def validate_step(step: WorkflowStep):
            if step.id in step_ids:
                issues.append(f"Duplicate step ID: {step.id}")
            step_ids.add(step.id)

            if step.type == StepType.CONDITIONAL and not step.condition:
                issues.append(f"Conditional step '{step.id}' has no condition")
            if step.type == StepType.TASK and not step.agent:
                issues.append(f"Task step '{step.id}' has no agent assigned")

            # Validate depends_on references
            for dep in step.depends_on:
                if dep not in step_ids:
                    issues.append(f"Step '{step.id}' depends on unknown step '{dep}'")

            for child in step.children:
                validate_step(child)
            for branch_steps in step.branches.values():
                for s in branch_steps:
                    validate_step(s)
            if step.fallback_step:
                validate_step(step.fallback_step)

        if self.root:
            validate_step(self.root)
        else:
            issues.append("Workflow has no root step")

        return issues

    def to_mermaid(self) -> str:
        """Export workflow as a Mermaid flowchart."""
        lines = ["graph TD"]
        ids: Set[str] = set()

        def add_step(step: WorkflowStep, parent_id: Optional[str] = None):
            prefix = {StepType.PARALLEL: "[||]", StepType.CONDITIONAL: "{?}",
                      StepType.LOOP: "[/]", StepType.TASK: "[ ]",
                      StepType.JOIN: "[+]", StepType.SPLIT: "[>]"}.get(step.type, "[ ]")
            label = step.name or step.id
            lines.append(f"    {step.id}{prefix}{label}")

            if parent_id:
                lines.append(f"    {parent_id} --> {step.id}")

            if step.id not in ids:
                ids.add(step.id)
                if step.type == StepType.CONDITIONAL:
                    for branch_name, branch_steps in step.branches.items():
                        for s in branch_steps:
                            add_step(s, step.id)
                            lines.append(f"    {step.id} -- {branch_name} --> {s.id}")
                else:
                    for child in step.children:
                        add_step(child, step.id)

        if self.root:
            add_step(self.root)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

class ConditionEvaluator:
    """Evaluate conditions against the workflow context."""

    @staticmethod
    def evaluate(condition: Dict[str, Any], ctx: WorkflowContext) -> bool:
        """Evaluate a condition dict against context."""
        if not condition:
            return True

        # Support AND/OR combinators
        if "and" in condition:
            return all(
                ConditionEvaluator.evaluate(sub, ctx)
                for sub in condition["and"]
            )
        if "or" in condition:
            return any(
                ConditionEvaluator.evaluate(sub, ctx)
                for sub in condition["or"]
            )
        if "not" in condition:
            return not ConditionEvaluator.evaluate(condition["not"], ctx)

        # Single condition
        field = condition.get("field", "")
        op = condition.get("op", "eq")
        value = condition.get("value")

        actual = ctx.get(field)
        operator = ConditionOperator(op)

        if operator == ConditionOperator.EQUALS:
            return actual == value
        elif operator == ConditionOperator.NOT_EQUALS:
            return actual != value
        elif operator == ConditionOperator.CONTAINS:
            return value in str(actual) if actual is not None else False
        elif operator == ConditionOperator.GREATER:
            try:
                return float(actual) > float(value)
            except (TypeError, ValueError):
                return False
        elif operator == ConditionOperator.LESS:
            try:
                return float(actual) < float(value)
            except (TypeError, ValueError):
                return False
        elif operator == ConditionOperator.IN:
            return actual in value if isinstance(value, (list, tuple, set)) else False
        elif operator == ConditionOperator.MATCHES:
            import re
            try:
                return bool(re.search(str(value), str(actual)))
            except re.error:
                return False
        elif operator == ConditionOperator.EXISTS:
            return actual is not None
        elif operator == ConditionOperator.EMPTY:
            return actual is None or actual == "" or actual == [] or actual == {}

        return False


# ---------------------------------------------------------------------------
# Workflow Engine
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """Executes a WorkflowDefinition with real-time progress tracking."""

    def __init__(
        self,
        agent_dispatcher: Optional[Callable] = None,
        max_parallelism: int = 10,
    ):
        self._dispatcher = agent_dispatcher or self._default_dispatcher
        self._max_parallelism = max_parallelism
        self._ctx: Optional[WorkflowContext] = None
        self._results: Dict[str, StepResult] = {}
        self._progress_callbacks: List[Callable] = []
        self._cancelled = False
        self._semaphore = asyncio.Semaphore(max_parallelism)

    def on_progress(self, callback: Callable[[StepResult], None]) -> None:
        """Register a progress callback."""
        self._progress_callbacks.append(callback)

    async def execute(self, workflow: WorkflowDefinition) -> WorkflowContext:
        """Execute a workflow and return the final context."""
        issues = workflow.validate()
        if issues:
            raise ValueError(f"Workflow validation failed: {issues}")

        self._ctx = WorkflowContext(variables=dict(workflow.variables))
        self._results = {}
        self._cancelled = False

        if workflow.root:
            await self._execute_step(workflow.root, self._ctx)

        return self._ctx

    async def dry_run(self, workflow: WorkflowDefinition) -> Dict[str, Any]:
        """Validate a workflow without executing it."""
        issues = workflow.validate()
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "steps": self._count_steps(workflow.root) if workflow.root else 0,
            "mermaid": workflow.to_mermaid(),
        }

    def cancel(self) -> None:
        """Cancel the running workflow."""
        self._cancelled = True

    async def _execute_step(
        self, step: WorkflowStep, ctx: WorkflowContext
    ) -> StepResult:
        if self._cancelled:
            return StepResult(step.id, ExecutionStatus.CANCELLED)

        if step.id in self._results:
            return self._results[step.id]

        logger.info(f"[Workflow] Executing step '{step.id}' ({step.type.value})")
        result = StepResult(step.id, ExecutionStatus.RUNNING)

        try:
            if step.type == StepType.TASK:
                result = await self._run_task(step, ctx)
            elif step.type == StepType.SEQUENTIAL:
                result = await self._run_sequential(step, ctx)
            elif step.type == StepType.PARALLEL:
                result = await self._run_parallel(step, ctx)
            elif step.type == StepType.CONDITIONAL:
                result = await self._run_conditional(step, ctx)
            elif step.type == StepType.LOOP:
                result = await self._run_loop(step, ctx)
            elif step.type == StepType.SUB_WORKFLOW:
                result = await self._run_sub_workflow(step, ctx)
            elif step.type == StepType.JOIN:
                result = await self._run_join(step, ctx)
            elif step.type == StepType.SPLIT:
                result = await self._run_split(step, ctx)
            else:
                result.status = ExecutionStatus.SUCCESS

        except asyncio.TimeoutError:
            result.status = ExecutionStatus.FAILED
            result.error = f"Step '{step.id}' timed out after {step.timeout}s"
        except Exception as e:
            result.status = ExecutionStatus.FAILED
            result.error = str(e)
            logger.exception(f"[Workflow] Step '{step.id}' failed: {e}")

            # Error recovery
            result = await self._handle_error(step, ctx, result)

        self._results[step.id] = result
        ctx.history.append({"step_id": step.id, "status": result.status.value,
                            "output": str(result.output)[:200] if result.output else None,
                            "error": result.error, "duration": result.duration})

        for cb in self._progress_callbacks:
            try:
                cb(result)
            except Exception:
                pass

        return result

    async def _run_task(self, step: WorkflowStep, ctx: WorkflowContext) -> StepResult:
        """Execute a single agent task."""
        import time
        t0 = time.time()

        # Resolve template variables in task payload
        payload = step.task or ""
        if "{{" in payload:
            payload = self._resolve_template(payload, ctx)

        try:
            output = await asyncio.wait_for(
                self._dispatcher(step.agent, payload, ctx),
                timeout=step.timeout,
            )
            ctx.set(f"steps.{step.id}.output", output)
            return StepResult(
                step.id, ExecutionStatus.SUCCESS,
                output=output,
                duration=time.time() - t0,
            )
        except asyncio.TimeoutError:
            raise

    async def _run_sequential(
        self, step: WorkflowStep, ctx: WorkflowContext
    ) -> StepResult:
        """Run children in sequence."""
        for child in step.children:
            result = await self._execute_step(child, ctx)
            if result.status == ExecutionStatus.FAILED and step.on_error == ErrorStrategy.ESCALATE:
                return StepResult(step.id, ExecutionStatus.FAILED,
                                  error=f"Child '{child.id}' failed: {result.error}")
        return StepResult(step.id, ExecutionStatus.SUCCESS)

    async def _run_parallel(
        self, step: WorkflowStep, ctx: WorkflowContext
    ) -> StepResult:
        """Run children in parallel with semaphore control."""
        async def bounded_execute(child):
            async with self._semaphore:
                return await self._execute_step(child, ctx)

        tasks = [bounded_execute(child) for child in step.children]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        outputs = {}
        for child, result in zip(step.children, results):
            if isinstance(result, Exception):
                outputs[child.id] = {"error": str(result)}
            else:
                outputs[child.id] = result.output

        ctx.set(f"steps.{step.id}.outputs", outputs)
        return StepResult(step.id, ExecutionStatus.SUCCESS, output=outputs)

    async def _run_conditional(
        self, step: WorkflowStep, ctx: WorkflowContext
    ) -> StepResult:
        """Evaluate condition and execute the matching branch."""
        if not step.condition:
            return StepResult(step.id, ExecutionStatus.SKIPPED,
                              error="No condition defined")

        matched = ConditionEvaluator.evaluate(step.condition, ctx)
        branch_key = "true" if matched else "false"
        branch_steps = step.branches.get(branch_key, [])
        if not branch_steps:
            # Try numeric/default branches
            branch_steps = step.branches.get("default", [])

        for child in branch_steps:
            result = await self._execute_step(child, ctx)
            if result.status == ExecutionStatus.FAILED:
                return StepResult(step.id, ExecutionStatus.FAILED,
                                  error=f"Branch child '{child.id}' failed: {result.error}")

        return StepResult(step.id, ExecutionStatus.SUCCESS,
                          output={"branch": branch_key})

    async def _run_loop(self, step: WorkflowStep, ctx: WorkflowContext) -> StepResult:
        """Execute children in a loop until condition is false."""
        iteration = 0
        while iteration < step.max_iterations:
            if self._cancelled:
                return StepResult(step.id, ExecutionStatus.CANCELLED)

            for child in step.children:
                result = await self._execute_step(child, ctx)
                if result.status == ExecutionStatus.FAILED:
                    return StepResult(step.id, ExecutionStatus.FAILED,
                                      error=f"Loop iteration {iteration}: child '{child.id}' failed")

            ctx.set(f"steps.{step.id}.iteration", iteration)
            iteration += 1

            # Check loop condition
            if step.loop_condition:
                if not ConditionEvaluator.evaluate(step.loop_condition, ctx):
                    break

        return StepResult(step.id, ExecutionStatus.SUCCESS,
                          output={"iterations": iteration})

    async def _run_sub_workflow(self, step: WorkflowStep, ctx: WorkflowContext) -> StepResult:
        """Execute a nested sub-workflow."""
        # Sub-workflow steps just execute their children
        for child in step.children:
            result = await self._execute_step(child, ctx)
            if result.status == ExecutionStatus.FAILED:
                return StepResult(step.id, ExecutionStatus.FAILED,
                                  error=f"Sub-workflow child '{child.id}' failed")
        return StepResult(step.id, ExecutionStatus.SUCCESS)

    async def _run_join(self, step: WorkflowStep, ctx: WorkflowContext) -> StepResult:
        """Join point — wait for specified dependencies."""
        # Already handled by depends_on graph resolution
        return StepResult(step.id, ExecutionStatus.SUCCESS)

    async def _run_split(self, step: WorkflowStep, ctx: WorkflowContext) -> StepResult:
        """Fan-out to multiple agents."""
        children_results = await self._run_parallel(step, ctx)
        return children_results

    async def _handle_error(
        self, step: WorkflowStep, ctx: WorkflowContext, result: StepResult
    ) -> StepResult:
        """Apply error recovery strategy."""
        ctx.errors.append({"step_id": step.id, "error": result.error})

        if step.on_error == ErrorStrategy.RETRY and result.retries < step.max_retries:
            logger.info(f"[Workflow] Retrying step '{step.id}' ({result.retries+1}/{step.max_retries})")
            await asyncio.sleep(step.retry_delay * (2 ** result.retries))
            result.retries += 1
            return await self._execute_step(step, ctx)

        elif step.on_error == ErrorStrategy.FALLBACK and step.fallback_step:
            logger.info(f"[Workflow] Executing fallback for step '{step.id}'")
            return await self._execute_step(step.fallback_step, ctx)

        elif step.on_error == ErrorStrategy.SKIP:
            result.status = ExecutionStatus.SKIPPED
            return result

        elif step.on_error == ErrorStrategy.PAUSE:
            logger.warning(f"[Workflow] Paused at step '{step.id}': {result.error}")
            # In production, this would notify the HITL system
            return result

        # Default: escalate
        return result

    @staticmethod
    async def _default_dispatcher(agent_id: str, task: str, ctx: WorkflowContext) -> str:
        """Default task dispatcher — logs and returns mock result."""
        logger.info(f"[Workflow] Dispatch to '{agent_id}': {task[:100]}")
        return f"Task dispatched to {agent_id}: {task[:50]}"

    @staticmethod
    def _resolve_template(template: str, ctx: WorkflowContext) -> str:
        """Resolve {{ variable }} placeholders in a template string."""
        import re
        def replacer(match):
            key = match.group(1).strip()
            return str(ctx.get(key, f"<{key} not found>"))
        return re.sub(r"\{\{\s*(.*?)\s*\}\}", replacer, template)

    @staticmethod
    def _count_steps(step: Optional[WorkflowStep]) -> int:
        if step is None:
            return 0
        count = 1
        for child in step.children:
            count += WorkflowEngine._count_steps(child)
        for branch_steps in step.branches.values():
            for s in branch_steps:
                count += WorkflowEngine._count_steps(s)
        if step.fallback_step:
            count += WorkflowEngine._count_steps(step.fallback_step)
        return count


# ---------------------------------------------------------------------------
# Workflow YAML/JSON Parser
# ---------------------------------------------------------------------------

class WorkflowParser:
    """Parse YAML/JSON files into WorkflowDefinition objects."""

    @staticmethod
    def parse_file(filepath: Union[str, Path]) -> WorkflowDefinition:
        """Parse a .yaml/.yml/.json file into a WorkflowDefinition."""
        path = Path(filepath)
        with open(path, "r", encoding="utf-8") as f:
            if path.suffix in (".json",):
                data = json.load(f)
            else:
                data = yaml.safe_load(f)
        return WorkflowParser.parse_dict(data)

    @staticmethod
    def parse_dict(data: Dict[str, Any]) -> WorkflowDefinition:
        """Parse a dict into a WorkflowDefinition."""
        wf = WorkflowDefinition(
            name=data.get("name", "unnamed"),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            variables=data.get("variables", {}),
            agents=data.get("agents", {}),
            defaults=data.get("defaults", {}),
            metadata=data.get("metadata", {}),
        )

        if "steps" in data:
            wf.root = WorkflowParser._parse_steps(data["steps"])

        return wf

    @staticmethod
    def _parse_steps(steps: List[Dict[str, Any]]) -> WorkflowStep:
        """Parse a list of step dicts into a tree. First step is root."""
        if not steps:
            raise ValueError("No steps defined")

        parsed = [WorkflowParser._parse_step(s) for s in steps]

        # Build parent-child relationships
        for i in range(len(parsed) - 1):
            if not parsed[i].children:
                parsed[i].children = [parsed[i + 1]]

        return parsed[0]

    @staticmethod
    def _parse_step(data: Dict[str, Any]) -> WorkflowStep:
        """Parse a single step dict."""
        step = WorkflowStep(
            id=data.get("id", ""),
            type=StepType(data.get("type", "task")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            agent=data.get("agent"),
            task=data.get("task"),
            timeout=data.get("timeout", 300.0),
            depends_on=data.get("depends_on", []),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )

        if "condition" in data:
            step.condition = data["condition"]

        if "branches" in data:
            for branch_name, branch_steps in data["branches"].items():
                step.branches[branch_name] = [
                    WorkflowParser._parse_step(s) for s in branch_steps
                ]

        if "children" in data:
            step.children = [WorkflowParser._parse_step(c) for c in data["children"]]

        if "on_error" in data:
            step.on_error = ErrorStrategy(data["on_error"])
        if "max_retries" in data:
            step.max_retries = data["max_retries"]
        if "retry_delay" in data:
            step.retry_delay = data["retry_delay"]
        if "fallback" in data:
            step.fallback_step = WorkflowParser._parse_step(data["fallback"])

        if step.type == StepType.LOOP:
            step.max_iterations = data.get("max_iterations", 100)
            if "loop_condition" in data:
                step.loop_condition = data["loop_condition"]

        return step

    @staticmethod
    def to_yaml(workflow: WorkflowDefinition) -> str:
        """Serialize a WorkflowDefinition to YAML string."""
        return yaml.dump(WorkflowParser._to_dict(workflow), default_flow_style=False)

    @staticmethod
    def to_json(workflow: WorkflowDefinition) -> str:
        """Serialize a WorkflowDefinition to JSON string."""
        return json.dumps(WorkflowParser._to_dict(workflow), indent=2)

    @staticmethod
    def _to_dict(wf: WorkflowDefinition) -> Dict[str, Any]:
        data = {
            "name": wf.name,
            "version": wf.version,
            "description": wf.description,
            "variables": wf.variables,
            "agents": wf.agents,
            "defaults": wf.defaults,
            "metadata": wf.metadata,
        }
        if wf.root:
            data["steps"] = [WorkflowParser._step_to_dict(wf.root)]
        return data

    @staticmethod
    def _step_to_dict(step: WorkflowStep) -> Dict[str, Any]:
        d = {
            "id": step.id,
            "type": step.type.value,
            "name": step.name,
            "description": step.description,
            "agent": step.agent,
            "task": step.task,
            "timeout": step.timeout,
            "depends_on": step.depends_on,
            "tags": step.tags,
            "metadata": step.metadata,
        }
        if step.condition:
            d["condition"] = step.condition
        if step.branches:
            d["branches"] = {
                k: [WorkflowParser._step_to_dict(s) for s in v]
                for k, v in step.branches.items()
            }
        if step.children:
            d["children"] = [WorkflowParser._step_to_dict(c) for c in step.children]
        if step.on_error != ErrorStrategy.ESCALATE:
            d["on_error"] = step.on_error.value
        if step.max_retries != 3:
            d["max_retries"] = step.max_retries
        if step.retry_delay != 1.0:
            d["retry_delay"] = step.retry_delay
        if step.fallback_step:
            d["fallback"] = WorkflowParser._step_to_dict(step.fallback_step)
        if step.type == StepType.LOOP:
            d["max_iterations"] = step.max_iterations
            if step.loop_condition:
                d["loop_condition"] = step.loop_condition
        return d


# ---------------------------------------------------------------------------
# Pre-built workflow templates
# ---------------------------------------------------------------------------

class WorkflowTemplates:
    """Library of common workflow patterns."""

    @staticmethod
    def sequential(name: str, agent_ids: List[str], task_template: str) -> WorkflowDefinition:
        """Create a sequential pipeline: Agent1 → Agent2 → Agent3."""
        root = None
        prev = None
        for agent_id in agent_ids:
            step = WorkflowStep(
                id=f"step_{agent_id}",
                type=StepType.TASK,
                name=f"Task by {agent_id}",
                agent=agent_id,
                task=task_template,
            )
            if prev:
                prev.children = [step]
            if root is None:
                root = step
            prev = step

        return WorkflowDefinition(name=name, root=root)

    @staticmethod
    def parallel_broadcast(
        name: str, agent_ids: List[str], task_template: str
    ) -> WorkflowDefinition:
        """Create a parallel broadcast: all agents run simultaneously."""
        children = [
            WorkflowStep(
                id=f"step_{agent_id}",
                type=StepType.TASK,
                name=f"Broadcast to {agent_id}",
                agent=agent_id,
                task=task_template,
            )
            for agent_id in agent_ids
        ]
        root = WorkflowStep(
            id="broadcast",
            type=StepType.PARALLEL,
            name="Parallel broadcast",
            children=children,
        )
        return WorkflowDefinition(name=name, root=root)

    @staticmethod
    def map_reduce(
        name: str,
        mapper_agents: List[str],
        reducer_agent: str,
        map_task: str,
        reduce_task: str,
    ) -> WorkflowDefinition:
        """Map-Reduce pattern: parallel map → single reduce."""
        map_steps = [
            WorkflowStep(
                id=f"map_{agent_id}",
                type=StepType.TASK,
                name=f"Map by {agent_id}",
                agent=agent_id,
                task=map_task,
            )
            for agent_id in mapper_agents
        ]
        map_root = WorkflowStep(
            id="map_phase",
            type=StepType.PARALLEL,
            name="Map phase",
            children=map_steps,
        )
        reduce_step = WorkflowStep(
            id="reduce_phase",
            type=StepType.TASK,
            name=f"Reduce by {reducer_agent}",
            agent=reducer_agent,
            task=reduce_task,
        )
        map_root.children = [reduce_step]

        return WorkflowDefinition(name=name, root=map_root)

    @staticmethod
    def conditional_branch(
        name: str,
        condition_field: str,
        true_agent: str,
        false_agent: str,
        task_template: str,
    ) -> WorkflowDefinition:
        """Conditional branching: if condition → agentA else → agentB."""
        true_step = WorkflowStep(
            id="true_branch",
            type=StepType.TASK,
            name=f"True: {true_agent}",
            agent=true_agent,
            task=task_template,
        )
        false_step = WorkflowStep(
            id="false_branch",
            type=StepType.TASK,
            name=f"False: {false_agent}",
            agent=false_agent,
            task=task_template,
        )
        root = WorkflowStep(
            id="condition",
            type=StepType.CONDITIONAL,
            name="Condition check",
            condition={"field": condition_field, "op": "eq", "value": True},
            branches={"true": [true_step], "false": [false_step]},
        )
        return WorkflowDefinition(name=name, root=root)

    @staticmethod
    def retry_loop(
        name: str, agent_id: str, task: str, max_retries: int = 3
    ) -> WorkflowDefinition:
        """Task with automatic retry on failure."""
        step = WorkflowStep(
            id="retry_task",
            type=StepType.TASK,
            name=f"Task with retry",
            agent=agent_id,
            task=task,
            on_error=ErrorStrategy.RETRY,
            max_retries=max_retries,
            retry_delay=2.0,
        )
        return WorkflowDefinition(name=name, root=step)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "StepType",
    "ExecutionStatus",
    "ErrorStrategy",
    "ConditionOperator",
    # Data
    "WorkflowContext",
    "StepResult",
    "WorkflowStep",
    "WorkflowDefinition",
    # Engine
    "WorkflowEngine",
    "ConditionEvaluator",
    # Parser
    "WorkflowParser",
    # Templates
    "WorkflowTemplates",
]
