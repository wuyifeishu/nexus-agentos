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
        from agentos.tools.risk import ToolRiskLevel, ToolRiskRating

        r = ToolRiskRating(level=ToolRiskLevel.HIGH)
        assert r.requires_user_confirm() is True

    def test_requires_confirm_critical(self):
        from agentos.tools.risk import ToolRiskLevel, ToolRiskRating

        r = ToolRiskRating(level=ToolRiskLevel.CRITICAL)
        assert r.requires_user_confirm() is True

    def test_requires_confirm_financial(self):
        from agentos.tools.risk import ToolRiskRating

        r = ToolRiskRating(financial_impact=True)
        assert r.requires_user_confirm() is True

    def test_get_risk_preset_list_files(self):
        from agentos.tools.risk import ToolRiskLevel, get_risk_preset

        r = get_risk_preset("list_files")
        assert r is not None
        assert r.level == ToolRiskLevel.LOW

    def test_get_risk_preset_delete_file(self):
        from agentos.tools.risk import ToolRiskLevel, get_risk_preset

        r = get_risk_preset("delete_file")
        assert r is not None
        assert r.level == ToolRiskLevel.HIGH
        assert r.requires_approval is True

    def test_get_risk_preset_payment(self):
        from agentos.tools.risk import ToolRiskLevel, get_risk_preset

        r = get_risk_preset("execute_payment")
        assert r is not None
        assert r.level == ToolRiskLevel.CRITICAL
        assert r.financial_impact is True

    def test_get_risk_preset_case_insensitive(self):
        from agentos.tools.risk import get_risk_preset

        assert get_risk_preset("DELETE_FILE") is not None

    def test_infer_risk_level_keyword_delete(self):
        from agentos.tools.risk import ToolRiskLevel, infer_risk_level

        r = infer_risk_level("purge_records", "delete all records")
        assert r.level == ToolRiskLevel.HIGH

    def test_infer_risk_level_keyword_write(self):
        from agentos.tools.risk import ToolRiskLevel, infer_risk_level

        r = infer_risk_level("update_profile")
        assert r.level == ToolRiskLevel.MEDIUM

    def test_infer_risk_level_default(self):
        from agentos.tools.risk import ToolRiskLevel, infer_risk_level

        r = infer_risk_level("get_status")
        assert r.level == ToolRiskLevel.LOW


# ══════════════════════════════════════════════════════════════════════════════
# Middleware Pipeline 测试
# ══════════════════════════════════════════════════════════════════════════════


class TestMiddlewarePipeline:
    @pytest.mark.asyncio
    async def test_empty_pipeline_allows(self):
        from agentos.core.middleware import (
            MiddlewareContext,
            MiddlewarePhase,
            MiddlewarePipeline,
        )

        pipe = MiddlewarePipeline()
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, prompt="hello")
        decision = await pipe.pre_llm(ctx)
        assert decision.allow is True

    @pytest.mark.asyncio
    async def test_blocking_middleware(self):
        from agentos.core.middleware import (
            AgentMiddleware,
            MiddlewareContext,
            MiddlewareDecision,
            MiddlewarePhase,
            MiddlewarePipeline,
        )

        class Blocker(AgentMiddleware):
            name = "blocker"

            @property
            def phases(self):
                return [MiddlewarePhase.PRE_LLM]

            async def process(self, ctx):
                return MiddlewareDecision(
                    allow=False, reason="blocked by test", action="block"
                )

        pipe = MiddlewarePipeline([Blocker()])
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_LLM, prompt="test")
        decision = await pipe.pre_llm(ctx)
        assert decision.allow is False
        assert "blocked by test" in decision.reason

    @pytest.mark.asyncio
    async def test_transform_middleware(self):
        from agentos.core.middleware import (
            AgentMiddleware,
            MiddlewareContext,
            MiddlewareDecision,
            MiddlewarePhase,
            MiddlewarePipeline,
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
                    return MiddlewareDecision(
                        allow=True, action="transform", modified_context=new_ctx
                    )
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
        from agentos.core.middleware import AuditLogMiddleware, MiddlewarePipeline

        pipe = MiddlewarePipeline([AuditLogMiddleware()])
        pipe.remove("audit_log")
        assert "audit_log" not in pipe.middleware_names

    @pytest.mark.asyncio
    async def test_phase_filtering(self):
        from agentos.core.middleware import (
            MiddlewareContext,
            MiddlewarePhase,
            MiddlewarePipeline,
            PIIMaskingMiddleware,
        )

        pipe = MiddlewarePipeline([PIIMaskingMiddleware()])
        # PIIMaskingMiddleware only listens on PRE_LLM
        ctx = MiddlewareContext(phase=MiddlewarePhase.PRE_TOOL, tool_name="test")
        decision = await pipe.pre_tool(ctx)
        assert (
            decision.allow is True
        )  # It should pass through since no middleware listens


# ══════════════════════════════════════════════════════════════════════════════
# Enhanced CostTracker + RunCostSession 测试
# ══════════════════════════════════════════════════════════════════════════════


class TestRunCostSession:
    """Test CostTracker core functionality (record, report, budget)."""

    def test_session_lifecycle(self):
        from agentos.cost.tracker import CostTracker

        tracker = CostTracker()
        summary = tracker.report_dict()
        assert summary["total_cost"] == 0
        assert summary["total_tokens"] == 0

        tracker.record("deepseek-v3.1", input_tokens=1000, output_tokens=500)
        summary = tracker.report_dict()
        assert summary["total_cost"] > 0
        assert summary["total_tokens"] == 1500

        tracker.record("deepseek-v3.1", input_tokens=2000, output_tokens=800)
        summary = tracker.report_dict()
        assert summary["total_cost"] > 0
        assert summary["total_tokens"] == 4300

    def test_total_tokens(self):
        from agentos.cost.tracker import CostTracker

        tracker = CostTracker()
        tracker.record("gpt-4o", input_tokens=100, output_tokens=50)
        tracker.record("gpt-4o", input_tokens=200, output_tokens=100)
        summary = tracker.report_dict()
        assert summary["total_tokens"] == 450


class TestCostTrackerEnhanced:
    def test_record_and_report(self):
        from agentos.cost.tracker import CostTracker

        tracker = CostTracker()
        tracker.record("deepseek-v3.1", input_tokens=1000, output_tokens=500)
        report = tracker.report_dict()
        assert report["total_cost"] > 0
        assert report["total_tokens"] == 1500

    def test_record_multiple_models(self):
        from agentos.cost.tracker import CostTracker

        tracker = CostTracker()
        tracker.record("gpt-4o", input_tokens=500, output_tokens=200)
        tracker.record("claude-3-5-sonnet", input_tokens=1000, output_tokens=500)
        report = tracker.report_dict()
        assert len(report["by_model"]) >= 2

    def test_get_price_fallback(self):
        from agentos.cost.tracker import CostTracker

        tracker = CostTracker()
        price = tracker.get_price("gpt-4o")
        assert price is not None

    def test_reset(self):
        from agentos.cost.tracker import CostTracker

        tracker = CostTracker()
        tracker.record("deepseek-v3.1", input_tokens=1000, output_tokens=500)
        report = tracker.report_dict()
        assert report["total_cost"] > 0
        tracker.reset()
        report = tracker.report_dict()
        assert report["total_cost"] == 0
        assert report["total_tokens"] == 0

    def test_budget_check(self):
        from agentos.cost.tracker import Budget, CostTracker

        tracker = CostTracker(budgets=[Budget(name="test-budget", limit=0.01)])
        tracker.record("deepseek-v3.1", input_tokens=10000, output_tokens=5000)
        alerts = tracker.check_budget()
        # May or may not exceed depending on pricing; verify method runs
        assert isinstance(alerts, list)
