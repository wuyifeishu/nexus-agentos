"""Tests for agentos.core.cost_tracker — Token Accounting & Spend Management."""

from __future__ import annotations

import json
import time

import pytest

from agentos.core.cost_tracker import (
    BudgetAction,
    BudgetExceededError,
    BudgetLimit,
    CostTracker,
    ModelPricing,
    PricingRegistry,
    UsageRecord,
)

# ============================================================================
# ModelPricing
# ============================================================================

class TestModelPricing:
    def test_cost_calculation(self):
        p = ModelPricing("test-model", "test", input_price_per_1m=1.0, output_price_per_1m=2.0)
        cost = p.cost(input_tokens=1000, output_tokens=500)
        assert cost == pytest.approx(0.002)  # (1000/1M)*1 + (500/1M)*2

    def test_cost_zero_tokens(self):
        p = ModelPricing("test-model", "test", input_price_per_1m=10.0, output_price_per_1m=20.0)
        cost = p.cost(input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_cost_with_cached_input(self):
        p = ModelPricing(
            "test-model", "test",
            input_price_per_1m=10.0,
            output_price_per_1m=20.0,
            cached_input_price_per_1m=1.0,
        )
        cost = p.cost(input_tokens=1000, output_tokens=500, cached_input_tokens=600)
        # Regular input: 1000-600=400, cost = 400/1M*10 + 600/1M*1 + 500/1M*20
        expected = (400 / 1_000_000) * 10 + (600 / 1_000_000) * 1 + (500 / 1_000_000) * 20
        assert cost == pytest.approx(expected)

    def test_cost_no_cached_price_fallback(self):
        p = ModelPricing("test-model", "test", input_price_per_1m=10.0, output_price_per_1m=20.0)
        cost = p.cost(input_tokens=1000, output_tokens=500, cached_input_tokens=100)
        # No cached price → ignores cached_input_tokens
        assert cost == pytest.approx((1000 / 1_000_000) * 10 + (500 / 1_000_000) * 20)


# ============================================================================
# PricingRegistry
# ============================================================================

class TestPricingRegistry:
    def test_get_known_model(self):
        pricing = PricingRegistry.get("gpt-4o")
        assert pricing is not None
        assert pricing.model_id == "gpt-4o"
        assert pricing.provider == "openai"

    def test_get_alias(self):
        pricing = PricingRegistry.get("gpt4o")
        assert pricing is not None
        assert pricing.model_id == "gpt-4o"

    def test_get_unknown_model(self):
        pricing = PricingRegistry.get("nonexistent-model-12345")
        assert pricing is None

    def test_register_custom_pricing(self):
        custom = ModelPricing("my-custom-model", "my-provider", 0.01, 0.02)
        PricingRegistry.register(custom)
        retrieved = PricingRegistry.get("my-custom-model")
        assert retrieved is not None
        assert retrieved.input_price_per_1m == 0.01
        assert retrieved.output_price_per_1m == 0.02

    def test_list_providers(self):
        providers = PricingRegistry.list_providers()
        assert "openai" in providers
        assert "anthropic" in providers
        assert "deepseek" in providers

    def test_list_models_all(self):
        models = PricingRegistry.list_models()
        assert "gpt-4o" in models
        assert "claude-sonnet-4-20250514" in models

    def test_list_models_by_provider(self):
        models = PricingRegistry.list_models(provider="openai")
        assert all(PricingRegistry.get(m).provider == "openai" for m in models)

    def test_deepseek_alias(self):
        pricing = PricingRegistry.get("deepseek")
        assert pricing is not None
        assert pricing.model_id == "deepseek-chat"

    def test_deepseek_r1_alias(self):
        pricing = PricingRegistry.get("deepseek-r1")
        assert pricing is not None
        assert pricing.model_id == "deepseek-reasoner"


# ============================================================================
# BudgetLimit
# ============================================================================

class TestBudgetLimit:
    def test_initial_state(self):
        budget = BudgetLimit(name="test", max_usd=100.0)
        assert budget._spent == 0.0
        assert budget.remaining == 100.0
        assert budget.usage_ratio == 0.0

    def test_add_spend_within_budget(self):
        budget = BudgetLimit(name="test", max_usd=100.0)
        assert budget.add_spend(30.0) is True
        assert budget._spent == 30.0
        assert budget.remaining == 70.0

    def test_add_spend_exceeds_budget(self):
        budget = BudgetLimit(name="test", max_usd=100.0)
        budget.add_spend(90.0)
        assert budget.add_spend(20.0) is False
        assert budget._spent == 110.0
        assert budget.remaining == 0.0

    def test_usage_ratio(self):
        budget = BudgetLimit(name="test", max_usd=100.0)
        budget.add_spend(25.0)
        assert budget.usage_ratio == 0.25

    def test_reset_if_expired_not_expired(self):
        budget = BudgetLimit(name="test", max_usd=100.0, period_seconds=3600)
        budget.add_spend(50.0)
        budget.reset_if_expired()
        assert budget._spent == 50.0  # Not reset because not expired

    def test_reset_if_expired_expired(self):
        budget = BudgetLimit(
            name="test", max_usd=100.0, period_seconds=0
        )  # period_seconds=0 means instantly expired
        budget.add_spend(50.0)
        time.sleep(0.01)
        budget.reset_if_expired()
        assert budget._spent == 0.0

    def test_alert_callback(self):
        alerts = []

        def on_alert(**kwargs):
            alerts.append(kwargs)

        budget = BudgetLimit(
            name="test",
            max_usd=100.0,
            alert_thresholds=[0.5, 0.75],
            alert_callback=on_alert,
        )
        budget.add_spend(60.0)  # Crosses 0.5
        assert len(alerts) == 1
        assert alerts[0]["threshold"] == 0.5

        budget.add_spend(20.0)  # Crosses 0.75
        assert len(alerts) == 2
        assert alerts[1]["threshold"] == 0.75

    def test_budget_action_enum(self):
        assert BudgetAction.BLOCK.value == "block"
        assert BudgetAction.WARN.value == "warn"
        assert BudgetAction.THROTTLE.value == "throttle"


# ============================================================================
# UsageRecord
# ============================================================================

class TestUsageRecord:
    def test_default_values(self):
        r = UsageRecord(model="gpt-4o", input_tokens=100, output_tokens=50)
        assert r.model == "gpt-4o"
        assert r.input_tokens == 100
        assert r.output_tokens == 50
        assert r.cached_input_tokens == 0
        assert r.cost_usd == 0.0
        assert r.user_id is None
        assert r.timestamp > 0


# ============================================================================
# CostTracker
# ============================================================================

class TestCostTracker:
    @pytest.fixture
    def tracker(self):
        return CostTracker()

    def test_record_known_model(self, tracker):
        result = tracker.record("gpt-4o", input_tokens=1000, output_tokens=500)
        assert result is True
        assert tracker.total_cost > 0
        assert tracker.total_tokens == 1500

    def test_record_unknown_model(self, tracker):
        result = tracker.record("nonexistent-model", input_tokens=100, output_tokens=50)
        assert result is True
        assert tracker.total_cost == 0.0  # Unknown model = no cost
        assert tracker.total_tokens == 150

    def test_record_with_user(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50, user_id="user_1")
        user_costs = tracker.get_user_costs()
        assert "user_1" in user_costs
        assert user_costs["user_1"] > 0

    def test_record_with_tenant(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50, tenant_id="tenant_a")
        tenant_costs = tracker.get_tenant_costs()
        assert "tenant_a" in tenant_costs
        assert tenant_costs["tenant_a"] > 0

    def test_record_multiple_models(self, tracker):
        tracker.record("gpt-4o", input_tokens=100, output_tokens=50)
        tracker.record("gpt-4o-mini", input_tokens=200, output_tokens=100)
        model_costs = tracker.get_model_costs()
        assert "gpt-4o" in model_costs
        assert "gpt-4o-mini" in model_costs

    def test_record_budget_exceeded(self, tracker):
        tracker.set_budget("test", BudgetLimit(name="test", max_usd=0.001))
        # GPT-4o costs will exceed this
        result = tracker.record("gpt-4", input_tokens=100000, output_tokens=100000)
        assert result is False  # Budget exceeded

    def test_noop_tracker(self):
        t = CostTracker.noop()
        result = t.record("gpt-4o", input_tokens=1000000, output_tokens=1000000)
        assert result is True

    def test_set_get_remove_budget(self, tracker):
        budget = BudgetLimit(name="daily", max_usd=50.0)
        tracker.set_budget("daily", budget)
        assert tracker.get_budget("daily") is budget
        tracker.remove_budget("daily")
        assert tracker.get_budget("daily") is None

    def test_budget_auto_reset_on_record(self, tracker):
        tracker.set_budget("test", BudgetLimit(name="test", max_usd=10.0, period_seconds=3600))
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50)
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50)
        assert tracker.total_cost > 0

    def test_get_recent_usage(self, tracker):
        for i in range(5):
            tracker.record("gpt-4o-mini", input_tokens=10, output_tokens=5)
        recent = tracker.get_recent_usage(limit=3)
        assert len(recent) == 3

    def test_get_usage_summary(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50, user_id="u1")
        tracker.set_budget("daily", BudgetLimit(name="daily", max_usd=100.0))
        summary = tracker.get_usage_summary()
        assert "total_cost_usd" in summary
        assert "total_tokens" in summary
        assert "total_requests" in summary
        assert summary["total_requests"] == 1
        assert "budgets" in summary
        assert "daily" in summary["budgets"]

    def test_export_json(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50)
        exported = tracker.export_json()
        data = json.loads(exported)
        assert "summary" in data
        assert "records" in data
        assert len(data["records"]) == 1

    def test_export_csv(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50)
        csv_output = tracker.export_csv()
        lines = csv_output.strip().split("\n")
        assert len(lines) == 2  # header + 1 record
        assert "model,input_tokens" in lines[0]

    def test_reset(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50)
        tracker.set_budget("daily", BudgetLimit(name="daily", max_usd=100.0))
        tracker.get_budget("daily").add_spend(10.0)
        tracker.reset()
        assert tracker.total_cost == 0.0
        assert tracker.total_tokens == 0
        assert tracker.get_recent_usage() == []
        assert tracker.get_budget("daily")._spent == 0.0

    def test_list_budgets(self, tracker):
        tracker.set_budget("b1", BudgetLimit(name="b1", max_usd=10.0))
        tracker.set_budget("b2", BudgetLimit(name="b2", max_usd=20.0))
        budgets = tracker.list_budgets()
        assert len(budgets) == 2
        assert "b1" in budgets
        assert "b2" in budgets

    def test_record_with_metadata(self, tracker):
        result = tracker.record(
            "gpt-4o-mini",
            input_tokens=50, output_tokens=25,
            metadata={"session": "sess_1", "purpose": "test"},
        )
        recent = tracker.get_recent_usage(1)
        assert recent[0].metadata["session"] == "sess_1"

    def test_record_with_request_id(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=10, output_tokens=5, request_id="req_abc")
        recent = tracker.get_recent_usage(1)
        assert recent[0].request_id == "req_abc"

    def test_multiple_user_costs(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50, user_id="u1")
        tracker.record("gpt-4o-mini", input_tokens=200, output_tokens=100, user_id="u2")
        costs = tracker.get_user_costs()
        assert "u1" in costs
        assert "u2" in costs
        assert costs["u2"] > costs["u1"]

    def test_same_model_aggregates(self, tracker):
        tracker.record("gpt-4o-mini", input_tokens=100, output_tokens=50)
        tracker.record("gpt-4o-mini", input_tokens=200, output_tokens=100)
        model_costs = tracker.get_model_costs()
        assert len(model_costs) == 1
        assert model_costs["gpt-4o-mini"] > 0


# ============================================================================
# BudgetExceededError
# ============================================================================

class TestBudgetExceededError:
    def test_error_message(self):
        err = BudgetExceededError("daily", spent=150.0, limit=100.0)
        assert "daily" in str(err)
        assert "150" in str(err) or "150.00" in str(err)
        assert "100" in str(err) or "100.00" in str(err)

    def test_error_attributes(self):
        err = BudgetExceededError("monthly", spent=500.0, limit=200.0)
        assert err.budget_name == "monthly"
        assert err.spent == 500.0
        assert err.limit == 200.0
