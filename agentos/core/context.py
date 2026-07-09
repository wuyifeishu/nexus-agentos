"""
上下文管理器 — 构建Agent所需的完整上下文。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    """模型请求的工具调用。"""

    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """工具调用的返回结果。"""

    call_id: str
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass
class Message:
    """对话中的单条消息。"""

    role: str  # system | user | assistant | tool
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass
class AgentContext:
    """传给模型的完整上下文。"""

    messages: list[Message]
    tools: list[dict] | None = None
    model_type: str = "openai"


class ContextManager:
    """管理Agent会话的全部消息历史。"""

    def __init__(self, system_prompt: str = "", max_history: int = 200):
        self.system_prompt = system_prompt
        self.max_history = max_history
        self._messages: list[Message] = []
        self.session_id: str = ""
        self._current_task: str = ""
        self._step_count: int = 0
        self._plan: str = ""

    async def init_session(self, session_id: str, task: str):
        self.session_id = session_id
        self._current_task = task
        self._step_count = 0
        self._plan = ""
        self._messages = []
        if self.system_prompt:
            self._messages.append(Message(role="system", content=self.system_prompt))
        self._messages.append(Message(role="user", content=task))

    def build_context(
        self, model_type: str = "openai", tools: list[dict] | None = None
    ) -> AgentContext:
        self._step_count += 1
        messages = self._messages[-self.max_history :]
        return AgentContext(messages=messages, tools=tools, model_type=model_type)

    def update_plan(self, new_plan: str):
        self._plan = new_plan
        self._messages.append(Message(role="system", content=f"[计划更新] {new_plan}"))

    def append_tool_results(self, results: list[ToolResult]):
        for r in results:
            self._messages.append(
                Message(
                    role="tool",
                    content=r.error or r.output or "",
                    tool_call_id=r.call_id,
                )
            )

    def add_assistant_message(self, content: str, tool_calls: list[ToolCall] | None = None):
        self._messages.append(Message(role="assistant", content=content, tool_calls=tool_calls))

    def add_user_message(self, content: str):
        self._messages.append(Message(role="user", content=content))

    def estimate_context_usage(self) -> float:
        """估算上下文使用比例 (0.0-1.0)。按 max_history 消息数 vs 最大 Token 估算。"""
        if len(self._messages) == 0:
            return 0.0
        estimated_tokens = sum(len(m.content) for m in self._messages) // 4
        max_tokens = self.max_history * 200  # 每消息 ~200 token 粗估
        return min(estimated_tokens / max_tokens if max_tokens > 0 else 0.0, 1.0)

    @property
    def current_task(self) -> str:
        return self._current_task

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def plan(self) -> str:
        return self._plan

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def estimated_tokens(self) -> int:
        """粗略估算当前上下文的总token数（按每4字符≈1token）。"""
        total_chars = sum(len(m.content) for m in self._messages)
        return total_chars // 4
