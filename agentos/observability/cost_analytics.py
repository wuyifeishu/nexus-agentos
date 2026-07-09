"""
AgentOS v0.70 — 成本分析与运营仪表板。
基因来源: OpenAI Usage Dashboard + Grafana

提供:
- 按模型/按天/按session的多维度成本统计
- Token消耗趋势分析
- 预算预警系统
- 成本预测（简单滑动平均）
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from agentos.cost.tracker import PRICING, CostTracker


@dataclass
class CostEntry:
    """单次调用的成本记录。"""

    timestamp: float
    model: str
    session_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: float = 0.0


@dataclass
class DailySummary:
    """日成本摘要。"""

    date: str
    model: str
    calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_duration_ms: float = 0.0


@dataclass
class CostBreakdown:
    """单次调用的详细成本分解。"""

    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float
    token_cost_ratio: str = ""  # e.g. "1:2.5"

    def __post_init__(self):
        if self.output_cost_usd > 0:
            r = self.input_cost_usd / self.output_cost_usd
            self.token_cost_ratio = f"1:{r:.1f}" if r > 1 else f"{1/r:.1f}:1"


@dataclass
class CostSession:
    """单次会话的成本摘要。"""

    session_id: str
    model: str = ""
    calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    status: str = "active"


@dataclass
class BudgetAlert:
    """预算告警。"""

    triggered: bool
    current_cost: float
    budget: float
    pct_used: float
    projected_daily: float
    message: str


class CostAnalytics:
    """
    成本分析引擎 — 多维度聚合、趋势、预算管理。
    """

    def __init__(
        self,
        cost_tracker: CostTracker,
        budget_monthly: float = 0.0,
        warn_threshold: float = 0.8,
        persist_path: str = "",
    ):
        self.tracker = cost_tracker
        self.budget_monthly = budget_monthly
        self.warn_threshold = warn_threshold
        self.persist_path = persist_path
        self._entries: list[CostEntry] = []
        self._lock = threading.Lock()
        self._load()

    def record(
        self,
        model: str,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float = 0.0,
    ):
        """记录一次调用成本。"""
        price = PRICING.get(model, {})
        cost = input_tokens / 1_000_000 * price.get(
            "input", 0
        ) + output_tokens / 1_000_000 * price.get("output", 0)
        entry = CostEntry(
            timestamp=time.time(),
            model=model,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
        )
        with self._lock:
            self._entries.append(entry)

        # Periodic save (every 50 entries)
        if len(self._entries) % 50 == 0:
            self._save()

    # ── 按模型汇总 ───────────────────────────────

    def by_model(self, hours: float = 24.0) -> list[dict]:
        """最近N小时的模型成本分布。"""
        cutoff = time.time() - hours * 3600
        agg: dict[str, dict] = defaultdict(
            lambda: {
                "model": "",
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }
        )
        with self._lock:
            for e in self._entries:
                if e.timestamp < cutoff:
                    continue
                d = agg[e.model]
                d["model"] = e.model
                d["calls"] += 1
                d["input_tokens"] += e.input_tokens
                d["output_tokens"] += e.output_tokens
                d["cost_usd"] += e.cost_usd

        return sorted(agg.values(), key=lambda x: x["cost_usd"], reverse=True)

    # ── 按天汇总 ────────────────────────────────

    def daily_breakdown(self, days: int = 7) -> list[DailySummary]:
        """最近N天的每日成本明细。"""
        from datetime import datetime

        datetime.now().date()
        summaries: dict[tuple[str, str], DailySummary] = {}

        with self._lock:
            for e in self._entries:
                d = datetime.fromtimestamp(e.timestamp).strftime("%Y-%m-%d")
                key = (d, e.model)
                if key not in summaries:
                    summaries[key] = DailySummary(date=d, model=e.model)
                s = summaries[key]
                s.calls += 1
                s.total_input_tokens += e.input_tokens
                s.total_output_tokens += e.output_tokens
                s.total_cost_usd += e.cost_usd
                if s.avg_duration_ms == 0:
                    s.avg_duration_ms = e.duration_ms
                else:
                    s.avg_duration_ms = (s.avg_duration_ms + e.duration_ms) / 2

        # Sort by date desc, model
        result = sorted(summaries.values(), key=lambda x: (x.date, x.model), reverse=True)
        return result

    # ── 按Session汇总 ────────────────────────────

    def by_session(self, top_n: int = 10) -> list[dict]:
        """最贵的N个session。"""
        agg: dict[str, dict] = defaultdict(
            lambda: {"session_id": "", "calls": 0, "cost_usd": 0.0, "tokens": 0}
        )
        with self._lock:
            for e in self._entries:
                d = agg[e.session_id]
                d["session_id"] = e.session_id
                d["calls"] += 1
                d["cost_usd"] += e.cost_usd
                d["tokens"] += e.input_tokens + e.output_tokens

        sorted_sessions = sorted(agg.values(), key=lambda x: x["cost_usd"], reverse=True)
        return sorted_sessions[:top_n]

    # ── 趋势分析 ─────────────────────────────────

    def trend(self, metric: str = "cost", window: int = 7) -> list[dict]:
        """
        趋势分析（滑动平均）。
        metric: cost | tokens | calls
        """
        daily = self.daily_breakdown(days=window * 2)
        # Aggregate by date
        by_date: dict[str, dict] = defaultdict(
            lambda: {"date": "", "cost": 0.0, "tokens": 0, "calls": 0}
        )
        for s in daily:
            d = by_date[s.date]
            d["date"] = s.date
            d["cost"] += s.total_cost_usd
            d["tokens"] += s.total_input_tokens + s.total_output_tokens
            d["calls"] += s.calls

        dates = sorted(by_date.keys())[-window * 2 :]
        values = [by_date[d].get(metric, 0) for d in dates]

        # Simple moving average (window=3)
        trend_data = []
        for i, d in enumerate(dates):
            w_start = max(0, i - 2)
            w_vals = values[w_start : i + 1]
            trend_data.append(
                {
                    "date": d,
                    "value": values[i],
                    "sma": sum(w_vals) / len(w_vals),
                }
            )
        return trend_data

    # ── 预算预警 ─────────────────────────────────

    def check_budget(self) -> BudgetAlert:
        """检查预算是否超过阈值。"""
        if self.budget_monthly <= 0:
            return BudgetAlert(False, self.tracker.total_cost, 0, 0, 0, "")

        current = self.tracker.total_cost
        pct = current / self.budget_monthly

        # Projection: based on past 7 days average
        daily_data = self.daily_breakdown(days=7)
        daily_costs = defaultdict(float)
        for s in daily_data:
            daily_costs[s.date] += s.total_cost_usd
        if daily_costs:
            avg_daily = sum(daily_costs.values()) / len(daily_costs)
        else:
            avg_daily = 0

        from datetime import datetime

        days_left = 31 - datetime.now().day
        projected = avg_daily * max(days_left, 1)

        triggered = pct > self.warn_threshold
        message = ""
        if triggered:
            projected_total = current + projected
            message = (
                f"成本告警: 已消耗 ${current:.4f} ({pct:.0%})，" f"预计月末 ${projected_total:.4f}"
            )

        return BudgetAlert(
            triggered=triggered,
            current_cost=current,
            budget=self.budget_monthly,
            pct_used=pct,
            projected_daily=avg_daily,
            message=message,
        )

    # ── Summary ──────────────────────────────────

    @property
    def total_cost(self) -> float:
        return self.tracker.total_cost

    @property
    def total_calls(self) -> int:
        with self._lock:
            return len(self._entries)

    def summary(self) -> str:
        models = self.by_model(hours=24)
        lines = [
            f"总成本: ${self.total_cost:.4f}",
            f"总调用: {self.total_calls} 次",
            "",
            "最近24h模型分布:",
        ]
        for m in models[:5]:
            lines.append(
                f"  {m['model']}: ${m['cost_usd']:.4f} "
                f"({m['calls']}次, {m['input_tokens']}+{m['output_tokens']} tokens)"
            )
        if self.budget_monthly > 0:
            alert = self.check_budget()
            lines.append(f"\n月度预算: ${self.budget_monthly:.2f} (已用 {alert.pct_used:.1%})")
            if alert.triggered:
                lines.append(f"  {alert.message}")
        return "\n".join(lines)

    # ── 详细分解 ─────────────────────────────────

    def get_breakdown(self, session_id: str = "", hours: float = 24.0) -> list[CostBreakdown]:
        """获取指定会话或最近的详细成本分解。"""
        cutoff = time.time() - hours * 3600
        results = []
        with self._lock:
            entries = self._entries
            if session_id:
                entries = [e for e in entries if e.session_id == session_id]
            for e in entries:
                if e.timestamp < cutoff:
                    continue
                price = PRICING.get(e.model, {})
                input_cost = e.input_tokens / 1_000_000 * price.get("input", 0)
                output_cost = e.output_tokens / 1_000_000 * price.get("output", 0)
                results.append(
                    CostBreakdown(
                        model=e.model,
                        input_tokens=e.input_tokens,
                        output_tokens=e.output_tokens,
                        input_cost_usd=input_cost,
                        output_cost_usd=output_cost,
                        total_cost_usd=e.cost_usd,
                    )
                )
        return sorted(results, key=lambda x: x.total_cost_usd, reverse=True)

    def get_session(self, session_id: str) -> CostSession | None:
        """获取指定会话的成本摘要。"""
        with self._lock:
            matches = [e for e in self._entries if e.session_id == session_id]
            if not matches:
                return None
            models = set(e.model for e in matches)
            timestamps = [e.timestamp for e in matches]
            total_input = sum(e.input_tokens for e in matches)
            total_output = sum(e.output_tokens for e in matches)
            total_cost = sum(e.cost_usd for e in matches)
            return CostSession(
                session_id=session_id,
                model=", ".join(sorted(models)),
                calls=len(matches),
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                total_cost_usd=total_cost,
                start_time=min(timestamps),
                end_time=max(timestamps),
            )

    # ── Scores 成本关联 ──────────────────────────

    def cost_by_score_tier(self, scores: dict[float, list[str]]) -> dict[str, float]:
        """按评分层级聚合成本（与 ScoringEngine 联动）。"""
        tiers = {}
        for score, session_ids in scores.items():
            tier_name = f"score_{score:.1f}"
            tier_cost = 0.0
            with self._lock:
                for e in self._entries:
                    if e.session_id in session_ids:
                        tier_cost += e.cost_usd
            tiers[tier_name] = tier_cost
        return tiers

    # ── Persistence ──────────────────────────────

    def _save(self):
        if not self.persist_path:
            return
        try:
            data = []
            with self._lock:
                for e in self._entries[-10000:]:  # Keep last 10k
                    data.append(
                        {
                            "ts": e.timestamp,
                            "model": e.model,
                            "session_id": e.session_id,
                            "input_tokens": e.input_tokens,
                            "output_tokens": e.output_tokens,
                            "cost_usd": e.cost_usd,
                            "duration_ms": e.duration_ms,
                        }
                    )
            os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
            with open(self.persist_path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _load(self):
        if not self.persist_path or not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path) as f:
                data = json.load(f)
            with self._lock:
                self._entries = [
                    CostEntry(
                        timestamp=d["ts"],
                        model=d["model"],
                        session_id=d["session_id"],
                        input_tokens=d["input_tokens"],
                        output_tokens=d["output_tokens"],
                        cost_usd=d["cost_usd"],
                        duration_ms=d.get("duration_ms", 0),
                    )
                    for d in data
                ]
        except Exception:
            pass
