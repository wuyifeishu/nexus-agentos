"""v1.1.4 新特性集成测试。"""
from __future__ import annotations

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# ToolRiskRating 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestToolRiskRating:
    def test_risk_level_enum(self):
        from agentos.tools.risk import ToolRiskLevel
        assert ToolRiskLevel.LOW.value == "low"
        assert ToolRiskLevel.CRITICAL.value == "critical"
        assert len(list(ToolRiskLevel)) == 4

    def test_risk_rating_defaults(self):
        from agentos.tools.risk import ToolRiskRating
        r = ToolRiskRating()
        assert r.level.value == "medium"
        assert r.reversible is True
        assert r.requires_approval is False
        assert r.requires_user_confirm() is False

    def test_requires_confirm_high(self):
        from agentos.tools.risk import ToolRiskRating, ToolRiskLevel
        r = ToolRiskRating(level=ToolRiskLevel.HIGH)
        assert r.requires_user_confirm() is True

    def test_requires_confirm_critical(self):
        from agentos.tools.risk import ToolRiskRating, ToolRiskLevel
        r = ToolRiskRating(level=ToolRiskLevel.CRITICAL)
        assert r.requires_user_confirm() is True

    def test_requires_confirm_financial(self):
        from agentos.tools.risk import ToolRiskRating
        r = ToolRiskRating(financial_impact=True)
        assert r.requires_user_confirm() is True

    def test_get_risk_preset_list_files(self):
        from agentos.tools.risk import get_risk_preset, ToolRiskLevel
        r = get_risk_preset("list_files")
        assert r is not None
        assert r.level == ToolRiskLevel.LOW

    def test_get_risk_preset_delete_file(self):
        from agentos.tools.risk import get_risk_preset, ToolRiskLevel
        r = get_risk_preset("delete_file")
        assert r is not None
        assert r.level == ToolRiskLevel.HIGH
        assert r.requires_approval is True

    def test_get_risk_preset_payment(self):
        from agentos.tools.risk import get_risk_preset, ToolRiskLevel
        r = get_risk_preset("execute_payment")
        assert r is not None
        assert r.level == ToolRiskLevel.CRITICAL
        assert r.financial_impact is True

    def test_get_risk_preset_case_insensitive(self):
        from agentos.tools.risk import get_risk_preset
        assert get_risk_preset("DELETE_FILE") is not None

    def test_infer_risk_level_keyword_delete(self):
        from agentos.tools.risk import infer_risk_level, ToolRiskLevel
        r = infer_risk_level("purge_records", "delete all records")
        assert r.level == ToolRiskLevel.HIGH

    def test_infer_risk_level_keyword_write(self):
        from agentos.tools.risk import infer_risk_level, ToolRiskLevel
        r = infer_risk_level("update_profile")
        assert r.level == ToolRiskLevel.MEDIUM

    def test_infer_risk_level_default(self):
        from agentos.tools.risk import infer_risk_level, ToolRiskLevel
        r = infer_risk_level("get_status")
        assert r.level == ToolRiskLevel.LOW


# ══════════════════════════════════════════════════════════════════════════════
# Middleware Pipeline 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestMiddlewarePipeline:
    @pytest.mark.asyncio
    async def test_empty_pipeline_allows(self):
        from agentos.core.middleware import MiddlewarePipeline, MiddlewarePhase, MiddlewareContext
        pipe = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, prompt="hello")
        decision = await pipe.pre_llm(ctx)
        assert decision.allow is True

    @pytest.mark.asyncio
    async def test_blocking_middleware(self):
        from agentos.core.middleware import (
            AgentMiddleware, MiddlewarePipeline, MiddlewarePhase,
            MiddlewareContext, MiddlewareDecision,
        )

        class Blocker(AgentMiddleware):
            name = "blocker"
            @property
            def phases(self):
                return [MiddlewarePhase.PRE_LLM]
            async def process(self, ctx):
                return MiddlewareDecision(allow=False, reason="blocked by test", action="block")

        pipe = MiddlewarePipeline([Blocker()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, prompt="test")
        decision = await pipe.pre_llm(ctx)
        assert decision.allow is False
        assert "blocked by test" in decision.reason

    @pytest.mark.asyncio
    async def test_transform_middleware(self):
        from agentos.core.middleware import (
            AgentMiddleware, MiddlewarePipeline, MiddlewarePhase,
            MiddlewareContext, MiddlewareDecision,
        )

        class UpperCaseTransform(AgentMiddleware):
            name = "upper"
            @property
            def phases(self):
                return [MiddlewarePhase.PRE_LLM]
            async def process(self, ctx):
                if ctx.prompt:
                    new_ctx = MiddlewareContext(**{**ctx.__dict__})
                    new_ctx.prompt = ctx.prompt.upper()
                    return MiddlewareDecision(allow=True, action="transform", modified_context=new_ctx)
                return MiddlewareDecision(allow=True)

        pipe = MiddlewarePipeline([UpperCaseTransform()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, prompt="hello")
        decision = await pipe.pre_llm(ctx)
        assert decision.allow is True
        assert decision.modified_context is not None
        assert decision.modified_context.prompt == "HELLO"

    @pytest.mark.asyncio
    async def test_chain_add(self):
        from agentos.core.middleware import MiddlewarePipeline
        pipe = MiddlewarePipeline()
        from agentos.core.middleware import AuditLogMiddleware
        pipe.add(AuditLogMiddleware())
        assert "audit_log" in pipe.middleware_names

    @pytest.mark.asyncio
    async def test_remove(self):
        from agentos.core.middleware import MiddlewarePipeline, AuditLogMiddleware
        pipe = MiddlewarePipeline([AuditLogMiddleware()])
        pipe.remove("audit_log")
        assert "audit_log" not in pipe.middleware_names

    @pytest.mark.asyncio
    async def test_phase_filtering(self):
        from agentos.core.middleware import (
            MiddlewarePipeline, MiddlewarePhase, MiddlewareContext, PIIMaskingMiddleware,
        )
        pipe = MiddlewarePipeline([PIIMaskingMiddleware()])
        # PIIMaskingMiddleware only listens on PRE_LLM
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_TOOL, tool_name="test")
        decision = await pipe.pre_tool(ctx)
        assert decision.allow is True  # It should pass through since no middleware listens


# ══════════════════════════════════════════════════════════════════════════════
# Enhanced CostTracker + RunCostSession 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestRunCostSession:
    def test_session_lifecycle(self):
        import time
        from agentos.cost.tracker import RunCostSession
        session = RunCostSession(run_id="test-123")
        assert session.run_id == "test-123"
        assert session.call_count == 0
        assert session.total_cost == 0

        # Record some usage
        from agentos.cost.tracker import UsageRecord
        session.records.append(UsageRecord(
            model="deepseek-v3.1", input_tokens=1000, output_tokens=500,
            cost_usd=0.01, run_id="test-123",
        ))
        session.records.append(UsageRecord(
            model="deepseek-v3.1", input_tokens=2000, output_tokens=800,
            cost_usd=0.02, run_id="test-123",
        ))
        session.finished_at = time.time()

        assert session.call_count == 2
        assert session.total_cost == 0.03
        assert session.duration_seconds > 0

    def test_total_tokens(self):
        from agentos.cost.tracker import RunCostSession, UsageRecord
        session = RunCostSession(run_id="t")
        session.records.append(UsageRecord(model="m", input_tokens=100, output_tokens=50, cost_usd=0.0))
        session.records.append(UsageRecord(model="m", input_tokens=200, output_tokens=100, cost_usd=0.0))
        assert session.total_tokens == {"input": 300, "output": 150, "total": 450}


class TestCostTrackerEnhanced:
    def test_start_end_session(self):
        from agentos.cost.tracker import CostTracker
        tracker = CostTracker()
        rid = tracker.start_session()
        assert len(tracker.active_sessions) == 1
        session = tracker.end_session(rid)
        assert session is not None
        assert session.finished_at is not None
        assert len(tracker.active_sessions) == 0

    def test_record_with_session(self):
        from agentos.cost.tracker import CostTracker
        tracker = CostTracker()
        rid = tracker.start_session()
        tracker.record("deepseek-v3.1", {"prompt_tokens": 1000, "completion_tokens": 500}, run_id=rid)
        tracker.record("deepseek-v3.1", {"prompt_tokens": 500, "completion_tokens": 200}, run_id=rid)
        session = tracker.end_session(rid)
        assert session.call_count == 2
        assert session.total_cost > 0

    def test_cost_by_session(self):
        from agentos.cost.tracker import CostTracker
        tracker = CostTracker()
        r1 = tracker.start_session()
        r2 = tracker.start_session()
        tracker.record("deepseek-v3.1", {"prompt_tokens": 1000, "completion_tokens": 100}, run_id=r1)
        tracker.record("deepseek-v3.1", {"prompt_tokens": 500, "completion_tokens": 50}, run_id=r2)
        costs = tracker.cost_by_session()
        assert r1 in costs
        assert r2 in costs
        assert costs[r2] < costs[r1]

    def test_get_session_active_and_completed(self):
        from agentos.cost.tracker import CostTracker
        tracker = CostTracker()
        rid = tracker.start_session()
        assert tracker.get_session(rid) is not None
        tracker.end_session(rid)
        assert tracker.get_session(rid) is not None  # Should find completed

    def test_record_with_cache(self):
        from agentos.cost.tracker import CostTracker
        tracker = CostTracker()
        cost = tracker.record_with_cache("deepseek-v3.1", 1000, 500)
        assert cost > 0
        assert tracker.total_cost == cost
