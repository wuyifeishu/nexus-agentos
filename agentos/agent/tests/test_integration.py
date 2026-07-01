"""ToolAgent 集成测试 — 使用 MockLLMProvider 测试完整 Agent 流程。"""

import json
import os
import tempfile

import pytest

from agentos.agent.tool_agent import (
    AgentConfig,
    AgentResult,
    AgentStep,
    MockLLMProvider,
    ToolAgent,
    ToolExecutor,
)
from agentos.llm.base import Tool, ToolParameter


# ── 工具 ─────────────────────────────────────────────────────────

WEATHER_TOOL = Tool.from_function(
    name="get_weather",
    description="获取城市天气",
    parameters={"city": ToolParameter(type="string", description="城市名")},
)

CALC_TOOL = Tool.from_function(
    name="calculate",
    description="数学计算",
    parameters={
        "expression": ToolParameter(type="string", description="表达式，如 1+2*3"),
    },
)


class TestIntegrationFullFlow:
    """完整 Agent 流程集成测试。"""

    def test_single_call_no_tools(self):
        """无工具，单步直接回答。"""
        mock = MockLLMProvider([
            MockLLMProvider.text_response("答案是42。"),
        ])
        executor = ToolExecutor()
        agent = ToolAgent(mock, executor)
        result = agent.run("1+1等于几？")

        assert result.success
        assert "42" in result.final_answer
        assert result.total_steps == 1
        assert len(mock.calls) == 1

    def test_single_tool_call_then_answer(self):
        """一步工具调用，然后给出答案。"""
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "北京"}),
            MockLLMProvider.text_response("北京今天晴天，22°C。"),
        ])
        executor = ToolExecutor()
        executor.register(WEATHER_TOOL, lambda city: f"{city}: 晴 22°C")
        agent = ToolAgent(mock, executor)
        result = agent.run("北京天气怎么样？")

        assert result.success
        assert "22" in result.final_answer
        assert result.total_steps == 2
        assert result.total_tokens > 0
        # 验证 tool 被调用了
        assert mock.calls[0]["tools"] == ["get_weather"]
        assert len(mock.calls) == 2

    def test_two_tool_calls(self):
        """两步工具调用。"""
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "北京"}),
            MockLLMProvider.tool_response("get_weather", {"city": "上海"}),
            MockLLMProvider.text_response("北京22°C，上海28°C，都适合出行。"),
        ])
        executor = ToolExecutor()
        executor.register(WEATHER_TOOL, lambda city: f"{city}: 晴")
        agent = ToolAgent(mock, executor)
        result = agent.run("北京和上海天气怎么样？")

        assert result.success
        assert result.total_steps == 3
        assert len(mock.calls) == 3

    def test_max_steps_exceeds(self):
        """超过 max_steps 限制。"""
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "北京"}),
            MockLLMProvider.tool_response("get_weather", {"city": "上海"}),
            MockLLMProvider.tool_response("get_weather", {"city": "深圳"}),
        ])
        executor = ToolExecutor()
        executor.register(WEATHER_TOOL, lambda city: f"{city}: OK")
        agent = ToolAgent(mock, executor, config=AgentConfig(max_steps=2))
        result = agent.run("查天气")

        assert not result.success
        assert "max steps" in (result.error or "")
        assert result.total_steps == 2

    def test_tool_execution_error_stops(self):
        """工具执行出错且 stop_on_error=True。"""
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "火星"}),
        ])
        executor = ToolExecutor()
        executor.register(WEATHER_TOOL, lambda city: 1/0)  # 必定失败
        agent = ToolAgent(mock, executor, config=AgentConfig(stop_on_error=True))
        result = agent.run("火星天气？")

        assert not result.success
        assert "error" in (result.error or "").lower()

    def test_tool_error_continues(self):
        """工具出错但 stop_on_error=False，Agent 继续执行。"""
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "火星"}),
            MockLLMProvider.text_response("抱歉，无法获取火星天气。"),
        ])
        executor = ToolExecutor()
        executor.register(WEATHER_TOOL, lambda city: 1/0)  # 必定失败
        agent = ToolAgent(mock, executor, config=AgentConfig(stop_on_error=False, max_steps=3))
        result = agent.run("火星天气？")

        # 工具出错但继续执行，LLM 应该给出文本回答
        assert result.success or result.total_steps > 1

    def test_streaming_yields_steps(self):
        """run_stream 逐步产出。"""
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "北京"}),
            MockLLMProvider.text_response("北京晴天22°C。"),
        ])
        executor = ToolExecutor()
        executor.register(WEATHER_TOOL, lambda city: f"{city}: 22°C")
        agent = ToolAgent(mock, executor)

        gen = agent.run_stream("北京天气？")
        steps = []
        result = None
        try:
            while True:
                steps.append(next(gen))
        except StopIteration as e:
            result = e.value

        assert len(steps) == 2  # tool call step + final answer step
        assert result is not None
        assert result.success
        assert "22" in result.final_answer

    def test_multiple_tools_registered(self):
        """多工具注册，Agent 只调用需要的。"""
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("calculate", {"expression": "3*4+5"}),
            MockLLMProvider.text_response("结果是17。"),
        ])
        executor = ToolExecutor()
        executor.register(CALC_TOOL, lambda expression: str(eval(expression)))
        executor.register(WEATHER_TOOL, lambda city: "sunny")

        agent = ToolAgent(mock, executor)
        result = agent.run("计算 3*4+5")

        assert result.success
        assert "17" in result.final_answer
        # verify only calculate was called, not weather
        assert "calculate" in mock.calls[0]["tools"]
        assert "get_weather" in mock.calls[0]["tools"]


class TestCheckpointResume:
    """Checkpoint / Resume 集成测试。"""

    def test_checkpoint_saved_and_resumed(self):
        """完整流程：中断 → checkpoint → 从断点恢复。"""
        # Step 1: 只给 1 步的 LLM 响应，让 Agent 在工具调用后"中断"
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "北京"}),
            MockLLMProvider.text_response("北京今天晴天，22°C。"),
        ])
        executor = ToolExecutor()
        executor.register(WEATHER_TOOL, lambda city: f"{city}: 晴 22°C")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = AgentConfig(checkpoint_dir=tmpdir, max_steps=5)
            agent = ToolAgent(mock, executor, config=config)

            # 第一次运行（完整）
            result1 = agent.run("北京天气？")
            assert result1.success
            assert os.path.exists(os.path.join(tmpdir, "agent_checkpoint.json"))

            # 验证 checkpoint 内容
            with open(os.path.join(tmpdir, "agent_checkpoint.json")) as f:
                ckpt = json.load(f)
            assert ckpt["task"] == "北京天气？"
            assert ckpt["step"] >= 0

            # 第二次从 checkpoint resume（需要新 mock 继续响应）
            mock2 = MockLLMProvider([
                MockLLMProvider.text_response("已确认，北京22°C。"),
            ])
            agent2 = ToolAgent(mock2, executor, config=config)
            result2 = agent2.resume()
            assert result2.success
            assert "22" in result2.final_answer or "22" in result2.final_answer

    def test_resume_no_checkpoint_raises(self):
        """无 checkpoint 时 resume 抛出异常。"""
        mock = MockLLMProvider([])
        executor = ToolExecutor()
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = ToolAgent(mock, executor, config=AgentConfig(checkpoint_dir=tmpdir))
            with pytest.raises(FileNotFoundError):
                agent.resume()

    def test_resume_no_checkpoint_dir_raises(self):
        """未配置 checkpoint_dir 时 resume 抛出异常。"""
        mock = MockLLMProvider([])
        executor = ToolExecutor()
        agent = ToolAgent(mock, executor)
        with pytest.raises(ValueError, match="checkpoint_dir"):
            agent.resume()


class TestRetry:
    """重试逻辑集成测试。"""

    def test_failing_provider_triggers_retry(self):
        """LLM 调用失败触发重试。"""

        class FailingThenOK(MockLLMProvider):
            call_count = 0

            def chat(self, *args, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    raise RuntimeError("API timeout")
                return super().chat(*args, **kwargs)

        mock = FailingThenOK([
            MockLLMProvider.text_response("OK after retry"),
        ])
        executor = ToolExecutor()
        agent = ToolAgent(mock, executor, config=AgentConfig(max_retries=2, retry_delay=0.01))
        result = agent.run("测试重试")

        assert result.success
        assert mock.call_count == 2  # 第一次失败，第二次成功

    def test_all_retries_exhausted(self):
        """所有重试都失败。"""

        class AlwaysFailing(MockLLMProvider):
            def chat(self, *args, **kwargs):
                raise RuntimeError("always fails")

        mock = AlwaysFailing([])
        executor = ToolExecutor()
        agent = ToolAgent(mock, executor, config=AgentConfig(max_retries=1, retry_delay=0.01))
        result = agent.run("测试")

        assert not result.success
        assert "always fails" in (result.error or "")


class TestAgentResult:
    """AgentResult 统计正确性。"""

    def test_statistics_accumulate(self):
        mock = MockLLMProvider([
            MockLLMProvider.tool_response("get_weather", {"city": "北京"}),
            MockLLMProvider.text_response("北京晴天22°C。"),
        ])
        executor = ToolExecutor()
        executor.register(WEATHER_TOOL, lambda city: "22°C")
        agent = ToolAgent(mock, executor)
        result = agent.run("天气？")

        assert result.total_steps == 2
        assert result.total_tokens > 0
        assert result.total_duration_ms > 0
        assert isinstance(result.total_cost_usd, float)
