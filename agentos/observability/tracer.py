"""
全链路追踪 — 每一步可追溯。
基因来源: LangSmith + OpenAI Tracing
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class StepTrace:
    """单步追踪记录。"""

    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls_count: int = 0
    error: str | None = None


@dataclass
class TokenStats:
    """Token 使用统计。"""

    total_input: int = 0
    total_output: int = 0
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class ObservabilityReport:
    """可观测性报告。"""

    session_id: str
    total_duration_ms: float = 0.0
    steps: list[StepTrace] = field(default_factory=list)
    tokens: TokenStats = field(default_factory=TokenStats)
    model_calls: int = 0
    tool_calls_total: int = 0

    def summary(self) -> str:
        lines = [
            f"Session: {self.session_id}",
            f"Duration: {self.total_duration_ms:.0f}ms",
            f"Model calls: {self.model_calls}",
            f"Tool calls: {self.tool_calls_total}",
            f"Tokens (in/out): {self.tokens.total_input}/{self.tokens.total_output}",
        ]
        if self.steps:
            lines.append(f"Steps: {', '.join(s.name for s in self.steps)}")
        return "\n".join(lines)


class Tracer:
    """全链路追踪器。每步记录耗时、token消耗、工具调用。"""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.steps: list[StepTrace] = []
        self.token_stats = TokenStats()
        self.start_time = time.time()

    @classmethod
    def noop(cls) -> Tracer:
        return NoopTracer()

    @contextmanager
    def step(self, name: str, model: str = ""):
        trace = StepTrace(name=name, model=model, start_time=time.time())
        try:
            yield trace
        except Exception as e:
            trace.error = str(e)
            raise
        finally:
            trace.end_time = time.time()
            trace.duration_ms = (trace.end_time - trace.start_time) * 1000
            self.steps.append(trace)

    def track_tokens(self, model: str, input_tokens: int, output_tokens: int):
        self.token_stats.total_input += input_tokens
        self.token_stats.total_output += output_tokens
        if model not in self.token_stats.by_model:
            self.token_stats.by_model[model] = {"input": 0, "output": 0}
        self.token_stats.by_model[model]["input"] += input_tokens
        self.token_stats.by_model[model]["output"] += output_tokens

    def track_tool_call(self):
        if self.steps:
            self.steps[-1].tool_calls_count += 1

    def report(self) -> ObservabilityReport:
        return ObservabilityReport(
            session_id=self.session_id,
            total_duration_ms=(time.time() - self.start_time) * 1000,
            steps=self.steps,
            tokens=self.token_stats,
            model_calls=len(self.steps),
            tool_calls_total=sum(s.tool_calls_count for s in self.steps),
        )

    def token_summary(self) -> dict[str, int]:
        return {
            "input": self.token_stats.total_input,
            "output": self.token_stats.total_output,
        }


class NoopTracer(Tracer):
    """空追踪器 — 生产环境中关闭追踪时使用。"""

    def __init__(self):
        pass

    @contextmanager
    def step(self, name: str, model: str = ""):
        yield StepTrace(name=name)

    def track_tokens(self, model: str, input_tokens: int, output_tokens: int):
        pass

    def track_tool_call(self):
        pass

    def report(self) -> ObservabilityReport:
        return ObservabilityReport(session_id="noop")

    def token_summary(self) -> dict[str, int]:
        return {}
