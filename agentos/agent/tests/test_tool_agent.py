"""agentos/agent/tool_agent.py 单元测试。"""

import json
import pytest

from agentos.agent.tool_agent import (
    ToolExecutor,
    AgentConfig,
    AgentStep,
    AgentResult,
)
from agentos.llm.base import Tool, ToolFunction, ToolParameter, ToolCall


# ── 工具定义 ──────────────────────────────────────────────────────

MOCK_TOOL = Tool.from_function(
    name="double",
    description="将输入数字翻倍",
    parameters={"x": ToolParameter(type="number", description="输入数字")},
)


# ── ToolExecutor ─────────────────────────────────────────────────

class TestToolExecutor:

    def test_register_and_list_schemas(self):
        ex = ToolExecutor()
        ex.register(MOCK_TOOL, lambda x: str(x * 2))
        schemas = ex.get_schemas()
        assert len(schemas) == 1
        assert schemas[0].function.name == "double"

    def test_execute_success(self):
        ex = ToolExecutor()
        ex.register(MOCK_TOOL, lambda x: str(x * 2))
        tc = ToolCall(id="c1", name="double", arguments=json.dumps({"x": 5}))
        result = ex.execute(tc)
        assert result == "10"

    def test_execute_unknown_tool(self):
        ex = ToolExecutor()
        tc = ToolCall(id="c1", name="no_such", arguments=json.dumps({}))
        result = ex.execute(tc)
        assert "Unknown tool" in result

    def test_execute_error(self):
        ex = ToolExecutor()
        ex.register(MOCK_TOOL, lambda x: str(int(x) * 2))  # int(x) would fail for non-number
        tc = ToolCall(id="c1", name="double", arguments=json.dumps({"x": "NOT_A_NUMBER"}))
        result = ex.execute(tc)
        assert "error" in result

    def test_multiple_register(self):
        ex = ToolExecutor()
        t2 = Tool.from_function(name="triple", description="三倍")
        ex.register(MOCK_TOOL, lambda x: str(x * 2))
        ex.register(t2, lambda: "tripled!")
        assert len(ex.get_schemas()) == 2
        assert ex.execute(ToolCall(id="c2", name="triple", arguments=json.dumps({}))) == "tripled!"


# ── AgentConfig ──────────────────────────────────────────────────

class TestAgentConfig:

    def test_defaults(self):
        c = AgentConfig()
        assert c.max_steps == 10
        assert c.temperature == 0.0
        assert c.stop_on_error is True
        assert c.verbose is False

    def test_custom(self):
        c = AgentConfig(max_steps=5, temperature=0.7, verbose=True, stop_on_error=False)
        assert c.max_steps == 5
        assert c.temperature == 0.7
        assert c.verbose is True
        assert c.stop_on_error is False


# ── AgentStep ────────────────────────────────────────────────────

class TestAgentStep:

    def test_empty_step(self):
        s = AgentStep(step=1)
        assert s.step == 1
        assert s.thought == ""
        assert s.tool_calls == []
        assert s.tool_results == {}

    def test_full_step(self):
        tc = ToolCall(id="c1", name="double", arguments=json.dumps({"x": 3}))
        s = AgentStep(
            step=2,
            thought="Let me double 3",
            tool_calls=[tc],
            tool_results={"c1": "6"},
            finish_reason="tool_calls",
            tokens_used=150,
            cost_usd=0.0002,
            duration_ms=320.0,
        )
        assert s.step == 2
        assert len(s.tool_calls) == 1
        assert s.tool_results["c1"] == "6"
        assert s.tokens_used == 150
        assert s.cost_usd == 0.0002
        assert s.duration_ms == 320.0


# ── AgentResult ──────────────────────────────────────────────────

class TestAgentResult:

    def test_success_result(self):
        r = AgentResult(success=True, final_answer="答案是 42", total_steps=2, total_tokens=500, total_cost_usd=0.001, total_duration_ms=1200)
        assert r.success is True
        assert r.final_answer == "答案是 42"
        assert r.total_steps == 2
        assert r.error is None

    def test_failure_result(self):
        r = AgentResult(success=False, final_answer="", total_steps=10, error="max steps")
        assert r.success is False
        assert r.error == "max steps"
