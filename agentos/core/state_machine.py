"""
AgentOS v0.60 State Machine — Agent 生命周期状态管理。
状态：Idle → Thinking → Acting → Observing → (Complete|Failed|Paused)
含转换守卫、超时检测、恢复机制。
"""

from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Awaitable


class AgentState(str, Enum):

    """Agent 状态枚举。"""

    IDLE = "idle"               # 空闲，等待任务
    INITIALIZING = "initializing"  # 加载配置/工具
    THINKING = "thinking"       # 推理/规划
    ACTING = "acting"           # 执行工具/调用模型
    OBSERVING = "observing"     # 处理工具返回/反思
    WAITING = "waiting"         # 等待外部输入(HITL)
    PAUSED = "paused"           # 手动暂停
    COMPLETED = "completed"     # 任务完成
    FAILED = "failed"           # 任务失败
    CANCELLED = "cancelled"     # 被取消
    ERROR = "error"             # 系统错误


# 合法状态转换表
VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE:         {AgentState.INITIALIZING, AgentState.CANCELLED},
    AgentState.INITIALIZING: {AgentState.IDLE, AgentState.THINKING, AgentState.FAILED, AgentState.ERROR},
    AgentState.THINKING:     {AgentState.ACTING, AgentState.WAITING, AgentState.COMPLETED, AgentState.FAILED, AgentState.PAUSED, AgentState.ERROR},
    AgentState.ACTING:       {AgentState.OBSERVING, AgentState.FAILED, AgentState.ERROR},
    AgentState.OBSERVING:    {AgentState.THINKING, AgentState.ACTING, AgentState.COMPLETED, AgentState.FAILED, AgentState.ERROR},
    AgentState.WAITING:      {AgentState.THINKING, AgentState.ACTING, AgentState.CANCELLED, AgentState.PAUSED, AgentState.ERROR},
    AgentState.PAUSED:       {AgentState.THINKING, AgentState.ACTING, AgentState.OBSERVING, AgentState.CANCELLED, AgentState.ERROR},
    AgentState.COMPLETED:    set(),  # 终态
    AgentState.FAILED:       {AgentState.IDLE, AgentState.ERROR},
    AgentState.CANCELLED:    {AgentState.IDLE, AgentState.ERROR},
    AgentState.ERROR:        {AgentState.IDLE, AgentState.FAILED},
}


@dataclass
class StateTransition:
    """状态转换事件记录。"""

    from_state: AgentState
    to_state: AgentState
    timestamp: float = field(default_factory=time.time)
    reason: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class StateMachineConfig:
    """状态机运行时配置。"""

    max_thinking_time: float = 300.0    # 推理超时（秒）
    max_acting_time: float = 120.0      # 执行超时
    max_observing_time: float = 60.0    # 观察超时
    max_total_time: float = 3600.0      # 总超时
    max_transitions: int = 500          # 最大状态转换次数
    auto_recover: bool = True           # 错误后自动恢复
    max_retries_after_error: int = 3


class TransitionError(Exception):
    """非法状态转换异常。"""

    def __init__(self, from_state: AgentState, to_state: AgentState):
        super().__init__(f"Invalid transition: {from_state.value} → {to_state.value}")
        self.from_state = from_state
        self.to_state = to_state


class StateTimeoutError(Exception):
    """状态超时异常。"""

    def __init__(self, state: AgentState, elapsed: float, limit: float):
        super().__init__(f"{state.value} timeout: {elapsed:.1f}s > {limit:.1f}s")
        self.state = state
        self.elapsed = elapsed


class AgentStateMachine:
    """Agent有限状态机，带守卫和超时检测。"""

    def __init__(self, config: StateMachineConfig | None = None):
        self.config = config or StateMachineConfig()
        self._state: AgentState = AgentState.IDLE
        self._history: list[StateTransition] = []
        self._state_enter_time: float = time.time()
        self._created_at: float = time.time()
        self._error_count: int = 0
        self._on_transition_hooks: dict[tuple[AgentState, AgentState], list[Callable]] = {}

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def elapsed_total(self) -> float:
        return time.time() - self._created_at

    @property
    def elapsed_in_state(self) -> float:
        return time.time() - self._state_enter_time

    @property
    def history(self) -> list[StateTransition]:
        return list(self._history)

    def _guard(self, target: AgentState) -> bool:
        """状态转换守卫。"""
        valid = VALID_TRANSITIONS.get(self._state, set())
        if target not in valid:
            raise TransitionError(self._state, target)

        if len(self._history) >= self.config.max_transitions:
            raise RuntimeError(f"Max transitions ({self.config.max_transitions}) exceeded")

        if self.elapsed_total >= self.config.max_total_time:
            raise StateTimeoutError(self._state, self.elapsed_total, self.config.max_total_time)

        return True

    def _check_timeout(self):
        """检查当前状态是否超时。"""
        limits = {
            AgentState.THINKING: self.config.max_thinking_time,
            AgentState.ACTING: self.config.max_acting_time,
            AgentState.OBSERVING: self.config.max_observing_time,
        }
        limit = limits.get(self._state)
        if limit and self.elapsed_in_state > limit:
            raise StateTimeoutError(self._state, self.elapsed_in_state, limit)

    def transition(self, to_state: AgentState, reason: str = "",
                   metadata: dict | None = None) -> StateTransition:
        """执行状态转换。"""
        self._check_timeout()
        self._guard(to_state)

        transition = StateTransition(
            from_state=self._state,
            to_state=to_state,
            reason=reason,
            metadata=metadata or {},
        )
        self._history.append(transition)
        self._state = to_state
        self._state_enter_time = time.time()
        self._fire_hooks(transition)
        return transition

    def on_transition(self, from_state: AgentState, to_state: AgentState):
        """装饰器：注册状态转换钩子。"""
        def decorator(fn):
            key = (from_state, to_state)
            self._on_transition_hooks.setdefault(key, []).append(fn)
            return fn
        return decorator

    def _fire_hooks(self, transition: StateTransition):
        key = (transition.from_state, transition.to_state)
        for hook in self._on_transition_hooks.get(key, []):
            hook(transition)

    # ── 便利方法 ──────────────────────────────────────────────────────────

    def start(self, reason: str = ""):
        return self.transition(AgentState.INITIALIZING, reason)

    def think(self, reason: str = ""):
        return self.transition(AgentState.THINKING, reason)

    def act(self, reason: str = ""):
        return self.transition(AgentState.ACTING, reason)

    def observe(self, reason: str = ""):
        return self.transition(AgentState.OBSERVING, reason)

    def complete(self, reason: str = ""):
        return self.transition(AgentState.COMPLETED, reason)

    def fail(self, reason: str = ""):
        self._error_count += 1
        return self.transition(AgentState.FAILED, reason)

    def pause(self, reason: str = ""):
        return self.transition(AgentState.PAUSED, reason)

    def resume(self, reason: str = ""):
        """从暂停恢复。"""
        if self._state != AgentState.PAUSED:
            raise TransitionError(self._state, AgentState.IDLE)
        prev = self._history[-1].from_state if self._history else AgentState.IDLE
        return self.transition(prev, reason=f"resumed: {reason}")

    def cancel(self, reason: str = ""):
        return self.transition(AgentState.CANCELLED, reason)

    def error(self, reason: str = ""):
        self._error_count += 1
        return self.transition(AgentState.ERROR, reason)

    def is_active(self) -> bool:
        return self._state in (AgentState.THINKING, AgentState.ACTING, AgentState.OBSERVING)

    def is_terminal(self) -> bool:
        return self._state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED)

    def run_idle(self):
        """错误/失败后回到空闲。"""
        if self._state in (AgentState.FAILED, AgentState.CANCELLED, AgentState.ERROR):
            return self.transition(AgentState.IDLE, "reset")
        raise TransitionError(self._state, AgentState.IDLE)

    def summary(self) -> dict:
        return {
            "state": self._state.value,
            "elapsed_total": f"{self.elapsed_total:.1f}s",
            "elapsed_in_state": f"{self.elapsed_in_state:.1f}s",
            "transitions": len(self._history),
            "error_count": self._error_count,
            "is_active": self.is_active(),
            "is_terminal": self.is_terminal(),
        }
