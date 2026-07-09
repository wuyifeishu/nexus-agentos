"""Comprehensive tests for agentos/cost/token_counter.py."""

import pytest

from agentos.cost.token_counter import (
    PRICING_TABLE,
    CostEstimate,
    ModelFamily,
    TokenCount,
    TokenCounter,
)


class TestModelFamily:
    def test_all_families_exist(self):
        assert ModelFamily.GPT4.value == "gpt-4"
        assert ModelFamily.GPT4O.value == "gpt-4o"
        assert ModelFamily.GPT35.value == "gpt-3.5-turbo"
        assert ModelFamily.CLAUDE3.value == "claude-3"
        assert ModelFamily.CLAUDE35.value == "claude-3.5"
        assert ModelFamily.GEMINI.value == "gemini"
        assert ModelFamily.LLAMA.value == "llama"
        assert ModelFamily.MIXTRAL.value == "mixtral"
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


class TestCostEstimate:
    def test_defaults(self):
        ce = CostEstimate()
        assert ce.prompt_cost == 0.0
        assert ce.completion_cost == 0.0
        assert ce.total_cost == 0.0
        assert ce.currency == "USD"
        assert ce.token_count is None

    def test_with_token_count(self):
        tc = TokenCount(prompt_tokens=1000, total_tokens=1000)
        ce = CostEstimate(
            prompt_cost=0.0025,
            completion_cost=0.0,
            total_cost=0.0025,
            token_count=tc,
        )
        assert ce.prompt_cost == 0.0025
        assert ce.total_cost == 0.0025
        assert ce.token_count.prompt_tokens == 1000


class TestPricingTable:
    def test_major_models_have_pricing(self):
        assert "gpt-4o" in PRICING_TABLE
        assert "gpt-4o-mini" in PRICING_TABLE
        assert "gpt-4" in PRICING_TABLE
        assert "gpt-3.5-turbo" in PRICING_TABLE
        assert "claude-3.5-sonnet" in PRICING_TABLE
        assert "gemini-1.5-pro" in PRICING_TABLE
        assert "gemini-2.0-flash" in PRICING_TABLE

    def test_pricing_is_tuple_of_two_floats(self):
        for model, pricing in PRICING_TABLE.items():
            assert isinstance(pricing, tuple), f"{model} pricing not tuple"
            assert len(pricing) == 2, f"{model} pricing length != 2"
            assert isinstance(pricing[0], (int, float)), f"{model} input price not numeric"
            assert isinstance(pricing[1], (int, float)), f"{model} output price not numeric"


class TestTokenCounterInit:
    def test_initializes_without_error(self):
        counter = TokenCounter()
        assert isinstance(counter, TokenCounter)

    def test_usage_log_starts_empty(self):
        counter = TokenCounter()
        assert counter._usage_log == []

    def test_reset_usage_clears_log(self):
        counter = TokenCounter()
        counter.count("hello")
        assert len(counter._usage_log) == 1
        counter.reset_usage()
        assert len(counter._usage_log) == 0


class TestTokenCounterCount:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.counter = TokenCounter()

    def test_count_short_text(self):
        tc = self.counter.count("hello", model="gpt-4o")
        assert tc.prompt_tokens > 0
        assert tc.total_tokens > 0
        assert tc.model == "gpt-4o"

    def test_count_empty_text(self):
        tc = self.counter.count("", model="gpt-4o")
        assert tc.prompt_tokens >= 0
        assert tc.total_tokens >= 0

    def test_count_long_text(self):
        long_text = "hello world " * 500
        tc = self.counter.count(long_text, model="gpt-4o")
        assert tc.total_tokens > 50

    def test_count_different_models(self):
        for model in ["gpt-4o", "gpt-4", "gpt-3.5-turbo", "claude-3.5-sonnet", "gemini-1.5-pro"]:
            tc = self.counter.count("The quick brown fox jumps over the lazy dog.", model=model)
            assert tc.model == model
            assert tc.total_tokens > 0

    def test_count_logs_usage(self):
        assert len(self.counter._usage_log) == 0
        self.counter.count("first")
        assert len(self.counter._usage_log) == 1
        self.counter.count("second")
        assert len(self.counter._usage_log) == 2

    def test_count_unknown_model_falls_back(self):
        tc = self.counter.count("hello", model="nonexistent-model-xyz")
        assert tc.total_tokens > 0
        assert tc.model == "nonexistent-model-xyz"


class TestTokenCounterCountMessages:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.counter = TokenCounter()

    def test_single_message(self):
        msgs = [{"role": "user", "content": "Hello, how are you?"}]
        tc = self.counter.count_messages(msgs, model="gpt-4o")
        assert tc.prompt_tokens > 0
        assert tc.model == "gpt-4o"

    def test_multiple_messages(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
        ]
        tc = self.counter.count_messages(msgs, model="gpt-4o")
        assert tc.prompt_tokens > 0

    def test_empty_message_content(self):
        msgs = [{"role": "user", "content": ""}]
        tc = self.counter.count_messages(msgs)
        assert tc.prompt_tokens >= 0

    def test_messages_log_to_usage(self):
        msgs = [{"role": "user", "content": "test"}]
        self.counter.count_messages(msgs)
        assert len(self.counter._usage_log) >= 1


class TestTokenCounterEstimateCost:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.counter = TokenCounter()

    def test_estimate_cost_gpt4o(self):
        tc = TokenCount(prompt_tokens=1000, total_tokens=1000, model="gpt-4o")
        cost = self.counter.estimate_cost(tc)
        assert cost.total_cost > 0
        assert cost.currency == "USD"
        assert cost.prompt_cost > 0

    def test_estimate_cost_gpt4o_mini_is_cheaper(self):
        tc = TokenCount(prompt_tokens=1_000_000, total_tokens=1_000_000, model="gpt-4o-mini")
        cost = self.counter.estimate_cost(tc)
        # gpt-4o-mini input: $0.15/1M
        assert 0.10 < cost.prompt_cost < 0.20

    def test_estimate_cost_with_model_override(self):
        tc = TokenCount(prompt_tokens=1_000_000, total_tokens=1_000_000, model="gpt-4o")
        cost = self.counter.estimate_cost(tc, model="gpt-4o-mini")
        assert 0.10 < cost.total_cost < 0.20

    def test_estimate_cost_zero_tokens(self):
        tc = TokenCount()
        cost = self.counter.estimate_cost(tc)
        assert cost.total_cost == 0.0

    def test_estimate_cost_unknown_model_default_pricing(self):
        tc = TokenCount(prompt_tokens=1_000_000, total_tokens=1_000_000, model="unknown-model")
        cost = self.counter.estimate_cost(tc)
        # Default: (1.00, 3.00) per 1M
        assert 0.50 < cost.total_cost < 5.00

    def test_estimate_cost_with_completion_tokens(self):
        tc = TokenCount(
            prompt_tokens=500_000,
            completion_tokens=500_000,
            total_tokens=1_000_000,
            model="gpt-4o",
        )
        cost = self.counter.estimate_cost(tc)
        assert cost.prompt_cost > 0
        assert cost.completion_cost > 0
        assert cost.completion_cost > cost.prompt_cost  # output is more expensive


class TestTokenCounterClassifyModel:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.counter = TokenCounter()

    def test_classify_gpt4o(self):
        assert self.counter._classify_model("gpt-4o") == ModelFamily.GPT4O
        assert self.counter._classify_model("gpt-4o-mini") == ModelFamily.GPT4O

    def test_classify_gpt4(self):
        assert self.counter._classify_model("gpt-4") == ModelFamily.GPT4
        assert self.counter._classify_model("gpt-4-turbo") == ModelFamily.GPT4

    def test_classify_gpt35(self):
        assert self.counter._classify_model("gpt-3.5-turbo") == ModelFamily.GPT35

    def test_classify_claude35(self):
        assert self.counter._classify_model("claude-3.5-sonnet") == ModelFamily.CLAUDE35

    def test_classify_claude3(self):
        assert self.counter._classify_model("claude-3-opus") == ModelFamily.CLAUDE3
        assert self.counter._classify_model("claude-3-haiku") == ModelFamily.CLAUDE3

    def test_classify_gemini(self):
        assert self.counter._classify_model("gemini-1.5-pro") == ModelFamily.GEMINI
        assert self.counter._classify_model("gemini-2.0-flash") == ModelFamily.GEMINI

    def test_classify_llama(self):
        assert self.counter._classify_model("llama-3-70b") == ModelFamily.LLAMA

    def test_classify_mixtral(self):
        assert self.counter._classify_model("mixtral-8x7b") == ModelFamily.MIXTRAL

    def test_classify_unknown(self):
        assert self.counter._classify_model("random-model-123") == ModelFamily.UNKNOWN


class TestTokenCounterGetTotalUsage:
    def test_empty_log(self):
        counter = TokenCounter()
        total = counter.get_total_usage()
        assert total.prompt_tokens == 0
        assert total.completion_tokens == 0
        assert total.total_tokens == 0

    def test_aggregates_all_entries(self):
        counter = TokenCounter()
        counter.count("first call")
        counter.count("second call")
        counter.count("third call")
        total = counter.get_total_usage()
        assert total.prompt_tokens > 0
        assert total.total_tokens > 0

    def test_after_reset_returns_zero(self):
        counter = TokenCounter()
        counter.count("data")
        counter.reset_usage()
        total = counter.get_total_usage()
        assert total.total_tokens == 0


class TestTokenCounterGetTotalCost:
    def test_empty_log_zero_cost(self):
        counter = TokenCounter()
        cost = counter.get_total_cost()
        assert cost.total_cost == 0.0

    def test_accumulates_cost(self):
        counter = TokenCounter()
        counter.count("hello " * 100, model="gpt-4o")
        counter.count("world " * 100, model="gpt-4o")
        cost = counter.get_total_cost()
        assert cost.total_cost > 0


class TestTokenCounterFormatCost:
    def test_tiny_cost(self):
        ce = CostEstimate(total_cost=0.000123)
        result = TokenCounter.format_cost(ce)
        assert "$" in result
        assert len(result.split(".")[1]) >= 6

    def test_small_cost(self):
        ce = CostEstimate(total_cost=0.50)
        result = TokenCounter.format_cost(ce)
        assert "$" in result
        assert len(result.split(".")[1]) == 4

    def test_large_cost(self):
        ce = CostEstimate(total_cost=42.0)
        result = TokenCounter.format_cost(ce)
        assert result == "$42.00"


class TestTokenCounterFormatTokens:
    def test_small_count(self):
        tc = TokenCount(total_tokens=500)
        result = TokenCounter.format_tokens(tc)
        assert result == "500"

    def test_large_count(self):
        tc = TokenCount(total_tokens=2500)
        result = TokenCounter.format_tokens(tc)
        assert "2.5K" in result


class TestTokenCounterGetPricing:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.counter = TokenCounter()

    def test_exact_match(self):
        pricing = self.counter._get_pricing("gpt-4o")
        assert pricing == (2.50, 10.00)

    def test_prefix_match(self):
        pricing = self.counter._get_pricing("gpt-4o-2024-08-06")
        assert pricing == (2.50, 10.00)

    def test_unknown_model_default(self):
        pricing = self.counter._get_pricing("totally-unknown")
        assert pricing == (1.00, 3.00)
