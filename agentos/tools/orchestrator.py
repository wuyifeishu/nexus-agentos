"""
AgentOS v1.1.7 — 工具链编排引擎（Checkpoint/恢复）。
基因来源: Airflow DAG + LangChain Tool Composition

支持:
- 顺序链 (chain): 工具A → 工具B → 工具C
- 并行分支 (parallel): A + B 同时 → C
- 条件执行 (conditional): if X then A else B
- 重试策略 (retry): 指数退避 / 固定间隔
- 超时控制 (timeout): 单工具 / 全链
- Checkpoint/恢复: 长时间DAG断点保存与续跑
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine


# ── Core Types ──────────────────────────────────

class NodeState(str, Enum):

    """DAG 节点状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class NodeResult:
    """DAG 节点执行结果。"""
    node_id: str
    state: NodeState
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    retries: int = 0


@dataclass
class DAGResult:
    """DAG 执行结果。"""
    nodes: dict[str, NodeResult]
    final_output: Any = None
    total_duration_ms: float = 0.0
    success: bool = False
    error: str | None = None


@dataclass
class RetryPolicy:
    """重试策略类。"""
    max_retries: int = 3
    base_delay: float = 1.0      # seconds
    max_delay: float = 30.0      # seconds
    backoff: str = "exponential" # exponential | fixed | linear
    retry_on: tuple = (Exception,)


# ── DAG Node Types ─────────────────────────────

@dataclass
class ToolNode:
    """工具执行节点。"""
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # upstream node IDs
    timeout: float = 60.0
    retry: RetryPolicy | None = None

    # Optional transform: map upstream outputs → tool_args
    input_transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass
class ConditionNode:
    """条件分支节点。"""
    condition: Callable[[dict[str, Any]], str]  # returns target node_id
    depends_on: list[str] = field(default_factory=list)


@dataclass
class ParallelGroup:
    """并行执行组 — 所有节点同时执行。"""
    node_ids: list[str]
    depends_on: list[str] = field(default_factory=list)
    max_concurrency: int = 5


@dataclass
class DAGSpec:
    """DAG编排规格。"""
    name: str
    nodes: dict[str, ToolNode] = field(default_factory=dict)
    parallels: list[ParallelGroup] = field(default_factory=list)
    conditions: dict[str, ConditionNode] = field(default_factory=dict)
    entry: list[str] = field(default_factory=list)
    global_timeout: float = 300.0


# ── Checkpoint Data (v1.1.7) ──────────────────

@dataclass
class CheckpointData:
    """DAG执行快照，支持断点续跑。"""

    dag_name: str
    completed_nodes: dict[str, dict] = field(default_factory=dict)
    pending_nodes: list[str] = field(default_factory=list)
    timestamp: float = 0.0
    version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "dag_name": self.dag_name,
            "completed_nodes": self.completed_nodes,
            "pending_nodes": self.pending_nodes,
            "timestamp": self.timestamp,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CheckpointData":
        return cls(
            dag_name=data.get("dag_name", ""),
            completed_nodes=data.get("completed_nodes", {}),
            pending_nodes=data.get("pending_nodes", []),
            timestamp=data.get("timestamp", 0.0),
            version=data.get("version", "1.0"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "CheckpointData":
        return cls.from_dict(json.loads(json_str))


# ── Orchestrator Engine ────────────────────────

class ToolOrchestrator:
    """
    工具链编排引擎 — DAG执行、并行调度、条件分支、Checkpoint恢复。
    """

    def __init__(self, tool_registry: Any):
        self.registry = tool_registry
        self._results: dict[str, NodeResult] = {}
        self._aborted: bool = False

    async def execute(self, dag: DAGSpec) -> DAGResult:
        """执行完整DAG。若从checkpoint恢复，会跳过已完成节点。"""
        was_restored = bool(self._results)
        if not was_restored:
            self._results = {}
        self._aborted = False
        start = time.time()

        try:
            await asyncio.wait_for(
                self._execute_entry(dag),
                timeout=dag.global_timeout,
            )
        except asyncio.TimeoutError:
            return DAGResult(
                nodes=self._results,
                total_duration_ms=(time.time() - start) * 1000,
                error=f"DAG timeout ({dag.global_timeout}s)",
            )

        duration_ms = (time.time() - start) * 1000
        success = all(
            r.state == NodeState.SUCCESS
            for r in self._results.values()
            if not self._is_conditional(dag, r.node_id)
        )

        # Final output = last entry node (or last successful)
        last = None
        for nid in reversed(dag.entry):
            if nid in self._results and self._results[nid].state == NodeState.SUCCESS:
                last = self._results[nid].output
                break

        return DAGResult(
            nodes=self._results,
            final_output=last,
            total_duration_ms=duration_ms,
            success=success,
        )

    async def _execute_entry(self, dag: DAGSpec):
        """递归执行入口节点。"""
        pending = set(dag.entry or dag.nodes.keys())
        # v1.1.7: 跳过checkpoint恢复后已完成的节点，并发现其下游节点
        completed = {nid for nid in pending if nid in self._results and self._results[nid].state == NodeState.SUCCESS}
        pending -= completed
        for nid in completed:
            for other_nid, other_node in dag.nodes.items():
                if nid in other_node.depends_on and other_nid not in pending and other_nid not in self._results:
                    pending.add(other_nid)

        while pending:
            # Find nodes ready to execute (all deps satisfied)
            ready = []
            for nid in list(pending):
                node = dag.nodes.get(nid)
                if not node:
                    continue
                if self._deps_ready(node.depends_on):
                    ready.append(nid)

            if not ready:
                # Check for deadlocks
                stuck = [nid for nid in pending if not self._can_proceed(dag, nid)]
                if stuck:
                    for nid in stuck:
                        self._results[nid] = NodeResult(
                            node_id=nid, state=NodeState.FAILED,
                            error="Deadlock: dependencies not met",
                        )
                    break
                await asyncio.sleep(0.01)
                continue

            # Execute ready nodes (parallel groups first)
            parallel_nodes = []
            sequential_nodes = []
            for nid in ready:
                if any(nid in pg.node_ids for pg in dag.parallels):
                    parallel_nodes.append(nid)
                else:
                    sequential_nodes.append(nid)

            # Run sequential nodes concurrently
            tasks = []
            for nid in sequential_nodes:
                tasks.append(self._run_node(dag, nid))
            if tasks:
                await asyncio.gather(*tasks)

            # Run parallel groups
            for pg in dag.parallels:
                group_ready = [nid for nid in pg.node_ids if nid in ready]
                if group_ready:
                    sem = asyncio.Semaphore(pg.max_concurrency)
                    async def bounded(nid):
                        async with sem:
                            await self._run_node(dag, nid)
                    await asyncio.gather(*[bounded(nid) for nid in group_ready])

            pending -= set(ready)

            # v1.1.7: 发现已完成节点的下游节点（支持checkpoint恢复 & 多节点链）
            for nid in list(ready):
                for other_nid, other_node in dag.nodes.items():
                    if nid in other_node.depends_on and other_nid not in pending and other_nid not in self._results:
                        pending.add(other_nid)

            # Process conditions
            for cid, cond in dag.conditions.items():
                if self._deps_ready(cond.depends_on):
                    upstream = {nid: self._results.get(nid) for nid in cond.depends_on}
                    target = cond.condition(upstream)
                    if target and target in dag.nodes:
                        pending.add(target)

    async def _run_node(self, dag: DAGSpec, nid: str) -> NodeResult:
        """执行单个节点（带重试）。"""
        node = dag.nodes.get(nid)
        if not node:
            return NodeResult(nid, NodeState.FAILED, error=f"Unknown node: {nid}")

        # Gather upstream outputs
        upstream = {}
        for dep in node.depends_on:
            dep_result = self._results.get(dep)
            if dep_result and dep_result.state == NodeState.SUCCESS:
                upstream[dep] = dep_result.output

        # Transform inputs if needed
        args = dict(node.tool_args)
        if node.input_transform and upstream:
            try:
                transformed = node.input_transform(upstream)
                args.update(transformed)
            except Exception as e:
                result = NodeResult(nid, NodeState.FAILED, error=f"Input transform error: {e}")
                self._results[nid] = result
                return result

        # Execute with retry
        retry_policy = node.retry or RetryPolicy(max_retries=0)
        last_error = None

        for attempt in range(retry_policy.max_retries + 1):
            try:
                step_start = time.time()
                output = await asyncio.wait_for(
                    self._execute_tool(node.tool_name, args, upstream),
                    timeout=node.timeout,
                )
                duration_ms = (time.time() - step_start) * 1000
                result = NodeResult(
                    node_id=nid, state=NodeState.SUCCESS,
                    output=output, duration_ms=duration_ms,
                    retries=attempt,
                )
                self._results[nid] = result
                return result
            except asyncio.TimeoutError:
                last_error = f"Tool timeout ({node.timeout}s)"
                result = NodeResult(nid, NodeState.TIMEOUT, error=last_error, retries=attempt)
            except Exception as e:
                last_error = str(e)
                if attempt < retry_policy.max_retries:
                    delay = self._calc_retry_delay(retry_policy, attempt)
                    await asyncio.sleep(delay)

        result = NodeResult(nid, NodeState.FAILED, error=last_error, retries=retry_policy.max_retries)
        self._results[nid] = result
        return result

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict,
        upstream: dict[str, Any],
    ) -> Any:
        """执行具体工具。"""
        tool = self.registry.get(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        # Inject upstream results into args
        full_args = {**args}
        for dep_id, dep_output in upstream.items():
            full_args[f"_{dep_id}"] = dep_output
        full_args["_upstream"] = upstream

        if asyncio.iscoroutinefunction(tool.execute):
            return await tool.execute(**full_args)
        else:
            return tool.execute(**full_args)

    def _deps_ready(self, deps: list[str]) -> bool:
        """所有依赖是否成功完成。"""
        for dep in deps:
            r = self._results.get(dep)
            if not r or r.state != NodeState.SUCCESS:
                return False
        return True

    def _can_proceed(self, dag: DAGSpec, nid: str) -> bool:
        """节点是否有可能继续执行（未永久失败）。"""
        node = dag.nodes.get(nid)
        if not node:
            return False
        for dep in node.depends_on:
            r = self._results.get(dep)
            if r and r.state in (NodeState.FAILED, NodeState.TIMEOUT):
                return False
        return True

    def _is_conditional(self, dag: DAGSpec, nid: str) -> bool:
        return nid in dag.conditions

    def _calc_retry_delay(self, policy: RetryPolicy, attempt: int) -> float:
        if policy.backoff == "fixed":
            return policy.base_delay
        elif policy.backoff == "linear":
            return min(policy.base_delay * (attempt + 1), policy.max_delay)
        else:  # exponential
            return min(policy.base_delay * (2 ** attempt), policy.max_delay)

    @property
    def results(self) -> dict[str, NodeResult]:
        return dict(self._results)

    # ── Checkpoint / Restore (v1.1.7) ──────────────

    def checkpoint(self, dag: DAGSpec) -> CheckpointData:
        """保存当前DAG执行进度为快照。"""
        completed = {}
        for nid, result in self._results.items():
            completed[nid] = {
                "node_id": result.node_id,
                "state": result.state.value,
                "output": result.output,
                "error": result.error,
                "duration_ms": result.duration_ms,
                "retries": result.retries,
            }
        # 未完成的节点（在dag中但不在results里）
        pending = [nid for nid in dag.nodes if nid not in self._results]
        return CheckpointData(
            dag_name=dag.name,
            completed_nodes=completed,
            pending_nodes=pending,
            timestamp=time.time(),
        )

    def restore_from_checkpoint(self, dag: DAGSpec, cp: CheckpointData) -> dict[str, NodeResult]:
        """从快照恢复已完成的节点状态，返回可继续执行的results基础。"""
        restored = {}
        for nid, data in cp.completed_nodes.items():
            restored[nid] = NodeResult(
                node_id=data["node_id"],
                state=NodeState(data["state"]),
                output=data.get("output"),
                error=data.get("error"),
                duration_ms=data.get("duration_ms", 0),
                retries=data.get("retries", 0),
            )
        self._results = restored
        return restored

    async def execute_with_checkpoint(
        self,
        dag: DAGSpec,
        checkpoint_callback: Callable[[CheckpointData], None] = None,
        checkpoint_interval: float = 60.0,
    ) -> dict[str, NodeResult]:
        """
        执行DAG并周期保存快照。超时或异常时保留已执行结果。

        Args:
            dag: DAG规格
            checkpoint_callback: 快照回调，收到最新的CheckpointData
            checkpoint_interval: 快照保存间隔（秒）
        Returns:
            最终执行结果
        """
        last_checkpoint_time = 0.0
        try:
            await self.execute(dag)
        except (asyncio.TimeoutError, Exception) as e:
            # 异常时保存当前状态
            cp = self.checkpoint(dag)
            if checkpoint_callback:
                checkpoint_callback(cp)
            raise
        else:
            # 最终完成快照
            cp = self.checkpoint(dag)
            if checkpoint_callback:
                checkpoint_callback(cp)
        return self._results


# ── DAG Builder (Fluent API) ────────────────────

class DAGBuilder:
    """流式构建DAG。"""

    def __init__(self, name: str = "unnamed"):
        self.name = name
        self._nodes: dict[str, ToolNode] = {}
        self._parallels: list[ParallelGroup] = []
        self._conditions: dict[str, ConditionNode] = {}
        self._entry: list[str] = []

    def node(
        self,
        node_id: str,
        tool_name: str,
        tool_args: dict | None = None,
        depends_on: list[str] | None = None,
        timeout: float = 60.0,
        retry: RetryPolicy | None = None,
        input_transform: Callable | None = None,
    ) -> "DAGBuilder":
        self._nodes[node_id] = ToolNode(
            tool_name=tool_name,
            tool_args=tool_args or {},
            depends_on=depends_on or [],
            timeout=timeout,
            retry=retry,
            input_transform=input_transform,
        )
        if not depends_on:
            self._entry.append(node_id)
        return self

    def parallel(self, node_ids: list[str], depends_on: list[str] | None = None, max_concurrency: int = 5) -> "DAGBuilder":
        self._parallels.append(ParallelGroup(
            node_ids=node_ids,
            depends_on=depends_on or [],
            max_concurrency=max_concurrency,
        ))
        return self

    def condition(self, cond_id: str, condition: Callable, depends_on: list[str]) -> "DAGBuilder":
        self._conditions[cond_id] = ConditionNode(
            condition=condition,
            depends_on=depends_on,
        )
        return self

    def build(self, global_timeout: float = 300.0) -> DAGSpec:
        return DAGSpec(
            name=self.name,
            nodes=self._nodes,
            parallels=self._parallels,
            conditions=self._conditions,
            entry=self._entry,
            global_timeout=global_timeout,
        )


# ── Pre-built Chains ────────────────────────────

def chain_builder(name: str, tool_names: list[str]) -> DAGSpec:
    """构建简单顺序链。"""
    builder = DAGBuilder(name)
    prev = None
    for i, tool_name in enumerate(tool_names):
        nid = f"step_{i}"
        deps = [f"step_{i - 1}"] if i > 0 else []
        builder.node(nid, tool_name, depends_on=deps)
    return builder.build()


def parallel_then_merge(name: str, parallel_tools: list[str], merge_tool: str) -> DAGSpec:
    """构建 并行→合并 模式。"""
    builder = DAGBuilder(name)
    pids = []
    for i, tool_name in enumerate(parallel_tools):
        nid = f"par_{i}"
        builder.node(nid, tool_name)
        pids.append(nid)
    builder.parallel(pids)
    builder.node("merge", merge_tool, depends_on=pids)
    return builder.build()


def if_then_else(name: str, check_tool: str, true_tool: str, false_tool: str) -> DAGSpec:
    """构建 if-then-else 条件分支。"""
    builder = DAGBuilder(name)
    builder.node("check", check_tool)
    builder.condition("cond", lambda up: "true_branch" if up.get("check", {}).get("output") else "false_branch", depends_on=["check"])
    builder.node("true_branch", true_tool, depends_on=["check"])
    builder.node("false_branch", false_tool, depends_on=["check"])
    return builder.build()
