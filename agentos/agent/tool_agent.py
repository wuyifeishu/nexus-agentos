"""
Tool-Using Agent — 基于 LLM Function Calling 的自主 Agent 循环。

核心模式:
    用户任务 → LLM 推理(tool_calls) → 工具执行 → 结果回传 → 循环直到完成

v1.3.38: +streaming, retry, checkpoint/resume, tool error handling, mock provider.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generator

from agentos.llm.base import (
    LLMProvider,
    Message,
    MessageRole,
    CompletionResult,
    CompletionChoice,
    CompletionUsage,
    Tool,
    ToolCall,
)

__all__ = [
    "ToolAgent",
    "AgentConfig",
    "AgentStep",
    "AgentResult",
    "ToolExecutor",
    "MockLLMProvider",
]


# ── 数据类型 ─────────────────────────────────────────────────────

@dataclass
class AgentConfig:
    max_steps: int = 10
    temperature: float = 0.0
    max_tokens: int = 4096
    verbose: bool = False
    stop_on_error: bool = True
    max_retries: int = 2
    retry_delay: float = 0.5
    checkpoint_dir: str = ""


@dataclass
class AgentStep:
    step: int
    thought: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: dict[str, str] = field(default_factory=dict)
    finish_reason: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0


@dataclass
class AgentResult:
    success: bool = True
    final_answer: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    total_steps: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: float = 0.0
    error: str | None = None


# ── 工具执行器 ───────────────────────────────────────────────────

class ToolExecutor:
    def __init__(self):
        self._tools: dict[str, Callable[..., str]] = {}
        self._schemas: dict[str, Tool] = {}

    def register(self, tool: Tool, handler: Callable[..., str]) -> None:
        self._tools[tool.function.name] = handler
        self._schemas[tool.function.name] = tool

    def get_schemas(self) -> list[Tool]:
        return list(self._schemas.values())

    def execute(self, tool_call: ToolCall) -> str:
        handler = self._tools.get(tool_call.name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {tool_call.name}"})
        try:
            return str(handler(**tool_call.parsed_arguments))
        except Exception as e:
            return json.dumps({"error": str(e)})


# ── MockLLMProvider ──────────────────────────────────────────────

class MockLLMProvider(LLMProvider):
    """可编程响应的 Mock Provider，供集成测试使用。"""

    def __init__(self, responses: list[dict]):
        super().__init__(model="mock", api_key="mock")
        self._responses = responses
        self._cursor = 0
        self.calls: list[dict] = []

    def chat(self, messages=None, *, temperature=0, max_tokens=4096, tools=None, **kwargs):
        if self._cursor >= len(self._responses):
            return self._build_result({"content": "done", "finish_reason": "stop"})
        resp = self._responses[self._cursor]
        self._cursor += 1
        self.calls.append({
            "tools": [t.function.name for t in (tools or [])],
            "cursor": self._cursor - 1,
        })
        return self._build_result(resp)

    async def achat(self, *args, **kwargs):
        return self.chat(*args, **kwargs)

    @property
    def provider_name(self) -> str:
        return "mock"

    @staticmethod
    def text_response(content: str, finish_reason: str = "stop") -> dict:
        return {"content": content, "finish_reason": finish_reason}

    @staticmethod
    def tool_response(name: str, arguments: dict, tool_call_id: str = "") -> dict:
        tid = tool_call_id or f"tc_{name}"
        return {
            "content": "",
            "tool_calls": [ToolCall(id=tid, name=name, arguments=json.dumps(arguments))],
            "finish_reason": "tool_calls",
        }

    def _build_result(self, resp: dict) -> CompletionResult:
        msg = Message(
            role=MessageRole.ASSISTANT,
            content=resp.get("content", ""),
            tool_calls=resp.get("tool_calls"),
        )
        choice = CompletionChoice(
            index=0,
            message=msg,
            finish_reason=resp.get("finish_reason", "stop"),
        )
        return CompletionResult(
            id=f"mock_{self._cursor}",
            model="mock-model",
            choices=[choice],
            usage=CompletionUsage(prompt_tokens=5, completion_tokens=len(resp.get("content", "")) + 3, total_tokens=len(resp.get("content", "")) + 8),
        )


# ── Tool-Using Agent ─────────────────────────────────────────────

class ToolAgent:
    """基于 LLM Function Calling 的自主 Agent。

    用法:
        from agentos.agent import ToolAgent, ToolExecutor
        from agentos.llm import create_provider, Tool

        provider = create_provider("openai")
        executor = ToolExecutor()
        executor.register(
            Tool.from_function("get_weather", "获取天气", {"city": ...}),
            lambda city: f"{city}: 22°C sunny"
        )
        agent = ToolAgent(provider, executor)
        result = agent.run("北京天气怎么样？")
        print(result.final_answer)
    """

    def __init__(
        self,
        provider: LLMProvider,
        tool_executor: ToolExecutor,
        *,
        config: AgentConfig | None = None,
        system_prompt: str = "",
    ):
        self._provider = provider
        self._executor = tool_executor
        self._config = config or AgentConfig()
        self._system_prompt = system_prompt or (
            "你是一个智能助手。你可以使用工具来获取信息。"
            "当你可以给出最终答案时，直接回答，不要再调用工具。"
            "用中文回答。"
        )

    # ── 同步 ──────────────────────────────────────────────────

    def run(self, task: str) -> AgentResult:
        t0 = time.monotonic()
        steps: list[AgentStep] = []
        tools = self._executor.get_schemas()
        messages: list[Message] = [
            Message(role=MessageRole.SYSTEM, content=self._system_prompt),
            Message(role=MessageRole.USER, content=task),
        ]
        return self._run_loop(messages, task, tools, steps, 1, t0)

    def _run_loop(
        self, messages, task, tools, steps, start_step, t0,
    ) -> AgentResult:
        final_answer = ""
        total_tokens = 0
        total_cost = 0.0
        step_num = start_step

        try:
            for step_num in range(start_step, self._config.max_steps + 1):
                result = self._call_with_retry(messages, tools)
                step, done, final = self._process_step(result, step_num)
                total_tokens += step.tokens_used
                total_cost += step.cost_usd
                steps.append(step)
                if done:
                    final_answer = final
                    break
                messages.append(result.choices[0].message)
                for tc in step.tool_calls:
                    messages.append(Message(
                        role=MessageRole.TOOL,
                        content=step.tool_results.get(tc.id, ""),
                        tool_call_id=tc.id,
                    ))
                self._checkpoint(messages, task, step_num)
            else:
                return self._make_result(
                    False, "", steps, total_tokens, total_cost, t0,
                    f"Reached max steps ({self._config.max_steps}) without final answer",
                )
        except Exception as e:
            return self._make_result(False, "", steps, total_tokens, total_cost, t0, str(e))

        return self._make_result(True, final_answer, steps, total_tokens, total_cost, t0)

    # ── 流式 ──────────────────────────────────────────────────

    def run_stream(self, task: str) -> Generator[AgentStep, None, AgentResult]:
        t0 = time.monotonic()
        steps: list[AgentStep] = []
        tools = self._executor.get_schemas()
        messages: list[Message] = [
            Message(role=MessageRole.SYSTEM, content=self._system_prompt),
            Message(role=MessageRole.USER, content=task),
        ]
        total_tokens = 0
        total_cost = 0.0
        final_answer = ""

        try:
            for step_num in range(1, self._config.max_steps + 1):
                result = self._call_with_retry(messages, tools)
                step, done, final = self._process_step(result, step_num)
                total_tokens += step.tokens_used
                total_cost += step.cost_usd
                yield step
                steps.append(step)
                if done:
                    final_answer = final
                    break
                messages.append(result.choices[0].message)
                for tc in step.tool_calls:
                    messages.append(Message(
                        role=MessageRole.TOOL,
                        content=step.tool_results.get(tc.id, ""),
                        tool_call_id=tc.id,
                    ))
                self._checkpoint(messages, task, step_num)
            else:
                return self._make_result(
                    False, "", steps, total_tokens, total_cost, t0,
                    f"Reached max steps ({self._config.max_steps}) without final answer",
                )
        except Exception as e:
            return self._make_result(False, "", steps, total_tokens, total_cost, t0, str(e))

        return self._make_result(True, final_answer, steps, total_tokens, total_cost, t0)

    # ── 异步 ──────────────────────────────────────────────────

    async def arun(self, task: str) -> AgentResult:
        t0 = time.monotonic()
        steps: list[AgentStep] = []
        tools = self._executor.get_schemas()
        messages: list[Message] = [
            Message(role=MessageRole.SYSTEM, content=self._system_prompt),
            Message(role=MessageRole.USER, content=task),
        ]
        final_answer = ""
        total_tokens = 0
        total_cost = 0.0

        try:
            for step_num in range(1, self._config.max_steps + 1):
                result = await self._acall_with_retry(messages, tools)
                step, done, final = self._process_step(result, step_num)
                total_tokens += step.tokens_used
                total_cost += step.cost_usd
                steps.append(step)
                if done:
                    final_answer = final
                    break
                messages.append(result.choices[0].message)
                for tc in step.tool_calls:
                    messages.append(Message(
                        role=MessageRole.TOOL,
                        content=step.tool_results.get(tc.id, ""),
                        tool_call_id=tc.id,
                    ))
                self._checkpoint(messages, task, step_num)
            else:
                return self._make_result(
                    False, "", steps, total_tokens, total_cost, t0,
                    f"Reached max steps ({self._config.max_steps}) without final answer",
                )
        except Exception as e:
            return self._make_result(False, "", steps, total_tokens, total_cost, t0, str(e))

        return self._make_result(True, final_answer, steps, total_tokens, total_cost, t0)

    # ── 共享步骤逻辑 ───────────────────────────────────────────────

    def _process_step(
        self, result: CompletionResult, step_num: int,
    ) -> tuple[AgentStep, bool, str]:
        """处理单步 LLM 结果：构建 AgentStep、执行工具、判断终止。

        Returns:
            (step, done, final_answer)
        """
        step_t0 = time.monotonic()
        choice = result.choices[0]
        assistant_msg = choice.message

        step = AgentStep(
            step=step_num,
            thought=assistant_msg.content,
            tool_calls=assistant_msg.tool_calls or [],
            finish_reason=choice.finish_reason,
            tokens_used=result.usage.total_tokens,
            cost_usd=result.usage.cost_usd,
            duration_ms=(time.monotonic() - step_t0) * 1000,
        )

        if self._config.verbose:
            self._log_step(step)

        # 无工具调用 → 终止，内容即为答案
        if not assistant_msg.tool_calls:
            return step, True, assistant_msg.content

        # 执行工具调用
        for tc in assistant_msg.tool_calls:
            tool_result = self._executor.execute(tc)
            step.tool_results[tc.id] = tool_result
            if "error" in tool_result and self._config.stop_on_error:
                raise RuntimeError(f"Tool '{tc.name}' error: {tool_result}")

        # finish_reason == "stop" → 提前终止
        if choice.finish_reason == "stop":
            return step, True, assistant_msg.content

        return step, False, ""

    def _make_result(
        self, success: bool, answer: str, steps: list[AgentStep],
        total_tokens: int, total_cost: float, t0: float, error: str = None,
    ) -> AgentResult:
        """统一构造 AgentResult。"""
        return AgentResult(
            success=success,
            final_answer=answer,
            steps=steps,
            total_steps=len(steps),
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            total_duration_ms=(time.monotonic() - t0) * 1000,
            error=error,
        )

    # ── Checkpoint / Resume ───────────────────────────────────

    def resume(self) -> AgentResult:
        if not self._config.checkpoint_dir:
            raise ValueError("checkpoint_dir not configured")
        ckpt_path = os.path.join(self._config.checkpoint_dir, "agent_checkpoint.json")
        if not os.path.exists(ckpt_path):
            raise FileNotFoundError(f"No checkpoint found at {ckpt_path}")
        with open(ckpt_path) as f:
            data = json.load(f)
        task = data["task"]
        start_step = data["step"] + 1
        messages_raw = data["messages"]
        messages = [
            Message(
                role=MessageRole(m["role"]),
                content=m["content"],
                tool_call_id=m.get("tool_call_id"),
                tool_calls=[ToolCall(**tc) for tc in m["tool_calls"]] if m.get("tool_calls") else None,
            )
            for m in messages_raw
        ]
        t0 = time.monotonic()
        tools = self._executor.get_schemas()
        steps: list[AgentStep] = []
        return self._run_loop(messages, task, tools, steps, start_step, t0)

    def _checkpoint(self, messages: list[Message], task: str, step: int) -> None:
        if not self._config.checkpoint_dir:
            return
        ckpt_path = os.path.join(self._config.checkpoint_dir, "agent_checkpoint.json")
        data = {
            "task": task,
            "step": step,
            "messages": [
                {
                    "role": m.role.value,
                    "content": m.content,
                    "tool_call_id": m.tool_call_id,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in m.tool_calls
                    ] if m.tool_calls else None,
                }
                for m in messages
            ],
        }
        with open(ckpt_path, "w") as f:
            json.dump(data, f, ensure_ascii=False)

    # ── 内部方法 ──────────────────────────────────────────────

    def _call_with_retry(self, messages: list[Message], tools: list[Tool]) -> CompletionResult:
        last_error = None
        for attempt in range(self._config.max_retries + 1):
            try:
                return self._provider.chat(
                    messages,
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    tools=tools if tools else None,
                )
            except Exception as e:
                last_error = e
                if attempt < self._config.max_retries:
                    time.sleep(self._config.retry_delay)
        raise last_error  # type: ignore

    async def _acall_with_retry(self, messages: list[Message], tools: list[Tool]) -> CompletionResult:
        last_error = None
        for attempt in range(self._config.max_retries + 1):
            try:
                return await self._provider.achat(
                    messages,
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    tools=tools if tools else None,
                )
            except Exception as e:
                last_error = e
                if attempt < self._config.max_retries:
                    import asyncio
                    await asyncio.sleep(self._config.retry_delay)
        raise last_error  # type: ignore

    def _log_step(self, step: AgentStep) -> None:
        print(f"\n── Step {step.step} ({step.duration_ms:.0f}ms, {step.tokens_used}t, ${step.cost_usd:.6f}) ──")
        if step.thought:
            print(f"  Thought: {step.thought}")
        if step.tool_calls:
            for tc in step.tool_calls:
                result_preview = step.tool_results.get(tc.id, "")[:100]
                print(f"  Tool: {tc.name}({tc.arguments}) → {result_preview}")
        print(f"  Finish: {step.finish_reason}")
