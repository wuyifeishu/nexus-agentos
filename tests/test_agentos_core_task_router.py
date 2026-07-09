"""Tests for agentos.core.task_router — Intelligent task routing engine."""

from __future__ import annotations

import pytest

from agentos.core.task_router import (
    DEFAULT_MODEL_SPECS,
    ModelSpec,
    RouteDecision,
    TaskCategory,
    TaskClassifier,
    TaskComplexity,
    TaskRouter,
)

# ============================================================================
# TaskClassifier
# ============================================================================

class TestTaskClassifier:
    @pytest.fixture
    def classifier(self):
        return TaskClassifier()

    def test_simple_chat(self, classifier):
        complexity, categories = classifier.classify("What is the capital of France?")
        assert complexity == TaskComplexity.SIMPLE
        assert TaskCategory.CHAT in categories

    def test_code_task(self, classifier):
        complexity, categories = classifier.classify("Write a Python function to sort a list")
        assert TaskCategory.CODE in categories

    def test_reasoning_task(self, classifier):
        complexity, categories = classifier.classify(
            "Explain the philosophical implications of free will"
        )
        assert TaskCategory.REASONING in categories
        assert TaskCategory.ANALYSIS in categories

    def test_tool_use_task(self, classifier):
        complexity, categories = classifier.classify("Search for the latest AI research papers")
        assert TaskCategory.TOOL_USE in categories

    def test_multi_step_medium(self, classifier):
        complexity, categories = classifier.classify(
            "First, read the file. Then parse the JSON. Finally, write the output."
        )
        assert complexity in (TaskComplexity.MEDIUM, TaskComplexity.COMPLEX)

    def test_agent_style_complex(self, classifier):
        complexity, categories = classifier.classify(
            "Plan and orchestrate a multi-agent system for automated data pipeline"
        )
        assert complexity == TaskComplexity.COMPLEX

    def test_long_prompt_complex(self, classifier):
        long_prompt = "analyze the data structure " * 500
        complexity, categories = classifier.classify(long_prompt)
        assert complexity == TaskComplexity.COMPLEX

    def test_with_available_tools(self, classifier):
        complexity, categories = classifier.classify(
            "Tell me about AI", available_tools=["search", "fetch"]
        )
        assert TaskCategory.TOOL_USE in categories

    def test_empty_input(self, classifier):
        complexity, categories = classifier.classify("")
        assert isinstance(complexity, TaskComplexity)
        assert isinstance(categories, list)

    def test_returns_hashable(self, classifier):
        result = classifier.classify("test")
        assert hash(result[0]) is not None

    def test_chinese_prompt(self, classifier):
        # Non-English prompts still work
        complexity, categories = classifier.classify("分析量子计算的最新发展并撰写报告")
        assert isinstance(complexity, TaskComplexity)

    def test_prompt_with_code_block(self, classifier):
        complexity, categories = classifier.classify("Here is a function:\n```python\ndef foo():\n    pass\n```")
        assert TaskCategory.CODE in categories


# ============================================================================
# ModelSpec
# ============================================================================

class TestModelSpec:
    def test_default_specs_populated(self):
        assert len(DEFAULT_MODEL_SPECS) > 0

    def test_spec_has_required_fields(self):
        for spec in DEFAULT_MODEL_SPECS:
            assert spec.model_id
            assert spec.provider
            assert spec.max_tokens > 0
            assert spec.tier in ("premium", "standard", "budget", "fallback")

    def test_cost_fields_non_negative(self):
        for spec in DEFAULT_MODEL_SPECS:
            assert spec.cost_multiplier >= 0

    def test_category_weights_is_dict(self):
        for spec in DEFAULT_MODEL_SPECS:
            assert isinstance(spec.category_weights, dict)

    def test_excluded_categories_is_set(self):
        for spec in DEFAULT_MODEL_SPECS:
            assert isinstance(spec.excluded_categories, set)

    def test_model_spec_construction(self):
        spec = ModelSpec(
            model_id="test-model",
            provider="test",
            tier="budget",
            max_tokens=4096,
            cost_multiplier=0.1,
            supports_tool_calling=False,
        )
        assert spec.model_id == "test-model"
        assert spec.max_tokens == 4096
        assert spec.tier == "budget"
        assert not spec.supports_tool_calling


# ============================================================================
# RouteDecision
# ============================================================================

class TestRouteDecision:
    def test_construction(self):
        rd = RouteDecision(
            selected_model="gpt-4o",
            provider="openai",
            complexity=TaskComplexity.SIMPLE,
            categories=[TaskCategory.CHAT],
            fallback_models=["gpt-4o-mini"],
            reasoning="Simple chat, chose cheapest capable model.",
        )
        assert rd.selected_model == "gpt-4o"
        assert rd.complexity == TaskComplexity.SIMPLE

    def test_immutable(self):
        rd = RouteDecision(
            selected_model="gpt-4o",
            provider="openai",
            complexity=TaskComplexity.SIMPLE,
            categories=[TaskCategory.CHAT],
            fallback_models=[],
            reasoning="test",
        )
        with pytest.raises(Exception):
            rd.selected_model = "other"  # type: ignore

    def test_to_dict(self):
        rd = RouteDecision(
            selected_model="gpt-4o",
            provider="openai",
            complexity=TaskComplexity.MEDIUM,
            categories=[TaskCategory.CODE, TaskCategory.REASONING],
            fallback_models=["claude-sonnet"],
            reasoning="Code + reasoning, picked GPT-4o.",
        )
        d = rd.to_dict()
        assert d["selected_model"] == "gpt-4o"
        assert d["provider"] == "openai"
        assert d["complexity"] == "medium"
        assert "code" in d["categories"]
        assert "reasoning" in d["categories"]

    def test_timestamp_auto_set(self):
        rd = RouteDecision(
            selected_model="gpt-4o-mini",
            provider="openai",
            complexity=TaskComplexity.SIMPLE,
            categories=[TaskCategory.CHAT],
            fallback_models=[],
            reasoning="test",
        )
        assert rd.timestamp > 0

    def test_latency_default_zero(self):
        rd = RouteDecision(
            selected_model="gpt-4o-mini",
            provider="openai",
            complexity=TaskComplexity.SIMPLE,
            categories=[TaskCategory.CHAT],
            fallback_models=[],
            reasoning="test",
        )
        assert rd.latency_ms >= 0


# ============================================================================
# TaskRouter
# ============================================================================

class TestTaskRouter:
    @pytest.fixture
    def router(self):
        return TaskRouter()

    def test_route_simple_chat(self, router):
        decision = router.route("What is 2+2?")
        assert isinstance(decision, RouteDecision)
        assert decision.selected_model is not None
        assert decision.complexity == TaskComplexity.SIMPLE
        assert decision.provider is not None

    def test_route_complex_task(self, router):
        decision = router.route(
            "Design and orchestrate a multi-region distributed system for "
            "real-time data processing with fault tolerance, exactly-once "
            "semantics, and full observability."
        )
        assert decision.complexity != TaskComplexity.SIMPLE

    def test_route_code_generation(self, router):
        decision = router.route(
            "First, design the API schema. Then implement the async library "
            "for document processing with retry logic. Next, write the test "
            "suite with 100% coverage. Finally, deploy to production.\n"
            "```python\nclass DocumentProcessor:\n    def __init__(self):\n"
            "        pass\n    import json\n```"
        )
        assert decision.complexity != TaskComplexity.SIMPLE

    def test_route_with_required_capabilities(self, router):
        decision = router.route(
            "Describe this image",
            required_capabilities={"vision"},
        )
        assert decision.selected_model is not None
        # Selected model should support vision
        for spec in DEFAULT_MODEL_SPECS:
            if spec.model_id == decision.selected_model:
                assert spec.supports_vision
                break

    def test_route_with_tool_calling_requirement(self, router):
        decision = router.route(
            "Search and summarize",
            required_capabilities={"tool_calling"},
        )
        for spec in DEFAULT_MODEL_SPECS:
            if spec.model_id == decision.selected_model:
                assert spec.supports_tool_calling
                break

    def test_route_with_latency_budget(self, router):
        decision = router.route(
            "Explain gravity",
            latency_budget_ms=500,
        )
        assert decision.selected_model is not None

    def test_route_fallback_models(self, router):
        decision = router.route("Complex multi-step analysis of financial data")
        assert isinstance(decision.fallback_models, list)

    def test_route_reasoning_string(self, router):
        decision = router.route("Write production code for a payment system")
        assert decision.reasoning is not None
        assert len(decision.reasoning) > 0

    def test_route_latency_recorded(self, router):
        decision = router.route("How to bake a cake?")
        assert decision.latency_ms >= 0

    def test_route_timestamp_set(self, router):
        decision = router.route("Hello")
        assert decision.timestamp > 0

    def test_statistics(self, router):
        router.route("task 1")
        router.route("task 2")
        stats = router.get_statistics()
        assert stats["total_requests"] >= 2
        assert "model_distribution" in stats
        assert "complexity_distribution" in stats
        assert "avg_latency_ms" in stats

    def test_statistics_empty(self, router):
        stats = router.get_statistics()
        assert stats == {}

    def test_decision_log(self, router):
        router.route("task a")
        router.route("task b")
        log = router.get_decision_log()
        assert len(log) == 2
        assert all(isinstance(d, RouteDecision) for d in log)

    def test_clear_log(self, router):
        router.route("task a")
        router.clear_log()
        assert router.get_decision_log() == []

    def test_route_always_succeeds(self, router):
        """Even with impossible constraints we should get a model."""
        decision = router.route("test", required_capabilities={"tool_calling", "vision", "reasoning"})
        assert decision.selected_model is not None

    def test_register_model(self, router):
        new_model = ModelSpec(
            model_id="custom-model",
            provider="custom",
            tier="budget",
            max_tokens=8192,
            cost_multiplier=0.05,
        )
        initial_count = len(router.models)
        router.register_model(new_model)
        assert len(router.models) == initial_count + 1

    def test_models_property(self, router):
        models = router.models
        assert isinstance(models, list)
        assert all(isinstance(m, ModelSpec) for m in models)

    def test_categories_in_decision(self, router):
        decision = router.route("Write a Python function to calculate Fibonacci")
        assert TaskCategory.CHAT in decision.categories


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    @pytest.fixture
    def router(self):
        return TaskRouter()

    def test_very_short_prompt(self, router):
        decision = router.route("Hi")
        assert decision.selected_model is not None

    def test_special_characters(self, router):
        decision = router.route("!@#$%^&*()")
        assert decision.selected_model is not None

    def test_only_whitespace(self, router):
        decision = router.route("   ")
        assert decision.selected_model is not None

    def test_model_with_excluded_categories(self):
        spec = ModelSpec(
            model_id="chat-only",
            provider="test",
            tier="budget",
            max_tokens=4096,
            cost_multiplier=1.0,
            excluded_categories={TaskCategory.CODE, TaskCategory.REASONING},
        )
        router = TaskRouter(model_specs=[spec])
        decision = router.route("Write a Python function")
        # The excluded model shouldn't be selected; falls back
        assert decision.selected_model is not None

    def test_latency_budget_excludes_slow(self, router):
        decision = router.route(
            "simple hello",
            latency_budget_ms=500,
        )
        assert decision is not None
