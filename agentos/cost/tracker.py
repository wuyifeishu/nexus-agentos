"""
AgentOS v1.1.4 成本追踪系统（增强版）。
v1.1.4新增: 实时按Run追踪（RunCostSession），灵感来自 CrewAI Control Plane 的实时成本核算。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ModelPricing:
    """模型定价配置。"""
    input_per_1m: float
    output_per_1m: float
    cached_input_per_1m: float = 0.0


PRICING = {
    "deepseek-v3.1": ModelPricing(0.27, 1.10),
    "deepseek-r1": ModelPricing(0.55, 2.19, 0.14),
    "kimi-k2.6": ModelPricing(1.50, 6.00),
    "qwen-3.6-plus": ModelPricing(0.80, 3.20),
    "claude-opus-4.8": ModelPricing(15.0, 75.0, 3.75),
    "glm-5.1": ModelPricing(0.50, 2.00),
    "minimax-m2.7": ModelPricing(0.15, 0.60),
}

# 上下文长度梯度折扣（超过一定token数缓存优惠）
_PROMPT_CACHE_MIN_TOKENS = 1024  # Claude Opus 4.8 已降至 1024


@dataclass
class UsageRecord:
    """用量记录。"""
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    timestamp: float = 0.0
    cost_usd: float = 0.0
    run_id: str = ""


@dataclass
class RunCostSession:
    """单次 Agent 运行的成本会话。"""

    run_id: str
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    records: list[UsageRecord] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def total_tokens(self) -> dict:
        inp = sum(r.input_tokens for r in self.records)
        out = sum(r.output_tokens for r in self.records)
        return {"input": inp, "output": out, "total": inp + out}

    @property
    def call_count(self) -> int:
        return len(self.records)

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at

    def summary(self) -> str:
        t = self.total_tokens
        return (
            f"Run {self.run_id[:8]}...: ${self.total_cost:.4f} | "
            f"{self.call_count} calls | {t['total']:,} tokens | "
            f"{self.duration_seconds:.1f}s"
        )


class CostTracker:
    """实时成本追踪器（v1.1.4增强）。

    新增能力：
    - 按 run 粒度分组追踪（RunCostSession）
    - 实时累计成本查询（按 run / 按 model）
    - 会话开始/结束生命周期
    """

    def __init__(self, budget_limit: float = 0.0):
        self.records: list[UsageRecord] = []
        self.budget_limit = budget_limit
        self._on_budget_warning: Optional[Callable] = None
        self._active_sessions: dict[str, RunCostSession] = {}
        self._completed_sessions: list[RunCostSession] = []

    # ── Session 生命周期 ────────────────────────────────────────────────────

    def start_session(self, run_id: Optional[str] = None) -> str:
        """开始一次运行会话，返回 run_id。"""
        rid = run_id or str(uuid.uuid4())[:12]
        if rid in self._active_sessions:
            raise ValueError(f"Session {rid} already active")
        self._active_sessions[rid] = RunCostSession(run_id=rid)
        return rid

    def end_session(self, run_id: str) -> Optional[RunCostSession]:
        """结束会话，归档到已完成列表。"""
        session = self._active_sessions.pop(run_id, None)
        if session:
            session.finished_at = time.time()
            self._completed_sessions.append(session)
        return session

    @property
    def active_sessions(self) -> list[RunCostSession]:
        return list(self._active_sessions.values())

    def get_session(self, run_id: str) -> Optional[RunCostSession]:
        """获取会话（先查活跃，再查已完成）。"""
        if run_id in self._active_sessions:
            return self._active_sessions[run_id]
        for s in self._completed_sessions:
            if s.run_id == run_id:
                return s
        return None

    # ── 记录 ────────────────────────────────────────────────────────────────

    def record(self, model: str, usage: dict | Any, run_id: str = "") -> float:
        """记录一次调用成本。"""
        if isinstance(usage, dict):
            inp = usage.get("prompt_tokens", usage.get("input_tokens", 0))
            out = usage.get("completion_tokens", usage.get("output_tokens", 0))
            cached = usage.get("cached_tokens", 0)
        else:
            inp = getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0)
            out = getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0)
            cached = getattr(usage, "cached_tokens", 0)

        pricing = PRICING.get(model)
        if not pricing:
            return 0.0

        # 长上下文缓存折扣（input > 1K tokens 时可享受 cache 折扣）
        cache_discount = 0.0
        if inp >= _PROMPT_CACHE_MIN_TOKENS and pricing.cached_input_per_1m > 0:
            cache_discount = (inp / 1_000_000) * (pricing.input_per_1m - pricing.cached_input_per_1m)
            cost_effective_input = inp * pricing.cached_input_per_1m / pricing.input_per_1m
        else:
            cost_effective_input = inp

        cost = (
            (cost_effective_input / 1_000_000) * pricing.input_per_1m
            + (out / 1_000_000) * pricing.output_per_1m
        )

        record = UsageRecord(
            model=model,
            input_tokens=inp,
            output_tokens=out,
            cached_tokens=cached,
            timestamp=time.time(),
            cost_usd=cost,
            run_id=run_id,
        )
        self.records.append(record)

        # 关联到活跃 session
        if run_id and run_id in self._active_sessions:
            self._active_sessions[run_id].records.append(record)

        # 预算告警
        if self.budget_limit and self.total_cost > self.budget_limit * 0.8:
            if self._on_budget_warning:
                self._on_budget_warning(self.total_cost, self.budget_limit)

        return cost

    def record_with_cache(
        self, model: str, input_tokens: int, output_tokens: int, run_id: str = "",
    ) -> float:
        """直接使用 token 数记录成本（用于 LLM response 后的精确追踪）。"""
        usage_data = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
        }
        return self.record(model, usage_data, run_id=run_id)

    # ── 查询 ────────────────────────────────────────────────────────────────

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def total_tokens(self) -> dict:
        inp = sum(r.input_tokens for r in self.records)
        out = sum(r.output_tokens for r in self.records)
        return {"input": inp, "output": out, "total": inp + out}

    def cost_by_model(self) -> dict[str, float]:
        costs: dict[str, float] = {}
        for r in self.records:
            costs[r.model] = costs.get(r.model, 0) + r.cost_usd
        return costs

    def cost_by_session(self) -> dict[str, float]:
        """按 run_id 汇总成本。"""
        costs: dict[str, float] = {}
        for r in self.records:
            rid = r.run_id or "unknown"
            costs[rid] = costs.get(rid, 0) + r.cost_usd
        return costs

    def summary(self) -> str:
        lines = [f"总成本: ${self.total_cost:.4f}"]
        for model, cost in self.cost_by_model().items():
            lines.append(f"  {model}: ${cost:.4f}")
        t = self.total_tokens
        lines.append(f"总Token: {t['total']:,} (输入 {t['input']:,} / 输出 {t['output']:,})")
        if self.budget_limit:
            pct = self.total_cost / self.budget_limit * 100
            lines.append(f"预算使用: {pct:.1f}% (${self.total_cost:.2f} / ${self.budget_limit:.2f})")
        return "\n".join(lines)

    def session_summary(self) -> str:
        """所有 session 的汇总。"""
        lines: list[str] = []
        for sid, cost in self.cost_by_session().items():
            session = self.get_session(sid)
            if session:
                lines.append(session.summary())
            else:
                lines.append(f"Run {sid[:8]}...: ${cost:.4f}")
        return "\n".join(lines) if lines else "No sessions."

    @staticmethod
    def noop():
        return CostTracker()

    def reset(self):
        self.records.clear()
        self._active_sessions.clear()
        self._completed_sessions.clear()

    def on_budget_warning(self, callback):
        self._on_budget_warning = callback
