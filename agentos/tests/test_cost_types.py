"""Tests for agentos/cost.py — re-exported cost data types."""

from agentos.cost import CostEstimate, ModelFamily, TokenCount, TokenCounter


class TestModelFamily:
    def test_all_families_reachable(self):
        assert ModelFamily.GPT4 is not None
        assert ModelFamily.GPT4O is not None
        assert ModelFamily.GPT35 is not None

    def test_all_families_exist(self):
        assert ModelFamily.GPT4.value == "gpt-4"
        assert ModelFamily.GPT4O.value == "gpt-4o"
        assert ModelFamily.UNKNOWN.value == "unknown"


class TestTokenCount:
    def test_defaults(self):
        tc = TokenCount()
        assert tc.prompt_tokens == 0
        assert tc.completion_tokens == 0
        assert tc.total_tokens == 0
        assert tc.model == ""

    def test_custom_values(self):
        tc = TokenCount(prompt_tokens=100, completion_tokens=50, total_tokens=150, model="gpt-4o")
        assert tc.prompt_tokens == 100
        assert tc.completion_tokens == 50
        assert tc.total_tokens == 150
        assert tc.model == "gpt-4o"

    def test_importable_from_cost_module(self):
        assert TokenCount is not None


class TestCostEstimate:
    def test_default_total_is_zero(self):
        ce = CostEstimate()
        assert ce.total_cost == 0.0
        assert ce.prompt_cost == 0.0
        assert ce.completion_cost == 0.0
        assert ce.currency == "USD"

    def test_custom_total(self):
        ce = CostEstimate(total_cost=0.0042)
        assert ce.total_cost == 0.0042


class TestCostModuleTokenCounter:
    def test_token_counter_exists(self):
        assert TokenCounter is not None

    def test_token_counter_instantiable(self):
        tc = TokenCounter()
        assert isinstance(tc, TokenCounter)
