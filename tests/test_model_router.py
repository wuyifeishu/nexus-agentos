"""AgentOS v1.5.0 - ModelRouter 全覆盖测试。

覆盖 agentos/agent/model_router.py 全部路径。
"""

from __future__ import annotations

import time

from agentos.agent.model_router import (
    DEFAULT_MODELS,
    ModelRouter,
    ModelSpec,
    RequestSpec,
    RouteResult,
    TaskComplexity,
    TaskPriority,
)

# ---- enums ----

def test_task_complexity_values():
    assert TaskComplexity.TRIVIAL.value == 0
    assert TaskComplexity.SIMPLE.value == 1
    assert TaskComplexity.MODERATE.value == 2
    assert TaskComplexity.COMPLEX.value == 3
    assert TaskComplexity.EXPERT.value == 4


def test_task_priority_values():
    assert TaskPriority.LOW.value == 0
    assert TaskPriority.NORMAL.value == 1
    assert TaskPriority.HIGH.value == 2
    assert TaskPriority.CRITICAL.value == 3


# ---- ModelSpec ----

def test_model_spec_defaults():
    m = ModelSpec("gpt-4", "openai", 1.0, 2.0)
    assert m.name == "gpt-4"
    assert m.provider == "openai"
    assert m.cost_per_1k_input == 1.0
    assert m.cost_per_1k_output == 2.0
    assert m.max_tokens == 4096
    assert m.context_window == 128000
    assert m.min_complexity == TaskComplexity.TRIVIAL
    assert m.tags == []


def test_model_spec_with_tags():
    m = ModelSpec("x", "y", 0.1, 0.2, tags=["fast", "cheap"])
    assert m.tags == ["fast", "cheap"]


# ---- RequestSpec ----

def test_request_spec_minimal():
    r = RequestSpec(100, 50, TaskComplexity.SIMPLE, TaskPriority.NORMAL)
    assert r.estimated_input_tokens == 100
    assert r.estimated_output_tokens == 50
    assert r.complexity == TaskComplexity.SIMPLE
    assert r.priority == TaskPriority.NORMAL
    assert r.task_id == ""
    assert r.session_id == ""


def test_request_spec_full():
    r = RequestSpec(200, 100, TaskComplexity.COMPLEX, TaskPriority.HIGH, "t1", "s1")
    assert r.task_id == "t1"
    assert r.session_id == "s1"


# ---- RouteResult ----

def test_route_result_defaults():
    m = ModelSpec("x", "p", 0, 0)
    r = RouteResult(success=True, model=m)
    assert r.success is True
    assert r.model is m
    assert r.reason == ""
    assert r.estimated_cost == 0.0
    assert r.fallback_chain == []


# ---- ModelRouter init ----

def test_router_init():
    m = ModelSpec("x", "p", 0, 0)
    router = ModelRouter([m], daily_budget_usd=100.0)
    assert len(router.models) == 1
    assert router._daily_budget == 100.0
    assert router._daily_spent == 0.0
    assert router._request_count == 0


def test_router_with_defaults():
    router = ModelRouter.with_defaults()
    assert len(router.models) == len(DEFAULT_MODELS)
    assert router._daily_budget == 50.0


# ---- route: basic ----

def test_route_trivial_task():
    router = ModelRouter.with_defaults()
    spec = RequestSpec(100, 50, TaskComplexity.TRIVIAL, TaskPriority.NORMAL)
    result = router.route(spec)
    assert result.success is True
    assert result.model is not None
    assert result.estimated_cost >= 0


def test_route_expert_task():
    router = ModelRouter.with_defaults()
    spec = RequestSpec(2000, 1000, TaskComplexity.EXPERT, TaskPriority.NORMAL)
    result = router.route(spec)
    assert result.success is True


def test_route_high_priority_uses_best_tag():
    router = ModelRouter.with_defaults()
    # Tiny token count so best-tagged models fit under COMPLEX budget (0.20)
    spec = RequestSpec(10, 10, TaskComplexity.COMPLEX, TaskPriority.HIGH)
    result = router.route(spec)
    assert result.success
    assert "best" in result.model.tags


def test_route_critical_priority_uses_best_tag():
    router = ModelRouter.with_defaults()
    spec = RequestSpec(10, 10, TaskComplexity.COMPLEX, TaskPriority.CRITICAL)
    result = router.route(spec)
    assert result.success
    assert "best" in result.model.tags


# ---- route: session affinity ----

def test_route_session_affinity():
    router = ModelRouter.with_defaults()
    spec1 = RequestSpec(100, 50, TaskComplexity.SIMPLE, TaskPriority.NORMAL, session_id="s1")
    r1 = router.route(spec1)
    assert r1.success

    spec2 = RequestSpec(100, 50, TaskComplexity.SIMPLE, TaskPriority.NORMAL, session_id="s1")
    r2 = router.route(spec2)
    assert r2.model.name == r1.model.name
    assert "Session affinity" in r2.reason


def test_route_session_affinity_over_budget():
    router = ModelRouter([ModelSpec("gpt-4o", "openai", 2.5, 10.0)], daily_budget_usd=0.001)
    spec1 = RequestSpec(100, 50, TaskComplexity.SIMPLE, TaskPriority.NORMAL, session_id="s2")
    r1 = router.route(spec1)
    # Force daily_spent up
    router.record_request(r1.model.name, cost_usd=1000)
    spec2 = RequestSpec(100, 50, TaskComplexity.SIMPLE, TaskPriority.NORMAL, session_id="s2")
    r2 = router.route(spec2)
    # Session affinity would exceed budget, so it re-routes
    assert r2.success


# ---- route: no candidates → cheapest fallback ----

def test_route_no_candidates_fallback():
    """When no model supports TRIVIAL (only EXPERT models), falls back to cheapest."""
    cheap = ModelSpec("tiny", "local", 0.0, 0.0, min_complexity=TaskComplexity.EXPERT)
    router = ModelRouter([cheap])
    spec = RequestSpec(100, 50, TaskComplexity.TRIVIAL, TaskPriority.NORMAL)
    result = router.route(spec)
    assert result.success


# ---- route: budget constraint → fallback chain ----

def test_route_budget_exhausted_fallback_to_cheapest():
    m = ModelSpec("gpt-4o", "openai", 2.50, 10.0)
    cheap = ModelSpec("free-model", "ollama", 0.001, 0.001, min_complexity=TaskComplexity.TRIVIAL)
    router = ModelRouter([m, cheap], daily_budget_usd=0.00001)  # nearly 0 budget
    router.record_request("x", cost_usd=10)  # exhaust budget
    spec = RequestSpec(10000, 5000, TaskComplexity.COMPLEX, TaskPriority.NORMAL)
    result = router.route(spec)
    assert result.success
    assert "constrained" in result.reason.lower()


def test_route_model_exceeds_complexity_budget_adds_to_fallback():
    """est_cost > max_budget — falls through to 'no model fits' path."""
    m = ModelSpec("expensive", "p", 100.0, 100.0)
    router = ModelRouter([m], daily_budget_usd=1000)
    spec = RequestSpec(1000, 1000, TaskComplexity.TRIVIAL, TaskPriority.NORMAL)
    result = router.route(spec)
    assert result.success
    assert "expensive" in result.fallback_chain


def test_route_model_fits_complexity_but_exceeds_daily_budget():
    """est_cost <= max_budget but est_cost + daily_spent > daily_budget — false branch of 263."""
    m = ModelSpec("mid", "p", 0.001, 0.001)
    cheap = ModelSpec("free", "q", 0.0, 0.0)
    router = ModelRouter([m, cheap], daily_budget_usd=0.0001)
    router.record_request("x", cost_usd=100)  # exhaust budget
    spec = RequestSpec(1000, 1000, TaskComplexity.TRIVIAL, TaskPriority.NORMAL)
    result = router.route(spec)
    assert result.success
    assert "mid" in result.fallback_chain


def test_route_fits_both_budgets_returns_success():
    """est_cost <= max_budget AND est_cost + daily_spent <= daily_budget — true branch of 263."""
    m = ModelSpec("mid", "p", 0.001, 0.001)
    router = ModelRouter([m], daily_budget_usd=100)
    spec = RequestSpec(100, 50, TaskComplexity.TRIVIAL, TaskPriority.NORMAL)
    result = router.route(spec)
    assert result.success
    assert result.model.name == "mid"


def test_route_high_priority_no_best_tags_in_candidates():
    """HIGH priority where no candidate has 'best' tag — tier empty → 242->253, 244->253."""
    m1 = ModelSpec("slow", "x", 0.1, 0.1, tags=["slow"])
    m2 = ModelSpec("fast", "x", 0.2, 0.2, tags=["fast"])
    router = ModelRouter([m1, m2], daily_budget_usd=100)
    spec = RequestSpec(100, 50, TaskComplexity.SIMPLE, TaskPriority.HIGH)
    result = router.route(spec)
    assert result.success


# ---- record_request ----

def test_record_request():
    router = ModelRouter.with_defaults()
    router.record_request("gpt-4o", success=True, tokens_used=100, cost_usd=0.05, latency_ms=200)
    assert router._daily_spent == 0.05
    assert router._request_count >= 1


# ---- daily budget properties ----

def test_daily_budget_total():
    router = ModelRouter([], daily_budget_usd=42.0)
    assert router.daily_budget_total == 42.0


def test_daily_budget_remaining():
    router = ModelRouter.with_defaults(daily_budget_usd=100)
    router.record_request("x", cost_usd=30)
    assert router.daily_budget_remaining == 70.0


def test_daily_spent():
    router = ModelRouter.with_defaults(daily_budget_usd=100)
    router.record_request("x", cost_usd=15.5)
    assert router.daily_spent == 15.5


# ---- summary ----

def test_router_summary():
    router = ModelRouter.with_defaults()
    router.route(RequestSpec(100, 50, TaskComplexity.SIMPLE, TaskPriority.NORMAL, session_id="sum_sess"))
    s = router.summary()
    assert "models_available" in s
    assert "daily_budget_usd" in s
    assert "daily_spent" in s
    assert "daily_remaining" in s
    assert "request_count" in s
    assert "cached_sessions" in s
    assert s["cached_sessions"] >= 1


# ---- _maybe_reset_daily ----

def test_maybe_reset_daily():
    router = ModelRouter.with_defaults()
    router._daily_spent = 10.0
    router._day_start = time.time() - 90000  # > 86400s
    router._route_cache["s"] = "m"
    router._maybe_reset_daily()
    assert router._daily_spent == 0.0
    assert router._route_cache == {}


def test_maybe_reset_daily_not_elapsed():
    router = ModelRouter.with_defaults()
    router._daily_spent = 10.0
    router._route_cache["s"] = "m"
    router._maybe_reset_daily()
    assert router._daily_spent == 10.0
    assert router._route_cache == {"s": "m"}


# ---- _estimate_cost ----

def test_estimate_cost():
    m = ModelSpec("x", "p", 1.0, 2.0)
    router = ModelRouter([m])
    spec = RequestSpec(1000, 500, TaskComplexity.SIMPLE, TaskPriority.NORMAL)
    cost = router._estimate_cost(m, spec)
    assert cost == 1.0 * 1.0 + 0.5 * 2.0  # 1.0 + 1.0 = 2.0


# ---- DEFAULT_MODELS ----

def test_default_models_not_empty():
    assert len(DEFAULT_MODELS) >= 8


# ---- route: complexity budget map ----

def test_route_exceeds_complexity_budget():
    """Request too expensive for complexity budget → fallback."""
    m1 = ModelSpec("gpt-4o", "openai", 2.50, 10.0)
    m2 = ModelSpec("mini", "openai", 0.10, 0.50)
    router = ModelRouter([m1, m2], daily_budget_usd=1000)
    # TRIVIAL budget is 0.002, so a big request will fail the complexity cap
    spec = RequestSpec(100000, 100000, TaskComplexity.TRIVIAL, TaskPriority.NORMAL)
    result = router.route(spec)
    assert result.success
    # Falls back to cheapest
    assert result.model.name == "mini"
    assert len(result.fallback_chain) > 0
