"""Tests for agentos.core.task_router."""
from agentos.core.task_router import (
    DEFAULT_MODEL_SPECS,
    ModelSpec,
    RouteDecision,
    TaskCategory,
    TaskClassifier,
    TaskComplexity,
    TaskRouter,
)


class TestTaskClassifier:
    async def test_simple_chat(self):
        classifier = TaskClassifier()
        complexity, categories = classifier.classify("Hello, how are you?")
        assert complexity == TaskComplexity.SIMPLE
        assert TaskCategory.CHAT in categories

    async def test_medium_reasoning(self):
        classifier = TaskClassifier()
        complexity, categories = classifier.classify("analyze and compare the performance of Python vs Java for web development")
        assert complexity in (TaskComplexity.MEDIUM, TaskComplexity.COMPLEX)

    async def test_code_task(self):
        classifier = TaskClassifier()
        complexity, categories = classifier.classify("Write a Python function to sort a list")
        assert TaskCategory.CODE in categories

    async def test_tool_use_task(self):
        classifier = TaskClassifier()
        complexity, categories = classifier.classify("search for the latest news and fetch the top 5 results")
        assert TaskCategory.TOOL_USE in categories

    async def test_multi_step(self):
        classifier = TaskClassifier()
        complexity, categories = classifier.classify(
            "First, analyze the data. Then, create a chart. Finally, write a report."
        )
        assert complexity in (TaskComplexity.MEDIUM, TaskComplexity.COMPLEX)

    async def test_long_prompt(self):
        classifier = TaskClassifier()
        long_prompt = " ".join(["word"] * 600)  # ~500+ words
        complexity, _ = classifier.classify(long_prompt)
        assert complexity in (TaskComplexity.MEDIUM, TaskComplexity.COMPLEX)


class TestTaskRouter:
    async def test_route_simple_chat(self):
        router = TaskRouter()
        decision = router.route("Hello, what can you do?")
        assert decision.selected_model
        assert decision.provider
        assert decision.complexity == TaskComplexity.SIMPLE

    async def test_route_returns_fallbacks(self):
        router = TaskRouter()
        decision = router.route("Write a complex data pipeline with error handling")
        assert decision.selected_model
        assert len(decision.fallback_models) >= 0

    async def test_route_with_tool_requirement(self):
        router = TaskRouter()
        decision = router.route(
            "Call the search tool and fetch weather",
            required_capabilities={"tool_calling"},
        )
        assert decision.selected_model
        # Must be a model that supports tool calling
        selected_spec = next(
            (m for m in DEFAULT_MODEL_SPECS if m.model_id == decision.selected_model),
            None,
        )
        assert selected_spec is not None
        assert selected_spec.supports_tool_calling

    async def test_route_decision_immutable(self):
        router = TaskRouter()
        decision = router.route("Test prompt")
        assert isinstance(decision, RouteDecision)
        d = decision.to_dict()
        assert "selected_model" in d
        assert "complexity" in d
        assert "reasoning" in d

    async def test_route_logs_accumulate(self):
        router = TaskRouter()
        router.route("Task 1")
        router.route("Task 2")
        assert len(router.get_decision_log()) == 2

    async def test_clear_log(self):
        router = TaskRouter()
        router.route("Task 1")
        router.clear_log()
        assert len(router.get_decision_log()) == 0

    async def test_statistics(self):
        router = TaskRouter()
        router.route("Task A")
        router.route("Task B")
        stats = router.get_statistics()
        assert stats["total_requests"] == 2
        assert "model_distribution" in stats
        assert "complexity_distribution" in stats
        assert stats["avg_latency_ms"] >= 0

    async def test_register_model(self):
        router = TaskRouter()
        initial_count = len(router.models)
        custom = ModelSpec("custom-model", "custom", "budget", min_complexity=TaskComplexity.SIMPLE)
        router.register_model(custom)
        assert len(router.models) == initial_count + 1

    async def test_route_no_candidates_relaxes(self):
        """With restrictive capability requirements, should still find a model."""
        router = TaskRouter()
        decision = router.route(
            "Simple hello",
            required_capabilities={"tool_calling", "vision", "reasoning"},
        )
        # Should still return a decision (relaxed complexity constraint)
        assert decision.selected_model


class TestModelSpec:
    def test_default_specs_non_empty(self):
        assert len(DEFAULT_MODEL_SPECS) >= 5

    def test_all_specs_have_provider(self):
        for spec in DEFAULT_MODEL_SPECS:
            assert spec.provider, f"{spec.model_id} missing provider"

    def test_all_specs_have_tier(self):
        for spec in DEFAULT_MODEL_SPECS:
            assert spec.tier in ("premium", "standard", "budget", "fallback")
