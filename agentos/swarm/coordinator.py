"""
v1.9.8: Smart Swarm Coordinator with tool registry + intelligent routing.

Full intelligence stack:
- TaskDecomposer: decompose complex tasks into sub-task DAGs
- ResultFusion: LLM-as-Judge aggregation with confidence scoring
- EvalFeedbackLoop: execute → evaluate → retry → converge
- CodeSandbox: safe code generation & execution with test cases
- HumanLoop: human-in-the-loop breakpoints for approval/intervention
- AgentMonitor: quality gates + self-monitoring pipeline
- ExecutionTrace: full span-tree observability + bottleneck detection
- AgentMemory: three-tier memory (working/short-term/long-term) + context window
- ToolRegistry: schema-based tool catalog with versioning, capabilities, search
- ToolRouter: intelligent tool selection with LLM + semantic matching
- ToolExecutor: safe tool execution with validation, rate limiting, destructive confirmation
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from agentos.core.di import Agent, RunContext
from agentos.swarm.task_decomposer import TaskDecomposer, Decomposition, SubTask
from agentos.swarm.result_fusion import ResultFusion, FusedResult
from agentos.swarm.eval_feedback_loop import EvalFeedbackLoop, LoopResult, RetryConfig
from agentos.swarm.code_sandbox import CodeSandbox, SandboxResult, TestCase, CodeFeedbackExtractor
from agentos.swarm.human_loop import (
    HITLManager, HITLConfig, Breakpoint, BreakpointType, HumanDecision,
)
from agentos.swarm.agent_monitor import (
    AgentMonitor, QualityGate, MonitorReport, GateResult, GateStatus, GateAction,
    output_not_empty, output_length_range, no_error_output, contains_keywords,
    latency_max, confidence_min,
)
from agentos.swarm.execution_trace import (
    ExecutionTrace, TraceSpan, TraceEvent, TraceCollector,
)
from agentos.swarm.agent_memory import (
    AgentMemory, WorkingMemory, ShortTermMemory, LongTermMemory,
    ContextWindowManager, ContextBudget, MemoryEntry,
)
from agentos.swarm.tool_registry import (
    ToolRegistry, ToolRouter, ToolExecutor, ToolSchema, ToolParam,
    ToolCategory, RoutingDecision, RoutingContext, ToolExecutionError,
    create_tool,
)
from agentos.security.guard import (
    GuardPipeline, InputGuard, OutputGuard,
    PIIDetector, ContentSafetyFilter,
    create_strict_guard, create_permissive_guard,
    GuardChainResult,
)


class SwarmTopology(str, Enum):
    """Swarm topology types."""
    STAR = "star"     # Central coordinator
    RING = "ring"     # Circular message passing
    MESH = "mesh"     # All-to-all communication
    TREE = "tree"     # Hierarchical structure


class ExecutionMode(str, Enum):
    """Execution strategy for the coordinator."""
    RAW = "raw"             # Original topology-only execution
    SMART = "smart"         # Decompose → Execute DAG → Fuse
    FEEDBACK = "feedback"   # Smart + eval feedback loop


@dataclass
class AgentRole:
    """Agent 角色定义。"""
    name: str
    goal: str
    backstory: str = ""
    tools: list[str] = field(default_factory=list)
    model: str = "auto"
    temperature: float = 0.7
    allow_delegation: bool = True
    verbose: bool = False


class MessageBus:
    """Agent 间消息总线 — 黑板模式。"""

    def __init__(self):
        self._messages: list[dict] = []
        self._subscribers: dict[str, list[Callable]] = {}
        self._shared_memory: dict[str, Any] = {}

    def publish(self, sender: str, topic: str, data: dict):
        msg = {"sender": sender, "topic": topic, "data": data}
        self._messages.append(msg)
        if topic in self._subscribers:
            for cb in self._subscribers[topic]:
                cb(msg)

    def subscribe(self, topic: str, callback: Callable):
        self._subscribers.setdefault(topic, []).append(callback)

    @property
    def messages(self) -> list[dict]:
        return self._messages

    @property
    def shared_memory(self) -> dict[str, Any]:
        return self._shared_memory


@dataclass
class SwarmMessage:
    """
    Message in swarm communication.

    Attributes:
        id: Unique identifier
        sender: Sender agent name
        receiver: Receiver agent name (None = broadcast)
        content: Message content
        metadata: Additional metadata
        timestamp: Message timestamp
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    sender: str = ""
    receiver: Optional[str] = None
    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        return {
            "id": self.id,
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


@dataclass
class SwarmResult:
    """
    Result of swarm execution.

    Attributes:
        id: Unique identifier
        topology: Swarm topology
        mode: Execution mode used
        outputs: Agent outputs
        messages: Communication messages
        duration: Execution duration
        success: Whether execution succeeded
        fused: ResultFusion output (smart mode only)
        decomposition: Task decomposition used (smart mode only)
        feedback_loop: Feedback loop result (feedback mode only)
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    topology: SwarmTopology = SwarmTopology.STAR
    mode: ExecutionMode = ExecutionMode.RAW
    outputs: dict[str, Any] = field(default_factory=dict)
    messages: list[SwarmMessage] = field(default_factory=list)
    duration: float = 0.0
    success: bool = True
    fused: Optional[FusedResult] = None
    decomposition: Optional[Decomposition] = None
    feedback_loop: Optional[LoopResult] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict."""
        d: dict[str, Any] = {
            "id": self.id,
            "topology": self.topology.value,
            "mode": self.mode.value,
            "outputs": self.outputs,
            "messages": [m.to_dict() for m in self.messages],
            "duration": f"{self.duration:.2f}s",
            "success": self.success,
        }
        if self.fused:
            d["fused"] = {
                "action": self.fused.action,
                "confidence": self.fused.confidence,
                "reason": self.fused.reason,
            }
        if self.decomposition:
            d["decomposition"] = {
                "sub_tasks": [st.to_dict() for st in self.decomposition.sub_tasks],
                "total_steps": self.decomposition.total_steps,
            }
        if self.feedback_loop:
            d["feedback_loop"] = {
                "attempts": self.feedback_loop.attempts,
                "best_score": self.feedback_loop.best_score,
                "converged": self.feedback_loop.converged,
                "duration": f"{self.feedback_loop.duration:.2f}s",
            }
        return d


class SmartSwarmCoordinator:
    """
    v1.9.4: Multi-agent coordination with intelligent orchestration.

    Upgrades the coordinator with:
    - TaskDecomposer: LLM-driven sub-task DAG decomposition
    - ResultFusion: LLM-as-Judge aggregation with confidence scoring
    - EvalFeedbackLoop: execute → evaluate → retry → converge

    Usage:
        coordinator = SmartSwarmCoordinator(topology=SwarmTopology.MESH)
        coordinator.register(agent1)
        coordinator.register(agent2)

        # Smart mode with decomposition + fusion
        result = await coordinator.smart_execute("complex research task")

        # Feedback mode with evaluation retry loop
        result = await coordinator.execute_with_feedback(
            task, expected_output, scorer
        )
    """

    def __init__(
        self,
        topology: SwarmTopology = SwarmTopology.STAR,
        max_rounds: int = 10,
        execution_mode: ExecutionMode = ExecutionMode.SMART,
        decomposer: TaskDecomposer | None = None,
        fusion: ResultFusion | None = None,
        feedback_loop: EvalFeedbackLoop | None = None,
        sandbox: CodeSandbox | None = None,
        hitl_manager: HITLManager | None = None,
        monitor: AgentMonitor | None = None,
        trace_collector: TraceCollector | None = None,
        memory: AgentMemory | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_router: ToolRouter | None = None,
        tool_executor: ToolExecutor | None = None,
        guard: GuardPipeline | None = None,
    ):
        """
        Initialize smart swarm coordinator.

        Args:
            topology: Swarm topology
            max_rounds: Maximum communication rounds
            execution_mode: Default execution mode
            decomposer: TaskDecomposer instance (created if None)
            fusion: ResultFusion instance (created if None)
            feedback_loop: EvalFeedbackLoop instance (created if None)
            sandbox: CodeSandbox instance for code execution (created if None)
            hitl_manager: HITLManager for human-in-the-loop (created if None)
            monitor: AgentMonitor for quality gating (created if None)
            trace_collector: TraceCollector for execution traces (created if None)
            memory: AgentMemory for layered memory (created if None)
            tool_registry: ToolRegistry for tool catalog (created if None)
            tool_router: ToolRouter for intelligent tool selection (created if None)
            tool_executor: ToolExecutor for safe tool execution (created if None)
            guard: GuardPipeline for input/output safety filtering (created if None)
        """
        self.topology = topology
        self.max_rounds = max_rounds
        self.execution_mode = execution_mode
        self._agents: dict[str, Agent[Any, Any]] = {}
        self._message_queue: list[SwarmMessage] = []

        self.decomposer = decomposer or TaskDecomposer()
        self.fusion = fusion or ResultFusion()
        self.feedback = feedback_loop or EvalFeedbackLoop()
        self.sandbox = sandbox or CodeSandbox()
        self.hitl = hitl_manager or HITLManager()
        self.monitor = monitor or AgentMonitor()
        self.tracer = trace_collector or TraceCollector()
        self.memory = memory or AgentMemory()
        self.tool_registry = tool_registry or ToolRegistry()
        self.tool_router = tool_router or ToolRouter(self.tool_registry)
        self.tool_executor = tool_executor or ToolExecutor(self.tool_registry)
        self.guard = guard or create_strict_guard()

        # Original topology methods bound for backward compatibility
        self._topo_handlers = {
            SwarmTopology.STAR: self._execute_star,
            SwarmTopology.RING: self._execute_ring,
            SwarmTopology.MESH: self._execute_mesh,
            SwarmTopology.TREE: self._execute_tree,
        }

    # ── Agent management ──────────────────────────────────────────

    def register(self, agent: Agent[Any, Any]) -> None:
        self._agents[agent.name] = agent

    def unregister(self, agent_name: str) -> bool:
        if agent_name in self._agents:
            del self._agents[agent_name]
            return True
        return False

    def get_agent(self, agent_name: str) -> Optional[Agent[Any, Any]]:
        return self._agents.get(agent_name)

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())

    # ── Execution API ─────────────────────────────────────────────

    async def execute(
        self,
        task: Any,
        mode: ExecutionMode | None = None,
        **metadata,
    ) -> SwarmResult:
        """Execute a task. Delegates to smart_execute or raw topology."""
        mode = mode or self.execution_mode
        if mode == ExecutionMode.SMART:
            return await self.smart_execute(task, **metadata)
        return await self._execute_raw(task, **metadata)

    async def smart_execute(
        self,
        task: Any,
        _trace: ExecutionTrace | None = None,
        **metadata,
    ) -> SwarmResult:
        """Smart execution: decompose → execute DAG → fuse.

        Uses ExecutionTrace for observability when tracer is available.

        Args:
            task: Task description (string or structured)
            _trace: Optional trace to attach (auto-created if self.tracer exists)
            **metadata: Additional metadata

        Returns:
            SwarmResult with fused output and decomposition trace
        """
        start_time = time.time()
        task_str = str(task)

        # Step 0: Security guard — input filtering
        guard_result = self.guard.process_input(task_str)
        if guard_result.blocked:
            result = SwarmResult(
                topology=self.topology,
                mode=ExecutionMode.SMART,
                output=f"[BLOCKED] Input rejected by guard: {guard_result.blocked_by}. Reason: {', '.join(guard_result.warnings)}",
                completed=False,
            )
            return result
        if guard_result.final_content != task_str:
            task_str = guard_result.final_content  # PII-redacted version

        # Trace setup
        trace = _trace
        if trace is None and self.tracer is not None:
            trace = ExecutionTrace(task_name=task_str[:80])
            self.tracer.add(trace)

        if trace:
            root = trace.start_span(TraceEvent.TASK_START, name="smart_execute", data={"task": task_str})

        result = SwarmResult(
            topology=self.topology,
            mode=ExecutionMode.SMART,
        )

        agent_names = self.list_agents()

        # Step 0: Load memory context
        self.memory.set_task(task_str)
        memory_context = self.memory.get_context(query=task_str) if self.memory else ""

        # Step 1: Decompose
        if trace:
            dspan = trace.start_span(TraceEvent.DECOMPOSE, name="decompose")
        decomp = self.decomposer.decompose(task_str, agents=agent_names)
        result.decomposition = decomp
        if trace and dspan:
            trace.end_span(dspan.id, status="done", data={"sub_tasks": len(decomp.sub_tasks)})

        # Step 2: Execute sub-tasks in dependency order
        sub_outputs: dict[str, dict[str, Any]] = {}
        completed: set[str] = set()

        for _round in range(self.max_rounds):
            ready = [
                st for st in decomp.sub_tasks
                if st.status == "pending"
                and all(dep in completed for dep in st.depends_on)
            ]
            if not ready:
                break

            for st in ready:
                st.status = "running"

                if trace:
                    stspan = trace.start_span(TraceEvent.SUBTASK_START, name=st.description[:60], data={"id": st.id})

                # Build context from dependencies
                context = task_str
                if memory_context:
                    context = f"{memory_context}\n\n[Current Task]\n{task_str}"
                if st.depends_on:
                    dep_contexts = []
                    for dep_id in st.depends_on:
                        dep_outputs = sub_outputs.get(dep_id, {})
                        for name, out in dep_outputs.items():
                            dep_contexts.append(f"[{name}]: {str(out)[:300]}")
                    if dep_contexts:
                        context = f"{context}\n\nPrevious results:\n" + "\n".join(dep_contexts)

                # Execute with all agents on this sub-task
                topo_result = await self._execute_raw(context, **metadata)
                sub_outputs[st.id] = topo_result.outputs
                st.output = topo_result.outputs
                st.status = "done" if topo_result.success else "failed"
                completed.add(st.id)

                # Store sub-task result in memory
                self.memory.remember(
                    content=f"SubTask [{st.description}]: {json.dumps(topo_result.outputs, default=str)[:500]}",
                    role="assistant",
                    importance=0.6,
                    metadata={"subtask_id": st.id, "status": st.status},
                )

                if trace and stspan:
                    st_status = "done" if st.status == "done" else "failed"
                    trace.end_span(stspan.id, status=st_status, data={"output_keys": list(topo_result.outputs.keys())})

        # Step 3: Fuse results from final sub-tasks
        if trace:
            fspan = trace.start_span(TraceEvent.FUSE, name="fuse_results")

        final_subtasks = [
            st for st in decomp.sub_tasks
            if st.status == "done" and st.id not in {
                s.id for s in decomp.sub_tasks
                if any(d == st.id for d in s.depends_on)
            }
        ]
        if final_subtasks:
            all_final: dict[str, Any] = {}
            for st in final_subtasks:
                if st.output:
                    all_final.update(st.output)
            if all_final:
                fused = self.fusion.fuse(task_str, all_final)
                result.fused = fused
                result.outputs = all_final
                result.success = fused.confidence >= 0.3

        if not result.outputs and sub_outputs:
            all_outputs: dict[str, Any] = {}
            for st_outputs in sub_outputs.values():
                all_outputs.update(st_outputs)
            if all_outputs:
                fused = self.fusion.fuse(task_str, all_outputs)
                result.fused = fused
                result.outputs = all_outputs
                result.success = fused.confidence >= 0.3

        if trace and fspan:
            trace.end_span(fspan.id, status="done", data={"confidence": result.fused.confidence if result.fused else 0})

        result.duration = time.time() - start_time

        if trace and root:
            trace.end_span(root.id, status="done" if result.success else "failed")

        # Output guard — filter agent output before returning to user
        if result.outputs:
            guarded_outputs: dict[str, Any] = {}
            for key, value in result.outputs.items():
                output_str = str(value)
                output_guard = self.guard.process_output(output_str)
                if output_guard.blocked:
                    guarded_outputs[key] = f"[BLOCKED by guard: {output_guard.blocked_by}]"
                elif output_guard.final_content != output_str:
                    guarded_outputs[key] = output_guard.final_content
                else:
                    guarded_outputs[key] = value
            result.outputs = guarded_outputs

        return result

    async def execute_with_feedback(
        self,
        task: Any,
        expected_output: str = "",
        scoring_strategy: str = "general",
        retry_config: RetryConfig | None = None,
        **metadata,
    ) -> SwarmResult:
        """Execution with eval-driven feedback loop.

        Args:
            task: Task description
            expected_output: Reference for scoring
            scoring_strategy: Scoring strategy (qa/code/summary/translation)
            retry_config: Retry configuration
            **metadata: Additional metadata

        Returns:
            SwarmResult with feedback_loop trace
        """
        start_time = time.time()
        result = SwarmResult(
            topology=self.topology,
            mode=ExecutionMode.FEEDBACK,
        )

        task_str = str(task)

        # Build executor that uses smart_execute
        async def executor(t: str) -> Any:
            r = await self.smart_execute(t, **metadata)
            fused = r.fused
            if fused and fused.merged:
                content = fused.merged
                # If it's a dict with agent outputs, stringify
                if isinstance(content, dict):
                    parts = []
                    for k, v in content.items():
                        if v and not isinstance(v, dict):
                            parts.append(str(v))
                    return "\n".join(parts) if parts else str(content)
                return str(content)
            return str(r.outputs)

        # Wire scorer if available
        scorer = None
        try:
            from agentos.evaluation.scorers import CompositeScorerV2
            scorer = CompositeScorerV2()
        except Exception:
            pass

        feedback = EvalFeedbackLoop(
            scorer=scorer,
            config=retry_config or RetryConfig(max_retries=3),
        )

        loop_result = await feedback.run(
            task=task_str,
            executor=executor,
            expected=expected_output,
            strategy=scoring_strategy,
        )

        result.feedback_loop = loop_result
        result.outputs = {"final": str(loop_result.final_output) if loop_result.final_output else ""}
        result.success = loop_result.converged
        result.duration = time.time() - start_time
        return result

    # ── Raw topology execution (backward compatible) ──────────────

    async def _execute_raw(
        self,
        task: Any,
        **metadata,
    ) -> SwarmResult:
        """Original topology-only execution."""
        handler = self._topo_handlers.get(self.topology)
        if handler is None:
            raise ValueError(f"Unknown topology: {self.topology}")
        return await handler(task, metadata)

    # ── Star Topology ─────────────────────────────────────────────

    async def _execute_star(
        self,
        task: Any,
        metadata: dict[str, Any],
    ) -> SwarmResult:
        result = SwarmResult(topology=SwarmTopology.STAR, mode=ExecutionMode.RAW)
        for agent_name, agent in self._agents.items():
            try:
                message = SwarmMessage(
                    sender="coordinator",
                    receiver=agent_name,
                    content=task,
                    metadata=metadata,
                )
                result.messages.append(message)
                output = await agent.invoke(task, **metadata)
                result.outputs[agent_name] = output
                response = SwarmMessage(
                    sender=agent_name,
                    receiver="coordinator",
                    content=output,
                )
                result.messages.append(response)
            except Exception as e:
                result.outputs[agent_name] = {"error": str(e)}
                result.success = False
        return result

    # ── Ring Topology ─────────────────────────────────────────────

    async def _execute_ring(
        self,
        task: Any,
        metadata: dict[str, Any],
    ) -> SwarmResult:
        result = SwarmResult(topology=SwarmTopology.RING, mode=ExecutionMode.RAW)
        agent_names = list(self._agents.keys())
        if not agent_names:
            return result

        current_input = task
        for i, agent_name in enumerate(agent_names):
            agent = self._agents[agent_name]
            next_agent = agent_names[(i + 1) % len(agent_names)]
            try:
                output = await agent.invoke(current_input, **metadata)
                result.outputs[agent_name] = output
                message = SwarmMessage(
                    sender=agent_name,
                    receiver=next_agent,
                    content=output,
                )
                result.messages.append(message)
                current_input = output
            except Exception as e:
                result.outputs[agent_name] = {"error": str(e)}
                result.success = False
        return result

    # ── Mesh Topology ─────────────────────────────────────────────

    async def _execute_mesh(
        self,
        task: Any,
        metadata: dict[str, Any],
    ) -> SwarmResult:
        result = SwarmResult(topology=SwarmTopology.MESH, mode=ExecutionMode.RAW)
        tasks_ = []
        for agent_name, agent in self._agents.items():
            tasks_.append(self._execute_agent_mesh(agent, task, metadata, result))
        await asyncio.gather(*tasks_, return_exceptions=True)
        for sender_name, output in result.outputs.items():
            for receiver_name in self._agents.keys():
                if sender_name != receiver_name:
                    message = SwarmMessage(
                        sender=sender_name,
                        receiver=receiver_name,
                        content=output,
                    )
                    result.messages.append(message)
        return result

    async def _execute_agent_mesh(
        self,
        agent: Agent[Any, Any],
        task: Any,
        metadata: dict[str, Any],
        result: SwarmResult,
    ) -> None:
        try:
            output = await agent.invoke(task, **metadata)
            result.outputs[agent.name] = output
        except Exception as e:
            result.outputs[agent.name] = {"error": str(e)}
            result.success = False

    # ── Tree Topology ─────────────────────────────────────────────

    async def _execute_tree(
        self,
        task: Any,
        metadata: dict[str, Any],
    ) -> SwarmResult:
        result = SwarmResult(topology=SwarmTopology.TREE, mode=ExecutionMode.RAW)
        agent_names = list(self._agents.keys())
        if not agent_names:
            return result

        root_name = agent_names[0]
        root_agent = self._agents[root_name]
        try:
            root_output = await root_agent.invoke(task, **metadata)
            result.outputs[root_name] = root_output
        except Exception as e:
            result.outputs[root_name] = {"error": str(e)}
            result.success = False
            return result

        children = agent_names[1:]
        for child_name in children:
            child_agent = self._agents[child_name]
            message = SwarmMessage(
                sender=root_name,
                receiver=child_name,
                content=root_output,
            )
            result.messages.append(message)
            try:
                child_output = await child_agent.invoke(root_output, **metadata)
                result.outputs[child_name] = child_output
                response = SwarmMessage(
                    sender=child_name,
                    receiver=root_name,
                    content=child_output,
                )
                result.messages.append(response)
            except Exception as e:
                result.outputs[child_name] = {"error": str(e)}
                result.success = False
        return result

    # ── Messaging ─────────────────────────────────────────────────

    def send_message(
        self,
        sender: str,
        receiver: Optional[str],
        content: Any,
        **metadata,
    ) -> SwarmMessage:
        message = SwarmMessage(
            sender=sender,
            receiver=receiver,
            content=content,
            metadata=metadata,
        )
        self._message_queue.append(message)
        return message

    def get_messages(
        self,
        receiver: Optional[str] = None,
    ) -> list[SwarmMessage]:
        if receiver:
            return [
                m for m in self._message_queue
                if m.receiver == receiver or m.receiver is None
            ]
        return self._message_queue.copy()

    def clear_messages(self) -> None:
        self._message_queue.clear()

    # ── Code Sandbox Execution (v1.9.5) ───────────────────────────

    async def execute_code(
        self,
        code: str,
        func_name: str = "",
        test_cases: list[TestCase] | None = None,
        setup_code: str = "",
        sandbox: CodeSandbox | None = None,
        max_retries: int = 3,
        code_generator: Callable[[str, list[str]], str] | None = None,
    ) -> SandboxResult:
        """Execute code in sandbox with test cases and feedback-driven retry.

        Supports code generation: if code_generator is provided and initial run
        fails, it will use the feedback extractor to guide re-generation.

        Args:
            code: Code to execute (or initial code if using generator)
            func_name: Function name to test
            test_cases: Test cases for validation
            setup_code: Setup code (imports, fixtures)
            sandbox: Custom sandbox instance
            max_retries: Max retry attempts with code generation
            code_generator: Callable(spec, feedback_suggestions) → new_code

        Returns:
            SandboxResult with execution details and test outcomes
        """
        sb = sandbox or self.sandbox

        result = sb.run(code, func_name, test_cases, setup_code)

        # If initial run succeeded, we're done
        if result.all_passed:
            return result

        # Feedback-driven retry loop
        for attempt in range(1, max_retries + 1):
            if not code_generator:
                break

            suggestions = CodeFeedbackExtractor.extract(result)
            if not suggestions:
                break

            # Generate improved code
            spec = f"Function: {func_name}, Test cases: {len(test_cases or [])}"
            try:
                new_code = code_generator(spec, suggestions)
            except Exception:
                break

            if not new_code or new_code == code:
                break

            code = new_code
            result = sb.run(code, func_name, test_cases, setup_code)

            if result.all_passed:
                break

            if attempt == max_retries:
                break  # Don't overwrite last result

        return result

    # ── HITL-Enhanced Execution (v1.9.5) ──────────────────────────

    async def smart_execute_with_hitl(
        self,
        task: Any,
        hitl: HITLManager | None = None,
        **metadata,
    ) -> SwarmResult:
        """Smart execution with human-in-the-loop breakpoints.

        Same as smart_execute but pauses at configurable checkpoints:
        - Before each sub-task (if hitl.break_on_every_task)
        - On sub-task failure (if hitl.break_on_failure)
        - On low-confidence fusion (if config threshold met)

        Args:
            task: Task description
            hitl: HITLManager instance (uses self.hitl if None)
            **metadata: Additional metadata

        Returns:
            SwarmResult with fused output
        """
        hitl_mgr = hitl or self.hitl
        start_time = time.time()
        result = SwarmResult(
            topology=self.topology,
            mode=ExecutionMode.SMART,
        )

        task_str = str(task)
        agent_names = self.list_agents()

        # Step 1: Decompose
        decomp = self.decomposer.decompose(task_str, agents=agent_names)
        result.decomposition = decomp

        # Step 2: Execute sub-tasks with HITL gates
        sub_outputs: dict[str, dict[str, Any]] = {}
        completed: set[str] = set()
        aborted = False

        for _round in range(self.max_rounds):
            if aborted:
                break

            ready = [
                st for st in decomp.sub_tasks
                if st.status == "pending"
                and all(dep in completed for dep in st.depends_on)
            ]
            if not ready:
                break

            for st in ready:
                # HITL: check before executing sub-task
                if hitl_mgr.config.break_on_every_task:
                    decision, feedback = await hitl_mgr.request_decision(
                        bp_type=BreakpointType.BEFORE_TASK,
                        task_id=st.id,
                        message=f"Execute sub-task: {st.description}?",
                        context={"task": task_str, "sub_task": st.description},
                        options=["approve", "abort", "modify"],
                    )
                    if decision == HumanDecision.ABORT:
                        aborted = True
                        break
                    if decision == HumanDecision.MODIFY and feedback:
                        st.description = f"{st.description} [modified: {feedback}]"

                st.status = "running"

                # Build context from dependencies
                context = task_str
                if st.depends_on:
                    dep_contexts = []
                    for dep_id in st.depends_on:
                        dep_outputs = sub_outputs.get(dep_id, {})
                        for name, out in dep_outputs.items():
                            dep_contexts.append(f"[{name}]: {str(out)[:300]}")
                    if dep_contexts:
                        context = f"{task_str}\n\nPrevious results:\n" + "\n".join(dep_contexts)

                # Execute
                topo_result = await self._execute_raw(context, **metadata)
                sub_outputs[st.id] = topo_result.outputs
                st.output = topo_result.outputs
                st.status = "done" if topo_result.success else "failed"
                completed.add(st.id)

                # HITL: check on failure
                if not topo_result.success:
                    decision, feedback = await hitl_mgr.should_break_on_failure(
                        task_id=st.id,
                        error=topo_result.error or "Unknown error",
                        attempt=1,
                    )
                    if decision == HumanDecision.ABORT:
                        aborted = True
                        break
                    if decision == HumanDecision.MODIFY and feedback:
                        st.description = f"{st.description} [retry with: {feedback}]"
                        st.status = "pending"  # Re-queue for retry
                        completed.discard(st.id)
                        del sub_outputs[st.id]

        if aborted:
            result.success = False
            result.error = "Aborted by human"
            return result

        # Step 3: Fuse results
        final_subtasks = [
            st for st in decomp.sub_tasks
            if st.status == "done" and st.id not in {
                s.id for s in decomp.sub_tasks
                if any(d == st.id for d in s.depends_on)
            }
        ]
        if final_subtasks:
            all_final: dict[str, Any] = {}
            for st in final_subtasks:
                if st.output:
                    all_final.update(st.output)
            if all_final:
                fused = self.fusion.fuse(task_str, all_final)
                result.fused = fused
                result.outputs = all_final

                # HITL: check low confidence
                if fused.confidence < hitl_mgr.config.break_on_low_confidence:
                    decision, feedback = await hitl_mgr.should_break_on_result(
                        task_id="final",
                        output=all_final,
                        confidence=fused.confidence,
                    )
                    if decision == HumanDecision.ABORT:
                        result.success = False
                        result.error = "Aborted by human at final result"
                        return result
                    if decision == HumanDecision.REJECT:
                        result.success = False
                        result.error = f"Rejected: {feedback}"
                        return result

                result.success = fused.confidence >= 0.3

        if not result.outputs and sub_outputs:
            all_outputs: dict[str, Any] = {}
            for st_outputs in sub_outputs.values():
                all_outputs.update(st_outputs)
            if all_outputs:
                fused = self.fusion.fuse(task_str, all_outputs)
                result.fused = fused
                result.outputs = all_outputs
                result.success = fused.confidence >= 0.3

        result.duration = time.time() - start_time
        return result

    # ── Monitored Execution (v1.9.6) ─────────────────────────────

    async def monitor_execute(
        self,
        task: Any,
        quality_gates: list[QualityGate] | None = None,
        fallback_fn: Callable[[], Any] | None = None,
        **metadata,
    ) -> tuple[Any, MonitorReport]:
        """Execute with automatic quality gating.

        Runs smart_execute through the AgentMonitor pipeline. If gates fail,
        automatically retries or falls back based on gate configuration.

        Args:
            task: Task description
            quality_gates: Custom quality gates (uses monitor defaults if None)
            fallback_fn: Fallback function if all gates fail
            **metadata: Additional metadata

        Returns:
            Tuple of (final_output, MonitorReport)
        """
        # Configure monitor with custom gates if provided
        monitor = self.monitor
        if quality_gates:
            monitor = AgentMonitor(
                max_retries=self.monitor.max_retries,
                default_fallback=self.monitor.default_fallback,
            )
            monitor.add_gates(quality_gates)
        elif not self.monitor._gates:
            # Default gates if none configured
            monitor = AgentMonitor()
            monitor.add_gates([
                output_not_empty(),
                no_error_output(),
            ])

        # Track latency for latency gates
        start = time.time()

        async def execute_fn() -> Any:
            result = await self.smart_execute(task, **metadata)
            fused = result.fused
            if fused and fused.merged:
                return fused.merged
            return result.outputs

        output, report = await monitor.monitor_execution(
            task_fn=execute_fn,
            task_name=str(task)[:80],
            context={"_latency_ms": 0},
            fallback_fn=fallback_fn,
        )

        # Inject actual latency
        elapsed = (time.time() - start) * 1000
        for gate in report.gates:
            gate.data["_latency_ms"] = elapsed

        return output, report

    # ── Tool Registry Convenience Methods ─────────────────────────

    def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable,
        category: ToolCategory = ToolCategory.CUSTOM,
        params: list[ToolParam] | None = None,
        capabilities: list[str] | None = None,
        tags: list[str] | None = None,
        is_destructive: bool = False,
        rate_limit: int = 0,
        **kwargs,
    ) -> ToolSchema:
        """Register a tool in the coordinator's tool registry."""
        tool = create_tool(
            name=name, description=description, handler=handler,
            category=category, params=params or [],
            capabilities=capabilities or [], tags=tags or [],
            is_destructive=is_destructive, rate_limit=rate_limit, **kwargs,
        )
        return self.tool_registry.register(tool)

    def find_tool(self, query: str, top_k: int = 5) -> list[tuple[ToolSchema, float]]:
        """Search for tools matching a natural language query."""
        return self.tool_registry.search(query, top_k=top_k)

    def route_tool(self, task: str, **ctx_kwargs) -> RoutingDecision:
        """Route a task to the best matching tool."""
        context = RoutingContext(task=task, **ctx_kwargs)
        return self.tool_router.route(context)

    def execute_tool(self, tool_name: str, params: dict[str, Any] | None = None, force: bool = False) -> Any:
        """Execute a registered tool safely."""
        return self.tool_executor.execute(tool_name, params, force=force)


# ── Backward-compatible alias ─────────────────────────────────────
SwarmCoordinator = SmartSwarmCoordinator
