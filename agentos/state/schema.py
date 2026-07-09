"""
AgentOS v1.14.0 — 结构化 Agent 状态管理系统。

基因来源: LangGraph Pydantic State Schema + AgentOS Checkpoint。

核心设计:
- AgentState: 强类型的全局 Agent 运行时状态，Pydantic v2 驱动
- 支持 JSON Schema 自动生成、验证、序列化
- 与 Checkpoint 系统无缝对接
- 支持状态合并策略（reducer）：append/extend/replace/merge
- 支持子状态派生（SubState），实现层级化状态管理
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import (
    Any,
    TypeVar,
)

try:
    from pydantic import (
        BaseModel,
        ConfigDict,
        Field,
        PrivateAttr,
    )
except ImportError:
    raise ImportError(
        "pydantic>=2.0 is required for agentos.state. " "Install with: pip install pydantic>=2.0"
    )

# ── Reducers ────────────────────────────────


class ReducerStrategy(StrEnum):
    """状态合并策略。"""

    REPLACE = "replace"  # 直接替换
    APPEND = "append"  # 追加（list -> extend）
    EXTEND = "extend"  # 字典合并
    MERGE = "merge"  # 深度递归合并
    KEEP_EXISTING = "keep"  # 保留旧值
    CUSTOM = "custom"  # 自定义 reducer 函数


# Type variable for generic state
S = TypeVar("S", bound=BaseModel)

# Custom reducer type
ReducerFn = Callable[[Any, Any], Any]

# Default reducers
_DEFAULT_REDUCERS: dict[str, ReducerStrategy] = {}


def default_reducer(field_name: str, strategy: ReducerStrategy) -> None:
    """注册字段的默认合并策略。

    Usage:
        default_reducer("messages", ReducerStrategy.APPEND)
    """
    _DEFAULT_REDUCERS[field_name] = strategy


def _apply_reducer(old_val: Any, new_val: Any, strategy: ReducerStrategy) -> Any:
    """应用合并策略。"""
    if strategy == ReducerStrategy.REPLACE or old_val is None:
        return new_val
    if new_val is None:
        return old_val
    if strategy == ReducerStrategy.KEEP_EXISTING:
        return old_val
    if strategy == ReducerStrategy.APPEND:
        if isinstance(old_val, list) and isinstance(new_val, list):
            return old_val + new_val
        return [old_val, new_val]
    if strategy == ReducerStrategy.EXTEND:
        if isinstance(old_val, dict) and isinstance(new_val, dict):
            return {**old_val, **new_val}
        return new_val
    if strategy == ReducerStrategy.MERGE:
        return _deep_merge(old_val, new_val)
    return new_val


def _deep_merge(old: Any, new: Any) -> Any:
    """递归深度合并两个字典。"""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return new
    result = dict(old)
    for k, v in new.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ── Field Metadata ──────────────────────────


class StateFieldInfo(BaseModel):
    """状态字段元信息。"""

    reducer: ReducerStrategy = ReducerStrategy.REPLACE
    custom_reducer: ReducerFn | None = None
    description: str = ""
    required: bool = False
    sensitive: bool = False  # 敏感字段，序列化时脱敏
    checkpointed: bool = True  # 是否持久化到 Checkpoint

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ── AgentState Core ─────────────────────────


class BaseAgentState(BaseModel):
    """Agent 状态的基类。

    所有 Agent 状态必须继承此类。自动提供:
    - thread_id / session_id 追踪
    - step 计数器
    - 状态快照（snapshot）与恢复（restore）
    - JSON Schema 生成
    - Checkpoint 序列化

    Usage:
        class MyState(BaseAgentState):
            messages: list[dict] = Field(default_factory=list)
            tools_result: dict = Field(default_factory=dict)
            task_progress: float = 0.0
    """

    thread_id: str = Field(
        default_factory=lambda: f"thread-{uuid.uuid4().hex[:8]}",
        description="对话线程唯一标识",
    )
    messages: list[Any] = Field(default_factory=list, description="对话消息列表")
    metrics: dict[str, Any] = Field(default_factory=dict, description="运行时指标")
    step: int = Field(default=0, ge=0, description="当前执行步骤")
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="创建时间",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="最后更新时间",
    )
    tags: list[str] = Field(default_factory=list, description="标签")
    metadata: dict[str, Any] = Field(default_factory=dict, description="自定义元数据")
    parent_state_id: str | None = Field(default=None, description="父状态 ID（用于分支/回溯）")

    # 字段级 Reducer 配置
    _field_reducers: dict[str, ReducerStrategy] = PrivateAttr(default_factory=dict)
    _field_custom_reducers: dict[str, ReducerFn] = PrivateAttr(default_factory=dict)
    _sensitive_fields: set[str] = PrivateAttr(default_factory=set)

    model_config = ConfigDict(
        extra="allow",
        validate_assignment=True,
        json_schema_extra={
            "title": "AgentState",
            "description": "AgentOS Structured Agent State",
        },
    )

    def __init__(self, **data):
        super().__init__(**data)
        self._field_reducers = {}
        self._field_custom_reducers = {}
        self._sensitive_fields = set()

    # ── Reducer Registration ──────────────────

    def set_reducer(self, field: str, strategy: ReducerStrategy) -> BaseAgentState:
        """为字段设置合并策略。"""
        self._field_reducers[field] = strategy
        return self

    def set_custom_reducer(self, field: str, fn: ReducerFn) -> BaseAgentState:
        """为字段设置自定义合并函数。"""
        self._field_custom_reducers[field] = fn
        self._field_reducers[field] = ReducerStrategy.CUSTOM
        return self

    def mark_sensitive(self, *fields: str) -> BaseAgentState:
        """标记敏感字段。"""
        self._sensitive_fields.update(fields)
        return self

    # ── State Mutation ────────────────────────

    def update_field(
        self,
        field: str,
        value: Any,
        reducer: ReducerStrategy | None = None,
    ) -> None:
        """更新单个字段，自动应用 Reducer。

        Args:
            field: 字段名
            value: 新值
            reducer: 合并策略，不传则使用注册的 reducer
        """
        if field not in self.model_fields and field not in self.model_computed_fields:
            # Dynamic field — store in metadata
            old = self.metadata.get(field)
            strategy = reducer or self._field_reducers.get(
                field,
                ReducerStrategy.REPLACE,
            )
            self.metadata[field] = _apply_reducer(old, value, strategy)
        else:
            old = getattr(self, field, None)
            strategy = reducer or self._field_reducers.get(
                field,
                ReducerStrategy.REPLACE,
            )
            new_val = _apply_reducer(old, value, strategy)
            setattr(self, field, new_val)

        self.updated_at = datetime.now(UTC).isoformat()

    def merge(self, other: BaseAgentState | dict) -> BaseAgentState:
        """合并另一个状态到当前状态。

        Args:
            other: 另一个 AgentState 实例或字典

        Returns:
            self (in-place merge)
        """
        if isinstance(other, dict):
            other = self.__class__(**other)

        for field_name in other.model_fields:
            if field_name in ("thread_id", "created_at"):
                continue  # Immutable fields

            other_val = getattr(other, field_name, None)
            if other_val is None:
                continue

            self.update_field(field_name, other_val)

        # Merge metadata
        if other.metadata:
            self.metadata = _deep_merge(self.metadata, other.metadata)
            self.updated_at = datetime.now(UTC).isoformat()

        # Merge tags
        if other.tags:
            self.tags = list(set(self.tags + other.tags))

        return self

    def increment_step(self) -> int:
        """递增步骤计数器，返回新 step。"""
        self.step += 1
        self.updated_at = datetime.now(UTC).isoformat()
        return self.step

    # ── Snapshot & Restore ────────────────────

    def snapshot(self) -> dict[str, Any]:
        """生成当前状态的完整快照。

        Returns:
            可序列化的状态字典（可直接存入 Checkpoint）
        """
        data = self.model_dump(mode="python", exclude_none=False)
        # Remove private attrs
        data.pop("_field_reducers", None)
        data.pop("_field_custom_reducers", None)
        data.pop("_sensitive_fields", None)
        return data

    def sanitized_snapshot(self) -> dict[str, Any]:
        """生成脱敏快照（敏感字段替换为 '***'）"""
        data = self.snapshot()
        for field in self._sensitive_fields:
            if field in data:
                data[field] = "***"
        return data

    @classmethod
    def restore(cls, data: dict[str, Any]) -> BaseAgentState:
        """从快照字典恢复状态。

        Args:
            data: snapshot() 返回的字典

        Returns:
            新的 AgentState 实例
        """

        def _clean_private(d: dict) -> dict:
            return {k: v for k, v in d.items() if not k.startswith("_")}

        cleaned = _clean_private(data)
        instance = cls(**cleaned)
        # Restore reducer configs from saved metadata if present
        if "metadata" in cleaned and isinstance(cleaned["metadata"], dict):
            reducer_config = cleaned["metadata"].get("_reducer_config")
            if isinstance(reducer_config, dict):
                for field, strategy_name in reducer_config.items():
                    try:
                        strategy = ReducerStrategy(strategy_name)
                        instance._field_reducers[field] = strategy
                    except ValueError:
                        pass
        return instance

    def diff(self, other: BaseAgentState) -> dict[str, tuple]:
        """计算两个状态之间的差异。

        Returns:
            {field: (old_val, new_val)} 的字典
        """
        diffs = {}
        for field in self.model_fields:
            old = getattr(self, field, None)
            new = getattr(other, field, None)
            if old != new:
                diffs[field] = (old, new)
        return diffs

    # ── JSON Schema ───────────────────────────

    @classmethod
    def generate_schema(cls) -> dict[str, Any]:
        """生成状态的 JSON Schema（符合 OpenAI Function Calling 格式）。

        Returns:
            JSON Schema dict，可直接用作 tool/function 的 parameters 定义
        """
        return cls.model_json_schema()

    @classmethod
    def validate_json_input(cls, data: dict) -> BaseAgentState:
        """从 JSON 字典验证并创建实例。"""
        return cls.model_validate(data)


# ── Specialized States ──────────────────────


class AgentState(BaseAgentState):
    """通用 Agent 运行状态。

    预配置了常用字段和默认 reducer:
    - messages: APPEND（对话消息累积）
    - tools_result: MERGE（工具结果合并）
    - errors: APPEND（错误收集）
    - intermediate: REPLACE（中间结果替换）
    """

    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="对话消息历史",
    )
    tools_result: dict[str, Any] = Field(
        default_factory=dict,
        description="最近一次工具调用结果",
    )
    intermediate: dict[str, Any] = Field(
        default_factory=dict,
        description="中间计算结果（每次替换）",
    )
    errors: list[dict[str, Any]] = Field(
        default_factory=list,
        description="错误堆栈",
    )
    human_interrupts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="人工干预请求队列",
    )
    context_summary: str = Field(
        default="",
        description="上下文摘要（自动分页用）",
    )
    task_progress: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="任务进度 0.0~1.0",
    )
    abort_reason: str | None = Field(
        default=None,
        description="中止原因（非空表示需中止）",
    )

    def __init__(self, **data):
        super().__init__(**data)
        # Default reducers for AgentState
        self._field_reducers["messages"] = ReducerStrategy.APPEND
        self._field_reducers["tools_result"] = ReducerStrategy.MERGE
        self._field_reducers["errors"] = ReducerStrategy.APPEND
        self._field_reducers["human_interrupts"] = ReducerStrategy.APPEND
        self._field_reducers["intermediate"] = ReducerStrategy.REPLACE

    @property
    def last_message(self) -> dict[str, Any] | None:
        """获取最后一条消息。"""
        return self.messages[-1] if self.messages else None

    @property
    def error_count(self) -> int:
        """累计错误数。"""
        return len(self.errors)

    @property
    def should_abort(self) -> bool:
        """是否需要中止执行？"""
        return self.abort_reason is not None

    def add_message(self, role: str, content: str, **extra) -> AgentState:
        """添加一条消息。"""
        msg = {"role": role, "content": content, **extra}
        self.update_field("messages", [msg])
        return self

    def add_error(self, error_type: str, message: str, **extra) -> AgentState:
        """记录一个错误。"""
        err = {
            "type": error_type,
            "message": message,
            "step": self.step,
            "timestamp": datetime.now(UTC).isoformat(),
            **extra,
        }
        self.update_field("errors", [err])
        return self

    def request_human_input(
        self,
        prompt: str,
        options: list[str] | None = None,
        **extra,
    ) -> AgentState:
        """发起人工干预请求。"""
        interrupt = {
            "prompt": prompt,
            "options": options,
            "step": self.step,
            "timestamp": datetime.now(UTC).isoformat(),
            **extra,
        }
        self.update_field("human_interrupts", [interrupt])
        return self

    def clear_human_interrupts(self) -> AgentState:
        """清除所有待处理的人工干预请求。"""
        self.human_interrupts = []
        return self

    def abort(self, reason: str) -> AgentState:
        """标记任务需要中止。"""
        self.abort_reason = reason
        return self

    def reset_abort(self) -> AgentState:
        """清除中止标记。"""
        self.abort_reason = None
        return self


class MultiAgentState(BaseAgentState):
    """多 Agent 协作状态。

    管理多个子 Agent 的状态、消息路由、角色分配。
    """

    agents: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="所有子 Agent 的状态 {agent_id: {state dict}}",
    )
    message_queue: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Agent 间消息队列",
    )
    roles: dict[str, str] = Field(
        default_factory=dict,
        description="Agent 角色分配 {agent_id: role_name}",
    )
    coordinator_state: dict[str, Any] = Field(
        default_factory=dict,
        description="协调器内部状态",
    )
    handoff_log: list[dict[str, Any]] = Field(
        default_factory=list,
        description="任务移交记录",
    )

    def __init__(self, **data):
        super().__init__(**data)
        self._field_reducers["agents"] = ReducerStrategy.MERGE
        self._field_reducers["message_queue"] = ReducerStrategy.APPEND
        self._field_reducers["handoff_log"] = ReducerStrategy.APPEND

    def register_agent(self, agent_id: str, role: str = "worker", **meta) -> MultiAgentState:
        """注册一个子 Agent。"""
        self.agents[agent_id] = {
            "role": role,
            "state": "idle",
            "step": 0,
            "errors": 0,
            **meta,
        }
        self.roles[agent_id] = role
        return self

    def update_agent_state(self, agent_id: str, updates: dict[str, Any]) -> MultiAgentState:
        """更新子 Agent 的状态。"""
        if agent_id in self.agents:
            self.agents[agent_id].update(updates)
            self._touch()
        return self

    def send_message(self, from_agent: str, to_agent: str, content: Any) -> MultiAgentState:
        """Agent 间发送消息。"""
        msg = {
            "from": from_agent,
            "to": to_agent,
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.update_field("message_queue", [msg])
        return self

    def log_handoff(
        self, from_agent: str, to_agent: str, task_id: str, reason: str = ""
    ) -> MultiAgentState:
        """记录任务移交。"""
        self.update_field(
            "handoff_log",
            [
                {
                    "from": from_agent,
                    "to": to_agent,
                    "task_id": task_id,
                    "reason": reason,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            ],
        )
        return self

    def _touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()


class ToolCallState(BaseAgentState):
    """工具调用追踪状态。

    用于细粒度监控每次工具调用的入参/出参/耗时。
    """

    calls: list[dict[str, Any]] = Field(
        default_factory=list,
        description="工具调用历史",
    )
    pending_calls: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="进行中的工具调用 {call_id: {tool, args, start_time}}",
    )
    tool_stats: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="工具统计 {tool_name: {count, total_ms, errors, avg_ms}}",
    )

    def __init__(self, **data):
        super().__init__(**data)
        self._field_reducers["calls"] = ReducerStrategy.APPEND

    def start_call(self, call_id: str, tool: str, args: dict) -> ToolCallState:
        """记录工具调用开始。"""
        self.pending_calls[call_id] = {
            "tool": tool,
            "args": args,
            "start_time": time.time(),
            "step": self.step,
        }
        self._init_stats(tool)
        return self

    def complete_call(self, call_id: str, result: Any, error: str | None = None) -> ToolCallState:
        """记录工具调用完成。"""
        if call_id not in self.pending_calls:
            return self  # 幂等
        call_info = self.pending_calls.pop(call_id)
        elapsed_ms = (time.time() - call_info["start_time"]) * 1000
        record = {
            **call_info,
            "call_id": call_id,
            "elapsed_ms": round(elapsed_ms, 2),
            "result": result,
            "error": error,
            "success": error is None,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.update_field("calls", [record])

        # Update stats
        tool = call_info["tool"]
        stats = self.tool_stats.get(tool, {})
        stats["count"] = stats.get("count", 0) + 1
        stats["total_ms"] = stats.get("total_ms", 0) + elapsed_ms
        stats["errors"] = stats.get("errors", 0) + (1 if error else 0)
        stats["avg_ms"] = stats["total_ms"] / stats["count"]
        self.tool_stats[tool] = stats

        return self

    def _init_stats(self, tool: str) -> None:
        """初始化工具统计。"""
        if tool not in self.tool_stats:
            self.tool_stats[tool] = {
                "count": 0,
                "total_ms": 0,
                "errors": 0,
                "avg_ms": 0,
            }

    @property
    def total_tool_calls(self) -> int:
        """总工具调用次数。"""
        return len(self.calls)

    @property
    def failed_calls(self) -> int:
        """失败的工具调用次数。"""
        return sum(1 for c in self.calls if not c.get("success", True))


# ── Schema Registry ──────────────────────────


class StateSchemaRegistry:
    """状态 Schema 注册中心。

    支持按名称查找、注册、验证状态类型。
    """

    def __init__(self):
        self._schemas: dict[str, type[BaseAgentState]] = {}
        self._default_name: str = "AgentState"
        self._schemas[self._default_name] = AgentState
        self._schemas["MultiAgentState"] = MultiAgentState
        self._schemas["ToolCallState"] = ToolCallState

    def register(self, name: str, schema_cls: type[BaseAgentState]) -> None:
        """注册自定义状态类型。"""
        if not issubclass(schema_cls, BaseAgentState):
            raise TypeError(
                f"State class must inherit from BaseAgentState, " f"got {schema_cls.__name__}"
            )
        self._schemas[name] = schema_cls

    def get(self, name: str) -> type[BaseAgentState]:
        """获取已注册的状态类型。"""
        if name not in self._schemas:
            raise KeyError(
                f"Unknown state schema: '{name}'. " f"Available: {list(self._schemas.keys())}"
            )
        return self._schemas[name]

    def list_schemas(self) -> list[str]:
        """列出所有已注册的状态类型。"""
        return list(self._schemas.keys())

    def create_state(self, name: str, **kwargs) -> BaseAgentState:
        """创建已注册类型的实例。"""
        cls = self.get(name)
        return cls(**kwargs)

    def validate(self, name: str, data: dict) -> BaseAgentState:
        """验证并创建状态实例。"""
        cls = self.get(name)
        return cls.model_validate(data)

    @property
    def default_state_class(self) -> type[BaseAgentState]:
        """默认状态类型。"""
        return self._schemas[self._default_name]

    @default_state_class.setter
    def default_state_class(self, name: str) -> None:
        if name not in self._schemas:
            raise KeyError(f"Unknown state schema: '{name}'")
        self._default_name = name


# ── 全局单例 ─────────────────────────────────

state_registry = StateSchemaRegistry()


# ── State Reducers (test compatibility) ──
class StateReducer:
    """Base state reducer with merge strategy."""

    @staticmethod
    def merge(base_state, new_state):
        data = base_state.model_dump()
        new_data = new_state.model_dump(exclude_unset=True)
        data.update(new_data)
        return type(base_state)(**data)


class LastWriteWinsReducer:
    """Reducer: newer state wins based on version."""

    @staticmethod
    def merge(base_state, new_state):
        bv = getattr(base_state, "version", 0)
        nv = getattr(new_state, "version", 0)
        if nv >= bv:
            data = base_state.model_dump()
            data.update(new_state.model_dump(exclude_unset=True))
            return type(base_state)(**data)
        return base_state


class AppendOnlyReducer:
    """Reducer: append-only for list fields."""

    MERGE_FIELDS = ["messages", "logs"]

    @staticmethod
    def merge(base_state, new_state):
        data = base_state.model_dump()
        new_data = new_state.model_dump(exclude_unset=True)
        for field in AppendOnlyReducer.MERGE_FIELDS:
            if field in new_data and field in data:
                data[field] = list(data[field]) + list(new_data[field])
        data.update({k: v for k, v in new_data.items() if k not in AppendOnlyReducer.MERGE_FIELDS})
        return type(base_state)(**data)
