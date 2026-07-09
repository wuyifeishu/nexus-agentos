"""Tests for agentos.core.cost_tracker."""
import pytest

from agentos.core.cost_tracker import (
    BudgetAction,
    BudgetExceededError,
    BudgetLimit,
    CostTracker,
    ModelPricing,
    PricingRegistry,
)


class TestPricingRegistry:
    def test_get_known_model(self):
        pricing = PricingRegistry.get("gpt-4o")
        assert pricing is not None
        assert pricing.provider == "openai"

    def test_alias_resolution(self):
        pricing = PricingRegistry.get("gpt4o")
        assert pricing is not None
        assert pricing.model_id == "gpt-4o"

    def test_get_unknown_model(self):
        pricing = PricingRegistry.get("non-existent-model-999")
        assert pricing is None

    def test_list_providers(self):
        providers = PricingRegistry.list_providers()
        assert "openai" in providers
        assert "anthropic" in providers

    def test_list_models(self):
        models = PricingRegistry.list_models()
        assert len(models) >= 10
        assert "gpt-4o" in models


class TestModelPricing:
    def test_cost_calculation(self):
        pricing = ModelPricing("test", "test", input_price_per_1m=2.0, output_price_per_1m=10.0)
        cost = pricing.cost(input_tokens=1000, output_tokens=500)
        assert cost == pytest.approx(0.007, abs=0.001)

    def test_cost_zero_tokens(self):
        pricing = ModelPricing("test", "test", 2.0, 10.0)
        cost = pricing.cost(0, 0)
        assert cost == 0.0

    def test_cached_input_discount(self):
        pricing = ModelPricing("test", "test", 2.0, 10.0, cached_input_price_per_1m=0.5)
        cost = pricing.cost(input_tokens=1000, output_tokens=500, cached_input_tokens=500)
        # 500 cached @ 0.5 + 500 regular @ 2.0 (input) + 500 output @ 10.0
        expected = (500/1e6)*0.5 + (500/1e6)*2.0 + (500/1e6)*10.0
        assert cost == pytest.approx(expected, abs=0.0001)


class TestCostTracker:
    def test_record_with_known_model(self):
        tracker = CostTracker()
        can_proceed = tracker.record(
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
        )
        assert can_proceed is True
        assert tracker.total_cost > 0

    def test_record_with_unknown_model(self):
        tracker = CostTracker()
        tracker.record(
            model="fake-model",
            input_tokens=1000,
            output_tokens=500,
        )
        assert tracker.total_cost == 0.0

    def test_total_tokens(self):
        tracker = CostTracker()
        tracker.record(model="gpt-4o", input_tokens=100, output_tokens=50)
        tracker.record(model="gpt-4o", input_tokens=200, output_tokens=100)
        assert tracker.total_tokens == 450

    def test_model_costs(self):
        tracker = CostTracker()
        tracker.record(model="gpt-4o", input_tokens=1000, output_tokens=500)
        tracker.record(model="gpt-4o-mini", input_tokens=1000, output_tokens=500)
        costs = tracker.get_model_costs()
        assert len(costs) == 2

    def test_user_costs(self):
        tracker = CostTracker()
        tracker.record(model="gpt-4o", input_tokens=1000, output_tokens=500, user_id="alice")
        tracker.record(model="gpt-4o", input_tokens=500, output_tokens=200, user_id="bob")
        costs = tracker.get_user_costs()
        assert "alice" in costs
        assert "bob" in costs

    def test_tenant_costs(self):
        tracker = CostTracker()
        tracker.record(model="gpt-4o", input_tokens=1000, output_tokens=500, tenant_id="org_a")
        costs = tracker.get_tenant_costs()
        assert "org_a" in costs

    def test_usage_summary(self):
        tracker = CostTracker()
        tracker.record(model="gpt-4o", input_tokens=1000, output_tokens=500)
        summary = tracker.get_usage_summary()
        assert "total_cost_usd" in summary
        assert "total_tokens" in summary
        assert "total_requests" in summary
        assert summary["total_requests"] == 1

    def test_export_json(self):
        tracker = CostTracker()
        tracker.record(model="gpt-4o", input_tokens=1000, output_tokens=500)
        exported = tracker.export_json()
        assert "summary" in exported
        assert "records" in exported

    def test_export_csv(self):
        tracker = CostTracker()
        tracker.record(model="gpt-4o", input_tokens=1000, output_tokens=500)
        csv = tracker.export_csv()
        lines = csv.strip().split("\n")
        assert len(lines) == 2  # header + 1 record
        assert "model" in lines[0]

    def test_reset(self):
        tracker = CostTracker()
        tracker.record(model="gpt-4o", input_tokens=1000, output_tokens=500)
        tracker.reset()
        assert tracker.total_cost == 0.0
        assert tracker.total_tokens == 0
        assert len(tracker.get_recent_usage()) == 0


class TestBudgetManagement:
    def test_within_budget(self):
        tracker = CostTracker()
        budget = BudgetLimit("daily", max_usd=1.0, action=BudgetAction.WARN)
        tracker.set_budget("daily", budget)
        can_proceed = tracker.record(model="gpt-4o", input_tokens=1000, output_tokens=500)
        assert can_proceed is True

    def test_exceeded_budget(self):
        tracker = CostTracker()
        budget = BudgetLimit("daily", max_usd=0.000001, action=BudgetAction.BLOCK)
        tracker.set_budget("daily", budget)
        can_proceed = tracker.record(model="gpt-4o", input_tokens=100000, output_tokens=50000)
        assert can_proceed is False

    def test_budget_remaining(self):
        budget = BudgetLimit("monthly", max_usd=100.0)
        budget.add_spend(30.0)
        assert budget.remaining == pytest.approx(70.0)

    def test_budget_usage_ratio(self):
        budget = BudgetLimit("test", max_usd=100.0)
        assert budget.usage_ratio == 0.0
        budget.add_spend(50.0)
        assert budget.usage_ratio == 0.5

    def test_list_budgets(self):
        tracker = CostTracker()
        tracker.set_budget("a", BudgetLimit("a", 10.0))
        tracker.set_budget("b", BudgetLimit("b", 20.0))
        assert len(tracker.list_budgets()) == 2


class TestBudgetExceededError:
    def test_error_message(self):
        err = BudgetExceededError("daily", 15.0, 10.0)
        assert "daily" in str(err)
        assert "15.0" in str(err) or "15" in str(err)
        assert "10.0" in str(err) or "10" in str(err)
