"""Tests for agentos/agent/production_agent.py."""

import os

import pytest

from agentos.agent.agent_builder import _MockProvider
from agentos.agent.production_agent import AgentResult, ProductionAgent


class TestAgentResult:
    def test_success_result(self):
        r = AgentResult(success=True, output="task done", total_steps=3)
        assert r.success is True
        assert r.output == "task done"
        assert r.total_steps == 3

    def test_failure_result(self):
        r = AgentResult(success=False, error="something went wrong")
        assert r.success is False
        assert r.error == "something went wrong"

    def test_all_fields(self):
        r = AgentResult(
            success=True,
            output="result",
            error=None,
            total_steps=5,
            total_tokens=1200,
            total_cost_usd=0.003,
            total_latency_ms=450.5,
            tool_calls=3,
        )
        assert r.total_tokens == 1200
        assert r.total_cost_usd == 0.003
        assert r.tool_calls == 3


class TestProductionAgent:
    @pytest.fixture(autouse=True)
    def setup(self):
        for key in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            os.environ.pop(key, None)

    def test_init_with_defaults(self):
        agent = ProductionAgent()
        assert agent is not None

    def test_init_with_mock_provider(self):
        provider = _MockProvider()
        agent = ProductionAgent(provider=provider)
        assert agent is not None

    def test_init_with_custom_max_steps(self):
        agent = ProductionAgent(max_steps=5)
        assert agent is not None

    def test_init_with_system_prompt(self):
        agent = ProductionAgent(system_prompt="Be concise.")
        assert agent is not None

    def test_init_with_include_skills_false(self):
        agent = ProductionAgent(include_skills=False)
        assert agent is not None

    def test_init_with_verbose(self):
        agent = ProductionAgent(verbose=True)
        assert agent is not None

    def test_run_with_mock_provider(self):
        provider = _MockProvider()
        agent = ProductionAgent(provider=provider, include_skills=False)
        result = agent.run("What is 1+1?")
        assert isinstance(result, AgentResult)

    def test_run_returns_agent_result_structure(self):
        provider = _MockProvider()
        agent = ProductionAgent(provider=provider, include_skills=False)
        result = agent.run("Say hello")
        assert isinstance(result, AgentResult)
        assert isinstance(result.success, bool)
        assert isinstance(result.output, str)

    def test_get_tool_count(self):
        provider = _MockProvider()
        agent = ProductionAgent(provider=provider, include_skills=False)
        count = agent.get_tool_count()
        assert isinstance(count, int)
        assert count >= 0

    def test_list_tools(self):
        provider = _MockProvider()
        agent = ProductionAgent(provider=provider, include_skills=False)
        tools = agent.list_tools()
        assert isinstance(tools, list)
