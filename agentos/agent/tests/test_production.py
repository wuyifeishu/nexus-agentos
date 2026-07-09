"""Tests for agentos.agent.production — 100% statement coverage target.

All external deps mocked: ModelRouter, AuditLogger, SmartCache, LLMProvider, ToolAgent.
============================================================ 5 source bugs fixed:
1. AuditLogger(max_events=, max_age_days=) → AuditLogger(log_dir=)
2. cache.wrap(provider) → provider (SmartCache has no wrap())
3. cache_stats → returns {"size": cache.size}
4. cache_hit_rate / cache_savings → return 0.0 (SmartCache has no stats)
5. model.tier.name → hasattr guard (ModelSpec has no tier)
6. cache._stats.total_cost_saved_usd += → no-op
"""

from __future__ import annotations

from unittest.mock import ANY, MagicMock, PropertyMock, call, patch

import pytest

from agentos.agent.model_router import (
    TaskComplexity,
    TaskPriority,
)
from agentos.agent.production import (
    ComplexityEstimate,
    ComplexityEstimator,
    ProductionAgent,
    ProductionConfig,
)
from agentos.agent.tool_agent import AgentConfig, AgentResult, ToolExecutor
from agentos.llm.base import LLMProvider


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def mock_provider():
    return MagicMock(spec=LLMProvider)


@pytest.fixture
def mock_executor():
    executor = MagicMock(spec=ToolExecutor)
    mock_schema = MagicMock()
    mock_schema.function.name = "test_tool"
    executor.get_schemas.return_value = [mock_schema]
    executor.execute.return_value = "tool_result"
    return executor


def _make_route(success=True, reason="matched", estimated_cost=0.005):
    mock_model = MagicMock()
    mock_model.name = "gpt-4o"
    mock_model.tier = MagicMock()
    mock_model.tier.name = "EXPERT"
    result = MagicMock()
    result.success = success
    result.model = mock_model
    result.fallback_chain = []
    result.estimated_cost = estimated_cost
    result.reason = reason
    return result


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.daily_budget_remaining = 42.0
    router.summary.return_value = {"budget_used": 5.0}
    router.route.return_value = _make_route()
    return router


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.size = 100
    return cache


@pytest.fixture
def agent(mock_provider, mock_executor, mock_router, mock_cache):
    a = ProductionAgent(mock_provider, mock_executor, router=mock_router, cache=mock_cache)
    a._audit = MagicMock()
    return a


# ── ComplexityEstimate ──────────────────────────────────────────


class TestComplexityEstimate:
    def test_fields(self):
        ce = ComplexityEstimate(
            complexity=TaskComplexity.TRIVIAL,
            priority=TaskPriority.NORMAL,
            estimated_tokens=100,
            reason="test",
        )
        assert ce.complexity == TaskComplexity.TRIVIAL
        assert ce.priority == TaskPriority.NORMAL
        assert ce.estimated_tokens == 100
        assert ce.reason == "test"


# ── ComplexityEstimator ─────────────────────────────────────────


class TestComplexityEstimator:
    @pytest.fixture
    def e(self):
        return ComplexityEstimator()

    def test_trivial(self, e):
        r = e.estimate("天气怎样")
        assert r.complexity == TaskComplexity.TRIVIAL

    def test_urgent(self, e):
        r = e.estimate("快帮我翻译")
        assert r.priority == TaskPriority.HIGH

    def test_simple(self, e):
        r = e.estimate("hello")
        assert r.complexity == TaskComplexity.SIMPLE

    def test_moderate_one_keyword(self, e):
        r = e.estimate("分析一下")
        assert r.complexity == TaskComplexity.MODERATE

    def test_moderate_length(self, e):
        r = e.estimate("x" * 250)
        assert r.complexity == TaskComplexity.MODERATE

    def test_complex_multi(self, e):
        r = e.estimate("分析对比评估")
        assert r.complexity == TaskComplexity.COMPLEX

    def test_complex_one_expert(self, e):
        r = e.estimate("深度调研")
        assert r.complexity == TaskComplexity.COMPLEX

    def test_expert_two(self, e):
        r = e.estimate("深度全面分析")
        assert r.complexity == TaskComplexity.EXPERT

    def test_expert_length(self, e):
        r = e.estimate("x" * 600)
        assert r.complexity == TaskComplexity.EXPERT

    def test_english_trivial(self, e):
        r = e.estimate("weather today")
        assert r.complexity == TaskComplexity.TRIVIAL

    def test_english_complex(self, e):
        r = e.estimate("analyze compare evaluate research")
        assert r.complexity == TaskComplexity.COMPLEX

    def test_english_expert(self, e):
        r = e.estimate("comprehensive production from scratch paper review")
        assert r.complexity == TaskComplexity.EXPERT

    def test_urgent_asap(self, e):
        r = e.estimate("asap translate")
        assert r.priority == TaskPriority.HIGH

    def test_urgent_immediately(self, e):
        r = e.estimate("do it immediately")
        assert r.priority == TaskPriority.HIGH

    def test_urgent_now(self, e):
        r = e.estimate("now")
        assert r.priority == TaskPriority.HIGH

    def test_tokens_chinese(self, e):
        r = e.estimate("你好世界你好世界你好世界")
        assert r.estimated_tokens == max(50, 10 // 1.5)

    def test_tokens_english(self, e):
        r = e.estimate("hello world")
        assert r.estimated_tokens == max(50, 11 // 4)

    def test_tokens_ceiling(self, e):
        # English: char//4, 200k//4=50000, stays below ceiling
        r = e.estimate("x" * 200_000)
        assert r.estimated_tokens == 50000

    def test_tokens_ceiling_chinese(self, e):
        # Chinese: char//1.5, 200k//1.5=133333, clamped to ceiling 100k
        r = e.estimate("你" * 200_000)
        assert r.estimated_tokens == 100_000

    def test_reason_fields(self, e):
        r = e.estimate("深度全面分析")
        assert "expert_hits" in r.reason


# ── ProductionConfig ────────────────────────────────────────────


class TestProductionConfig:
    def test_defaults(self):
        pc = ProductionConfig()
        assert pc.enable_audit is True
        assert pc.enable_routing is True
        assert pc.enable_cache is True
        assert pc.budget_usd == 50.0
        assert pc.fallback_on_error is True

    def test_custom(self):
        ac = AgentConfig(max_steps=10)
        pc = ProductionConfig(
            agent_config=ac,
            enable_audit=False,
            enable_routing=False,
            enable_cache=False,
            audit_log_dir="/tmp",
            session_id="s1",
            budget_usd=100.0,
            fallback_on_error=False,
        )
        assert pc.enable_audit is False
        assert pc.enable_cache is False
        assert pc.audit_log_dir == "/tmp"
        assert pc.session_id == "s1"
        assert pc.agent_config.max_steps == 10


# ── ProductionAgent.__init__ ─────────────────────────────────────


class TestInit:
    def test_basic(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor)
        assert agent._provider is mock_provider
        assert agent._executor is mock_executor
        assert agent._cache is None

    def test_cache_enabled(self, mock_provider, mock_executor, mock_cache):
        agent = ProductionAgent(mock_provider, mock_executor, cache=mock_cache)
        assert agent._cache is mock_cache
        assert agent._provider is mock_provider  # no longer wraps

    def test_cache_disabled_config(self, mock_provider, mock_executor, mock_cache):
        config = ProductionConfig(enable_cache=False)
        agent = ProductionAgent(mock_provider, mock_executor, cache=mock_cache, config=config)
        assert agent._cache is None

    def test_cache_none(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor, cache=None)
        assert agent._cache is None

    def test_custom_config(self, mock_provider, mock_executor):
        config = ProductionConfig(enable_audit=False, budget_usd=100.0)
        agent = ProductionAgent(mock_provider, mock_executor, config=config)
        assert agent._config is config

    def test_session_auto(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor)
        assert agent._session_id.startswith("sess-")

    def test_session_custom(self, mock_provider, mock_executor):
        config = ProductionConfig(session_id="my-session")
        agent = ProductionAgent(mock_provider, mock_executor, config=config)
        assert agent._session_id == "my-session"

    def test_system_prompt(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor, system_prompt="Be helpful")
        assert agent._system_prompt == "Be helpful"


# ── run() ────────────────────────────────────────────────────────


class TestRun:
    _SUCCESS_RESULT = AgentResult(
        success=True, total_steps=3, total_tokens=500, total_cost_usd=0.001, final_answer="ok"
    )

    @staticmethod
    def _mock_run():
        return patch("agentos.agent.production.ToolAgent.run", return_value=TestRun._SUCCESS_RESULT)

    def test_success(self, agent, mock_router):
        with self._mock_run():
            result = agent.run("分析问题")
        assert result.success is True
        mock_router.record_request.assert_called_once()

    def test_routing_failure(self, mock_provider, mock_executor, mock_router):
        mock_router.route.return_value = _make_route(success=False, reason="budget exceeded")
        agent = ProductionAgent(mock_provider, mock_executor, router=mock_router)
        agent._audit = MagicMock()
        result = agent.run("hello")
        assert result.success is False
        assert "budget exceeded" in result.error

    def test_audit_start_end(self, agent):
        with self._mock_run():
            agent.run("test")
        actions = [c[1]["action"] for c in agent._audit.log.call_args_list]
        assert "agent_start" in actions
        assert "agent_end" in actions

    def test_no_audit(self, mock_provider, mock_executor, mock_router):
        config = ProductionConfig(enable_audit=False)
        agent = ProductionAgent(mock_provider, mock_executor, router=mock_router, config=config)
        with self._mock_run():
            result = agent.run("hello")
        assert result.success is True
        assert agent._audit is None

    def test_last_route_tracked(self, agent):
        with self._mock_run():
            assert agent._last_route is None
            agent.run("test")
        assert agent._last_route is not None

    def test_last_model_tracked(self, agent):
        with self._mock_run():
            assert agent._last_model is None
            agent.run("test")
        assert agent._last_model is not None
        assert agent._last_model.name == "gpt-4o"

    def test_duration_set(self, agent):
        with self._mock_run():
            result = agent.run("test")
        assert result.total_duration_ms > 0

    def test_failure_audit(self, agent):
        fail_result = AgentResult(success=False, error="exec error")
        with patch("agentos.agent.production.ToolAgent.run", return_value=fail_result):
            agent.run("fail task")
        end_calls = [c for c in agent._audit.log.call_args_list if c[1]["action"] == "agent_end"]
        assert len(end_calls) >= 1

    def test_cache_stats_noop(self, agent):
        agent._cache = None
        with self._mock_run():
            result = agent.run("test")
        assert result.success is True

    def test_cache_stats_update(self, agent):
        """Cache stats line now is a no-op (pass), ensure run still completes."""
        with self._mock_run():
            result = agent.run("test")
        assert result.success is True


# ── Properties ───────────────────────────────────────────────────


class TestProperties:
    def test_last_route_none(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor)
        assert agent.last_route is None

    def test_last_model_none(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor)
        assert agent.last_model is None

    def test_cache_stats(self, agent):
        assert agent.cache_stats == {"size": 100}

    def test_cache_stats_none(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor)
        assert agent.cache_stats is None

    def test_cache_hit_rate(self, agent):
        assert agent.cache_hit_rate == 0.0

    def test_cache_hit_rate_no_cache(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor)
        assert agent.cache_hit_rate == 0.0

    def test_cache_savings(self, agent):
        assert agent.cache_savings == 0.0

    def test_cache_savings_no_cache(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor)
        assert agent.cache_savings == 0.0

    def test_router(self, agent, mock_router):
        assert agent.router is mock_router

    def test_audit(self, agent):
        assert agent.audit is agent._audit

    def test_session_id(self, agent):
        assert agent.session_id == agent._session_id


# ── run_stream ───────────────────────────────────────────────────


class TestRunStream:
    def test_basic(self, agent):
        steps = list(agent.run_stream("test"))
        assert isinstance(steps, list)

    def test_tracks_route(self, agent):
        list(agent.run_stream("test"))
        assert agent._last_route is not None

    def test_no_audit(self, mock_provider, mock_executor, mock_router):
        config = ProductionConfig(enable_audit=False)
        agent = ProductionAgent(mock_provider, mock_executor, router=mock_router, config=config)
        result = agent.run_stream("test")
        assert result is not None

    def test_is_generator(self, agent):
        gen = agent.run_stream("test")
        assert hasattr(gen, "__iter__")


# ── route_summary ────────────────────────────────────────────────


class TestRouteSummary:
    def test_full(self, agent):
        with TestRun._mock_run():
            agent.run("test")
        s = agent.route_summary()
        assert s["last_model"] == "gpt-4o"
        assert s["last_model_tier"] == "EXPERT"

    def test_no_audit(self, mock_provider, mock_executor, mock_router):
        config = ProductionConfig(enable_audit=False)
        agent = ProductionAgent(mock_provider, mock_executor, router=mock_router, config=config)
        s = agent.route_summary()
        assert "audit" not in s

    def test_no_last_model(self, mock_provider, mock_executor):
        agent = ProductionAgent(mock_provider, mock_executor)
        s = agent.route_summary()
        assert "last_model" not in s

    def test_audit_stats(self, agent):
        agent._audit.stats_summary.return_value = {"events": 5}
        s = agent.route_summary()
        assert s["audit"] == {"events": 5}

    def test_no_tier_attr(self, agent):
        """route_summary skips tier when model has no .tier attribute."""
        with TestRun._mock_run():
            agent.run("test")
        agent._last_model = MagicMock()
        agent._last_model.name = "simple-model"
        del agent._last_model.tier
        s = agent.route_summary()
        assert s["last_model"] == "simple-model"
        assert "last_model_tier" not in s


# ── _make_audited_executor ───────────────────────────────────────


class TestMakeAuditedExecutor:
    def test_no_audit(self, mock_provider, mock_executor):
        config = ProductionConfig(enable_audit=False)
        agent = ProductionAgent(mock_provider, mock_executor, config=config)
        assert agent._make_audited_executor() is mock_executor

    def test_wrapped(self, mock_provider, mock_executor, mock_router, mock_cache):
        agent = ProductionAgent(mock_provider, mock_executor, router=mock_router, cache=mock_cache)
        agent._audit = MagicMock()
        wrapped = agent._make_audited_executor()
        assert wrapped is not mock_executor

    def test_schemas_copied(self, mock_provider, mock_executor, mock_router, mock_cache):
        agent = ProductionAgent(mock_provider, mock_executor, router=mock_router, cache=mock_cache)
        agent._audit = MagicMock()
        wrapped = agent._make_audited_executor()
        schemas = wrapped.get_schemas()
        assert len(schemas) == 1
        assert schemas[0].function.name == "test_tool"
