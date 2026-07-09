"""
test_tool_agent.py — tool_agent.py 全覆盖测试
"""

import asyncio
import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from agentos.agent.tool_agent import (
    AgentConfig,
    AgentResult,
    AgentStep,
    MockLLMProvider,
    ToolAgent,
    ToolExecutor,
)
from agentos.llm.base import (
    CompletionChoice,
    CompletionResult,
    CompletionUsage,
    Message,
    MessageRole,
    Tool,
    ToolCall,
    ToolFunction,
)
from agentos.tools.circuit_breaker import CircuitBreaker
from agentos.tools.validation import (
    ToolOutputValidator,
    ValidationIssue,
    ValidationResult,
)

# ── Helpers ─────────────────────────────────────────────────────


def _tf(name, desc="test", params=None):
    return ToolFunction(name=name, description=desc, parameters=params or {})


def _tool(name, desc="test", params=None):
    return Tool(function=_tf(name, desc, params))


def _tc(name, args=None, tid=""):
    return ToolCall(id=tid or f"tc_{name}", name=name, arguments=json.dumps(args or {}))


def _tr(content="", tool_calls=None, finish="stop"):
    msg = Message(role=MessageRole.ASSISTANT, content=content, tool_calls=tool_calls)
    choice = CompletionChoice(index=0, message=msg, finish_reason=finish)
    return CompletionResult(
        id="r1", model="m", choices=[choice],
        usage=CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


# ── AgentConfig ──────────────────────────────────────────────────


class TestAgentConfig:
    def test_defaults(self):
        c = AgentConfig()
        assert c.max_steps == 10
        assert c.temperature == 0.0
        assert c.max_tokens == 4096
        assert c.verbose is False
        assert c.stop_on_error is True
        assert c.max_retries == 2
        assert c.retry_delay == 0.5
        assert c.checkpoint_dir == ""

    def test_custom(self):
        c = AgentConfig(max_steps=5, temperature=0.7, max_tokens=1000, verbose=True,
                        stop_on_error=False, max_retries=3, retry_delay=1.0, checkpoint_dir="/tmp")
        assert c.max_steps == 5
        assert c.verbose is True
        assert c.stop_on_error is False
        assert c.max_retries == 3


# ── AgentStep ────────────────────────────────────────────────────


class TestAgentStep:
    def test_defaults(self):
        s = AgentStep(step=1)
        assert s.step == 1
        assert s.thought == ""
        assert s.tool_calls == []
        assert s.tool_results == {}
        assert s.finish_reason == ""
        assert s.tokens_used == 0
        assert s.cost_usd == 0.0
        assert s.duration_ms == 0.0

    def test_custom(self):
        tc = _tc("w", {"x": 1})
        s = AgentStep(step=3, thought="think", tool_calls=[tc],
                      tool_results={"a": "ok"}, finish_reason="stop",
                      tokens_used=100, cost_usd=0.01, duration_ms=500.0)
        assert s.step == 3
        assert s.thought == "think"
        assert len(s.tool_calls) == 1
        assert s.tool_results["a"] == "ok"
        assert s.duration_ms == 500.0


# ── AgentResult ──────────────────────────────────────────────────


class TestAgentResult:
    def test_defaults(self):
        r = AgentResult()
        assert r.success is True
        assert r.final_answer == ""
        assert r.steps == []
        assert r.total_steps == 0

    def test_error_result(self):
        s = AgentStep(step=1)
        r = AgentResult(success=False, error="test err", steps=[s],
                        final_answer="fail", total_steps=1, total_tokens=10,
                        total_cost_usd=0.001, total_duration_ms=100.0)
        assert r.success is False
        assert r.error == "test err"
        assert r.final_answer == "fail"


# ── ToolExecutor ─────────────────────────────────────────────────


class TestToolExecutor:
    def test_register_and_get_schemas(self):
        te = ToolExecutor()
        te.register(_tool("hello"), lambda **kw: f"hi {kw.get('name','')}")
        schemas = te.get_schemas()
        assert len(schemas) == 1
        assert schemas[0].function.name == "hello"

    def test_execute_success(self):
        te = ToolExecutor()
        te.register(_tool("add"), lambda a, b: str(a + b))
        result = te.execute(_tc("add", {"a": 1, "b": 2}))
        assert result == "3"

    def test_execute_unknown_tool(self):
        te = ToolExecutor()
        result = te.execute(_tc("unknown"))
        d = json.loads(result)
        assert "Unknown tool" in d["error"]

    def test_execute_with_circuit_breaker_closed(self):
        cb = CircuitBreaker(name="cb1", failure_threshold=3, recovery_timeout=60)
        te = ToolExecutor(circuit_breaker=cb)
        te.register(_tool("t1"), lambda **kw: "ok")
        result = te.execute(_tc("t1"))
        assert result == "ok"

    def test_execute_with_circuit_breaker_open(self):
        cb = CircuitBreaker(name="cb2", failure_threshold=1, recovery_timeout=60)
        te = ToolExecutor(circuit_breaker=cb)
        te.register(_tool("t1"), lambda **kw: "ok")
        cb.trip()  # trip immediately
        result = te.execute(_tc("t1"))
        d = json.loads(result)
        assert "Circuit breaker OPEN" in d["error"]

    def test_execute_with_validator_pass(self):
        v = ToolOutputValidator("t1")
        te = ToolExecutor(validator=v)
        te.register(_tool("t1"), lambda **kw: "ok")
        result = te.execute(_tc("t1"))
        assert result == "ok"

    def test_execute_with_validator_fail(self):
        v = ToolOutputValidator("t1")
        issue = ValidationIssue(rule="required", severity="error", message="bad output", field="output")
        v.validate = MagicMock(return_value=ValidationResult(is_valid=False, issues=[issue]))
        te = ToolExecutor(validator=v)
        te.register(_tool("t1"), lambda **kw: "bad")
        result = te.execute(_tc("t1"))
        assert "[validation:" in result
        assert "bad output" in result

    def test_execute_with_metrics_success(self):
        """Mock MetricsCollector with get_counter/get_timer to exercise metrics paths."""
        m = MagicMock()
        c = MagicMock()
        t = MagicMock()
        m.get_counter.return_value = c
        m.get_timer.return_value = t
        te = ToolExecutor(metrics=m)
        te.register(_tool("t1"), lambda **kw: "ok")
        result = te.execute(_tc("t1"))
        assert result == "ok"
        m.get_counter.assert_any_call("tool_calls_total")
        m.get_counter.assert_any_call("tool_calls_success")
        m.get_timer.assert_called_with("tool_latency_ms")

    def test_execute_with_metrics_error(self):
        m = MagicMock()
        c = MagicMock()
        m.get_counter.return_value = c
        m.get_timer.return_value = MagicMock()
        te = ToolExecutor(metrics=m)
        te.register(_tool("t1"), lambda **kw: 1 / 0)
        result = te.execute(_tc("t1"))
        d = json.loads(result)
        assert "error" in d
        m.get_counter.assert_any_call("tool_calls_total")
        m.get_counter.assert_any_call("tool_calls_errors")

    def test_execute_handler_raises_exception(self):
        te = ToolExecutor()
        te.register(_tool("fail"), lambda **kw: 1 / 0)
        result = te.execute(_tc("fail"))
        d = json.loads(result)
        assert "error" in d

    def test_execute_full_pipeline_cb_fail_metrics(self):
        cb = CircuitBreaker(name="cb", failure_threshold=1, recovery_timeout=60)
        m = MagicMock()
        m.get_counter.return_value = MagicMock()
        cb.trip()
        te = ToolExecutor(circuit_breaker=cb, metrics=m)
        te.register(_tool("t1"), lambda **kw: "ok")
        result = te.execute(_tc("t1"))
        d = json.loads(result)
        assert "Circuit breaker OPEN" in d["error"]

    def test_execute_exception_records_cb_failure(self):
        cb = CircuitBreaker(name="cb", failure_threshold=3, recovery_timeout=60)
        te = ToolExecutor(circuit_breaker=cb)
        te.register(_tool("bad"), lambda **kw: 1 / 0)
        te.execute(_tc("bad"))
        assert cb._failure_count == 1


# ── MockLLMProvider ──────────────────────────────────────────────


class TestMockLLMProvider:
    def test_text_response_static(self):
        d = MockLLMProvider.text_response("hello")
        assert d["content"] == "hello"
        assert d["finish_reason"] == "stop"

    def test_tool_response_static(self):
        tc_list = MockLLMProvider.tool_response("get_weather", {"city": "BJ"})["tool_calls"]
        assert tc_list[0].name == "get_weather"

    def test_tool_response_with_custom_id(self):
        tc_list = MockLLMProvider.tool_response("t1", {}, "my_id")["tool_calls"]
        assert tc_list[0].id == "my_id"

    def test_chat_basic(self):
        mp = MockLLMProvider([
            MockLLMProvider.text_response("hello"),
            MockLLMProvider.text_response("world"),
        ])
        r1 = mp.chat([Message(role=MessageRole.USER, content="hi")])
        assert r1.choices[0].message.content == "hello"
        r2 = mp.chat([Message(role=MessageRole.USER, content="hi")])
        assert r2.choices[0].message.content == "world"

    def test_chat_exhausted_responses(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("only")])
        mp.chat([Message(role=MessageRole.USER, content="hi")])
        r2 = mp.chat([Message(role=MessageRole.USER, content="hi")])
        assert r2.choices[0].message.content == "done"

    def test_chat_tool_response(self):
        mp = MockLLMProvider([
            MockLLMProvider.tool_response("search", {"q": "x"}),
            MockLLMProvider.text_response("answer"),
        ])
        r1 = mp.chat([], tools=[_tool("search")], temperature=0, max_tokens=100)
        assert r1.choices[0].message.tool_calls[0].name == "search"

    async def test_achat(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("async hello")])
        r = await mp.achat([Message(role=MessageRole.USER, content="hi")])
        assert r.choices[0].message.content == "async hello"

    def test_provider_name(self):
        mp = MockLLMProvider([])
        assert mp.provider_name == "mock"


# ── ToolAgent ────────────────────────────────────────────────────


class TestToolAgent:

    def test_run_simple_answer(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("北京今天晴，22°C")])
        agent = ToolAgent(mp, ToolExecutor())
        result = agent.run("北京天气")
        assert result.success is True
        assert result.final_answer == "北京今天晴，22°C"
        assert result.total_steps == 1

    def test_run_with_tools(self):
        mp = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "BJ"}),
            MockLLMProvider.text_response("北京今天晴"),
        ])
        te = ToolExecutor()
        te.register(_tool("get_weather"), lambda city: f"{city}: 22°C sunny")
        agent = ToolAgent(mp, te)
        result = agent.run("北京天气")
        assert result.success is True
        assert result.final_answer == "北京今天晴"
        assert result.total_steps == 2

    def test_run_max_steps_exceeded(self):
        mp = MockLLMProvider([MockLLMProvider.tool_response("t1", {}) for _ in range(3)])
        te = ToolExecutor()
        te.register(_tool("t1"), lambda **kw: "ok")
        agent = ToolAgent(mp, te, config=AgentConfig(max_steps=2))
        result = agent.run("task")
        assert result.success is False
        assert "max steps" in result.error

    def test_run_tool_error_stop(self):
        mp = MockLLMProvider([MockLLMProvider.tool_response("fail", {})])
        te = ToolExecutor()
        te.register(_tool("fail"), lambda **kw: 1 / 0)
        agent = ToolAgent(mp, te, config=AgentConfig(stop_on_error=True))
        result = agent.run("task")
        assert result.success is False

    def test_run_tool_error_continue(self):
        mp = MockLLMProvider([MockLLMProvider.tool_response("fail", {})])
        te = ToolExecutor()
        te.register(_tool("fail"), lambda **kw: 1 / 0)
        agent = ToolAgent(mp, te, config=AgentConfig(stop_on_error=False))
        result = agent.run("task")
        # stop_on_error=False means tool errors don't halt; agent continues
        # and exhausted mock returns "done" → success
        assert result.success is True

    def test_run_custom_system_prompt(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("got it")])
        agent = ToolAgent(mp, ToolExecutor(), system_prompt="You are a code assistant.")
        result = agent.run("test")
        assert result.success is True

    def test_run_with_verbose_enabled(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("ok")])
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(verbose=True))
        with patch("builtins.print") as mock_print:
            result = agent.run("test")
        assert result.success is True
        assert mock_print.called

    def test_run_verbose_with_tools(self):
        mp = MockLLMProvider([
            MockLLMProvider.tool_response("t1", {"x": 1}),
            MockLLMProvider.text_response("done"),
        ])
        te = ToolExecutor()
        te.register(_tool("t1"), lambda x: f"got {x}")
        agent = ToolAgent(mp, te, config=AgentConfig(verbose=True))
        with patch("builtins.print") as mock_print:
            result = agent.run("test")
        assert result.success is True
        assert mock_print.called

    def test_run_with_metrics(self):
        m = MagicMock()
        c = MagicMock()
        m.counter.return_value = c
        mp = MockLLMProvider([MockLLMProvider.text_response("answer")])
        agent = ToolAgent(mp, ToolExecutor(), metrics=m)
        result = agent.run("test")
        assert result.success is True
        # _process_step calls metrics, but tool_agent uses get_counter not counter
        # So this only exercises the ToolAgent path; metrics integration tested separately

    def test_run_finish_reason_stop_with_content(self):
        mp = MockLLMProvider([{"content": "final answer", "finish_reason": "stop"}])
        agent = ToolAgent(mp, ToolExecutor())
        result = agent.run("test")
        assert result.success is True
        assert result.final_answer == "final answer"

    def test__process_step_no_tool_calls(self):
        agent = ToolAgent(MockLLMProvider([]), ToolExecutor())
        step, done, final = agent._process_step(_tr(content="ans"), 1)
        assert done is True
        assert final == "ans"

    def test__process_step_with_tool_calls(self):
        te = ToolExecutor()
        te.register(_tool("t1"), lambda **kw: "ok")
        agent = ToolAgent(MockLLMProvider([]), te)
        step, done, final = agent._process_step(_tr(tool_calls=[_tc("t1")], finish="tool_calls"), 1)
        assert done is False
        assert step.tool_calls[0].name == "t1"

    def test__process_step_finish_stop_with_tool_calls(self):
        te = ToolExecutor()
        te.register(_tool("t1"), lambda **kw: "ok")
        agent = ToolAgent(MockLLMProvider([]), te)
        step, done, final = agent._process_step(
            _tr(content="ans", tool_calls=[_tc("t1")], finish="stop"), 1
        )
        assert done is True
        assert final == "ans"

    def test__make_result(self):
        agent = ToolAgent(MockLLMProvider([]), ToolExecutor())
        r = agent._make_result(True, "yes", [], 0, 0.0, time.monotonic())
        assert r.success is True
        assert r.final_answer == "yes"

    def test__make_result_error(self):
        agent = ToolAgent(MockLLMProvider([]), ToolExecutor())
        r = agent._make_result(False, "", [], 10, 0.001, time.monotonic(), "boom")
        assert r.success is False
        assert r.error == "boom"

    def test_run_stream(self):
        mp = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "BJ"}),
            MockLLMProvider.text_response("晴天"),
        ])
        te = ToolExecutor()
        te.register(_tool("get_weather"), lambda city: f"{city}: sunny")
        agent = ToolAgent(mp, te)
        steps = list(agent.run_stream("test"))
        assert len(steps) == 2

    def test_run_stream_simple(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("direct")])
        agent = ToolAgent(mp, ToolExecutor())
        steps = list(agent.run_stream("test"))
        assert len(steps) == 1

    def test_run_stream_max_steps(self):
        mp = MockLLMProvider([MockLLMProvider.tool_response("t1", {}) for _ in range(3)])
        te = ToolExecutor()
        te.register(_tool("t1"), lambda **kw: "ok")
        agent = ToolAgent(mp, te, config=AgentConfig(max_steps=2))
        steps = list(agent.run_stream("test"))
        assert len(steps) == 2  # yields 2 then StopIteration with error result

    async def test_arun_simple(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("async result")])
        agent = ToolAgent(mp, ToolExecutor())
        result = await agent.arun("test")
        assert result.success is True
        assert result.final_answer == "async result"

    async def test_arun_with_tools(self):
        mp = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "BJ"}),
            MockLLMProvider.text_response("晴天"),
        ])
        te = ToolExecutor()
        te.register(_tool("get_weather"), lambda city: f"{city}: sunny")
        agent = ToolAgent(mp, te)
        result = await agent.arun("test")
        assert result.success is True
        assert result.final_answer == "晴天"
        assert result.total_steps == 2

    async def test_arun_max_steps(self):
        mp = MockLLMProvider([MockLLMProvider.tool_response("t1", {}) for _ in range(3)])
        te = ToolExecutor()
        te.register(_tool("t1"), lambda **kw: "ok")
        agent = ToolAgent(mp, te, config=AgentConfig(max_steps=2))
        result = await agent.arun("test")
        assert result.success is False
        assert "max steps" in result.error

    async def test_arun_exception(self):
        mp = MagicMock()
        async def fake_achat(*args, **kwargs):
            raise RuntimeError("async llm down")
        mp.achat = fake_achat
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(max_retries=0))
        result = await agent.arun("test")
        assert result.success is False
        assert "async llm down" in result.error

    # ── Retry ──────────────────────────────────────────────────

    def test__call_with_retry_success(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("ok")])
        agent = ToolAgent(mp, ToolExecutor())
        r = agent._call_with_retry([], [])
        assert r.choices[0].message.content == "ok"

    def test__call_with_retry_eventual_success(self):
        call_count = [0]

        class FlakyProvider(MockLLMProvider):
            def chat(self, *args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise ValueError("transient error")
                return self._build_result({"content": "recovered"})

        mp = FlakyProvider([])
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(max_retries=2, retry_delay=0.01))
        r = agent._call_with_retry([], [])
        assert r.choices[0].message.content == "recovered"
        assert call_count[0] == 2

    def test__call_with_retry_exhausted(self):
        mp = MagicMock()
        mp.chat.side_effect = ValueError("always fail")
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(max_retries=1, retry_delay=0.01))
        with pytest.raises(ValueError, match="always fail"):
            agent._call_with_retry([], [])

    async def test__acall_with_retry_success(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("async ok")])
        agent = ToolAgent(mp, ToolExecutor())
        r = await agent._acall_with_retry([], [])
        assert r.choices[0].message.content == "async ok"

    async def test__acall_with_retry_exhausted(self):
        mp = MagicMock()
        async def fake_achat(*args, **kwargs):
            raise ValueError("async fail")
        mp.achat = fake_achat
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(max_retries=0, retry_delay=0.01))
        with pytest.raises(ValueError, match="async fail"):
            await agent._acall_with_retry([], [])

    async def test__acall_with_retry_eventual(self):
        call_count = [0]

        class FlakyAsync(MockLLMProvider):
            async def achat(self, *args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise ValueError("transient")
                return self._build_result({"content": "async recovered"})

        mp = FlakyAsync([])
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(max_retries=2, retry_delay=0.01))
        r = await agent._acall_with_retry([], [])
        assert r.choices[0].message.content == "async recovered"
        assert call_count[0] == 2

    # ── Checkpoint / Resume ────────────────────────────────────

    def test_checkpoint_and_resume(self, tmp_path):
        ckpt_dir = str(tmp_path / "ckpt")
        os.makedirs(ckpt_dir, exist_ok=True)
        mp = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "BJ"}),
            MockLLMProvider.text_response("晴天"),
        ])
        te = ToolExecutor()
        te.register(_tool("get_weather"), lambda city: f"{city}: sunny")
        agent = ToolAgent(mp, te, config=AgentConfig(checkpoint_dir=ckpt_dir))
        agent.run("test")
        assert os.path.exists(os.path.join(ckpt_dir, "agent_checkpoint.json"))

    def test_resume_no_checkpoint_dir(self):
        agent = ToolAgent(MockLLMProvider([]), ToolExecutor())
        with pytest.raises(ValueError, match="checkpoint_dir not configured"):
            agent.resume()

    def test_resume_no_checkpoint_file(self, tmp_path):
        agent = ToolAgent(MockLLMProvider([]), ToolExecutor(),
                          config=AgentConfig(checkpoint_dir=str(tmp_path)))
        with pytest.raises(FileNotFoundError, match="No checkpoint found"):
            agent.resume()

    def test_resume_success(self, tmp_path):
        ckpt_dir = str(tmp_path / "ckpt")
        os.makedirs(ckpt_dir, exist_ok=True)
        ckpt_path = os.path.join(ckpt_dir, "agent_checkpoint.json")
        ckpt_data = {
            "task": "resume test",
            "step": 1,
            "messages": [
                {"role": "system", "content": "sys", "tool_call_id": None, "tool_calls": None},
                {"role": "user", "content": "task", "tool_call_id": None, "tool_calls": None},
                {"role": "assistant", "content": "", "tool_call_id": None,
                 "tool_calls": [{"id": "tc1", "name": "get_weather", "arguments": '{"city":"BJ"}'}]},
                {"role": "tool", "content": "BJ: sunny", "tool_call_id": "tc1", "tool_calls": None},
            ],
        }
        with open(ckpt_path, "w") as f:
            json.dump(ckpt_data, f)

        mp = MockLLMProvider([MockLLMProvider.text_response("resumed answer")])
        te = ToolExecutor()
        te.register(_tool("get_weather"), lambda city: f"{city}: sunny")
        agent = ToolAgent(mp, te, config=AgentConfig(checkpoint_dir=ckpt_dir))
        result = agent.resume()
        assert result.success is True
        assert result.final_answer == "resumed answer"

    def test_resume_max_steps(self, tmp_path):
        ckpt_dir = str(tmp_path / "ckpt")
        os.makedirs(ckpt_dir, exist_ok=True)
        ckpt_path = os.path.join(ckpt_dir, "agent_checkpoint.json")
        ckpt_data = {
            "task": "resume test",
            "step": 2,  # already at step 2
            "messages": [
                {"role": "system", "content": "sys", "tool_call_id": None, "tool_calls": None},
                {"role": "user", "content": "task", "tool_call_id": None, "tool_calls": None},
            ],
        }
        with open(ckpt_path, "w") as f:
            json.dump(ckpt_data, f)

        mp = MockLLMProvider([MockLLMProvider.tool_response("t1", {})])
        te = ToolExecutor()
        te.register(_tool("t1"), lambda **kw: "ok")
        agent = ToolAgent(mp, te, config=AgentConfig(checkpoint_dir=ckpt_dir, max_steps=3))
        result = agent.resume()
        assert result.success is False
        assert "max steps" in result.error

    # ── Edge cases ─────────────────────────────────────────────

    def test_run_empty_tool_executor(self):
        mp = MockLLMProvider([MockLLMProvider.text_response("direct answer")])
        agent = ToolAgent(mp, ToolExecutor())
        result = agent.run("test")
        assert result.success is True

    def test_run_tools_none_when_empty(self):
        mp = MagicMock()
        mp.chat.return_value = _tr("ok")
        agent = ToolAgent(mp, ToolExecutor())
        agent.run("test")
        # tools passed to chat should be None when tool executor has no tools
        assert mp.chat.call_args[1]["tools"] is None

    def test_run_exception_in_loop(self):
        mp = MagicMock()
        mp.chat.side_effect = RuntimeError("llm down")
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(max_retries=0))
        result = agent.run("test")
        assert result.success is False
        assert "llm down" in result.error

    def test_mock_llm_provider_builds_completion_correctly(self):
        mp = MockLLMProvider([])
        r = mp._build_result({"content": "c", "finish_reason": "stop"})
        assert r.choices[0].message.content == "c"

    def test_mock_llm_provider_tool_response_default_id(self):
        d = MockLLMProvider.tool_response("t1", {"x": 1})
        assert d["tool_calls"][0].id.startswith("tc_")

    def test_run_stream_exception(self):
        mp = MagicMock()
        mp.chat.side_effect = RuntimeError("stream error")
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(max_retries=0))
        steps = list(agent.run_stream("test"))
        assert len(steps) == 0

    def test__process_step_with_metrics(self):
        """_process_step with metrics mock using get_counter API."""
        m = MagicMock()
        counter_mock = MagicMock()
        m.get_counter.return_value = counter_mock
        m.get_timer.return_value = MagicMock()
        agent = ToolAgent(MockLLMProvider([]), ToolExecutor(), metrics=m)
        step, done, final = agent._process_step(_tr(content="ans"), 1)
        assert done is True
        # Should have called metrics
        m.get_counter.assert_any_call("llm_calls_total")
        m.get_counter.assert_any_call("llm_tokens_total")
        m.get_counter.assert_any_call("agent_steps_total")

    def test_acha_silent_error(self):
        """Verify that arun catches exceptions from _acall_with_retry."""
        mp = MagicMock()
        mp.achat = MagicMock(side_effect=ValueError("silent error"))
        agent = ToolAgent(mp, ToolExecutor(), config=AgentConfig(max_retries=0))
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(agent.arun("test"))
            assert result.success is False
        finally:
            loop.close()
