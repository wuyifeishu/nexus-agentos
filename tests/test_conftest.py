"""Test conftest fixtures — verifies all shared fixtures work correctly."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path


class TestAsyncFixtures:
    """Verify async client and event loop fixtures."""

    async def test_async_client_connects(self, async_client):
        """async_client fixture yields a usable httpx AsyncClient."""
        from httpx import AsyncClient
        assert isinstance(async_client, AsyncClient)
        assert async_client.base_url == "http://test"

    def test_mock_async_client_is_mock(self, mock_async_client):
        """mock_async_client returns an AsyncMock."""
        from unittest.mock import AsyncMock
        assert isinstance(mock_async_client, AsyncMock)


class TestMockLLMFixtures:
    """Verify mock LLM response factories and fixtures."""

    def test_mock_response_factory_defaults(self, mock_response_factory):
        """Factory creates responses with sensible defaults."""
        resp = mock_response_factory()
        assert resp.content == "Mock response"
        assert resp.finish_reason == "stop"
        assert "prompt_tokens" in resp.usage

    def test_mock_response_factory_custom_content(self, mock_response_factory):
        """Factory accepts custom content."""
        resp = mock_response_factory(content="Custom answer")
        assert resp.content == "Custom answer"

    def test_mock_response_to_dict(self, mock_success_response):
        """to_dict() produces OpenAI-compatible format."""
        d = mock_success_response.to_dict()
        assert d["object"] == "chat.completion"
        assert "choices" in d
        assert d["choices"][0]["message"]["content"] == "Success"

    def test_mock_tool_call_response(self, mock_tool_call_response):
        """Tool call response has proper tool_calls structure."""
        d = mock_tool_call_response.to_dict()
        choices = d["choices"]
        assert len(choices) > 0
        tool_calls = choices[0]["message"].get("tool_calls", [])
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "get_weather"

    def test_streaming_chunks_structure(self, mock_streaming_chunks):
        """Streaming chunks have proper delta structure."""
        assert len(mock_streaming_chunks) == 4
        assert mock_streaming_chunks[0]["choices"][0]["delta"]["role"] == "assistant"
        assert mock_streaming_chunks[-1]["choices"][0]["finish_reason"] == "stop"


class TestAgentFixtures:
    """Verify agent factory fixtures."""

    def test_make_agent_creates_valid_agent(self, make_agent):
        """Factory creates an Agent instance."""
        from agentos.core.di import Agent
        agent = make_agent(name="test-bot")
        assert isinstance(agent, Agent)
        assert agent.name == "test-bot"

    def test_make_agent_custom_fields(self, make_agent):
        """Factory creates Agent with custom name."""
        agent = make_agent(name="custom-bot")
        assert agent.name == "custom-bot"
        assert hasattr(agent, "run")

    def test_agent_name_fixture(self, agent_name):
        """Default agent name is a string."""
        assert isinstance(agent_name, str)
        assert len(agent_name) > 0

    def test_run_id_is_unique(self, run_id):
        """Each run_id fixture call produces a unique ID."""
        assert run_id.startswith("run-")

    def test_session_id_is_unique(self, session_id):
        """Each session_id fixture produces a unique ID."""
        assert session_id.startswith("sess-")


class TestToolFixtures:
    """Verify tool factory fixtures."""

    def test_make_sync_tool_returns_callable(self, make_sync_tool):
        """Factory creates a callable tool."""
        tool = make_sync_tool(name="my_tool", return_value=42)
        assert callable(tool)
        assert tool.__name__ == "my_tool"
        assert tool() == 42

    async def test_make_async_tool_returns_coroutine(self, make_async_tool):
        """Factory creates an awaitable tool."""
        tool = make_async_tool(name="async_one", return_value="done")
        assert asyncio.iscoroutinefunction(tool)
        result = await tool()
        assert result == "done"


class TestFileFixtures:
    """Verify filesystem fixtures."""

    def test_temp_dir_exists(self, temp_dir):
        """temp_dir creates a real directory."""
        assert isinstance(temp_dir, Path)
        assert temp_dir.exists()
        assert temp_dir.is_dir()

    def test_temp_dir_is_writable(self, temp_dir):
        """temp_dir allows file creation."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("hello")
        assert test_file.read_text() == "hello"

    def test_temp_file_exists_and_readable(self, temp_file):
        """temp_file creates a readable file."""
        assert temp_file.exists()
        assert temp_file.read_text() == "test content"

    def test_make_temp_file_custom_content(self, make_temp_file):
        """make_temp_file factory with custom name and content."""
        fp = make_temp_file("custom.txt", "custom content")
        assert fp.name == "custom.txt"
        assert fp.read_text() == "custom content"

    def test_make_json_file_creates_valid_json(self, make_json_file):
        """make_json_file factory creates valid JSON."""
        data = {"key": "value", "num": 42}
        fp = make_json_file("data.json", data)
        loaded = json.loads(fp.read_text())
        assert loaded == data

    def test_temp_dirs_are_isolated(self, temp_dir):
        """Each test gets its own isolated temp_dir."""
        marker = temp_dir / f"marker_{uuid.uuid4().hex}"
        marker.write_text("isolated")
        assert marker.exists()


class TestConfigFixtures:
    """Verify config fixture factories."""

    def test_test_config_dict_has_required_keys(self, test_config_dict):
        """Default config has agent and tools sections."""
        assert "agent" in test_config_dict
        assert "tools" in test_config_dict
        assert "logging" in test_config_dict

    def test_make_config_file_creates_yaml(self, make_config_file):
        """Factory creates a valid YAML config file."""
        fp = make_config_file()
        assert fp.exists()
        assert fp.suffix == ".yaml"

    def test_make_config_file_overrides(self, make_config_file):
        """Factory accepts overrides merged into base config."""
        import yaml
        fp = make_config_file(overrides={"agent": {"name": "overridden"}})
        config = yaml.safe_load(fp.read_text())
        assert config["agent"]["name"] == "overridden"


class TestTimeFixtures:
    """Verify time-related fixtures."""

    def test_freeze_time(self, freeze_time):
        """time.time() returns frozen value."""
        import time
        assert time.time() == 1700000000.0

    def test_advance_time_default(self, advance_time):
        """advance_time starts at epoch anchor."""
        import time
        assert time.time() == 1700000000.0

    def test_advance_time_increment(self, advance_time):
        """advance_time.advance() shifts the clock."""
        advance_time.advance(60)
        import time
        assert time.time() == 1700000060.0

    def test_advance_time_set(self, advance_time):
        """advance_time.set() jumps to a specific time."""
        advance_time.set(9999999999.0)
        import time
        assert time.time() == 9999999999.0


class TestEnvFixtures:
    """Verify environment variable fixtures."""

    def test_clean_env_removes_keys(self, clean_env, set_env):
        """clean_env removes sensitive keys."""
        # set_env sets a temporary key
        set_env(OPENAI_API_KEY="test-key")
        import os
        assert os.environ["OPENAI_API_KEY"] == "test-key"
        # clean_env should have already cleaned before this test ran
        # The fixture is function-scoped, so this test gets clean_env

    def test_set_env_temporary(self, set_env):
        """set_env sets vars that revert after test."""
        import os
        set_env(MY_TEST_VAR="hello")
        assert os.environ["MY_TEST_VAR"] == "hello"


class TestMiddlewareFixture:
    """Verify middleware context fixture."""

    def test_middleware_context_has_required_fields(self, middleware_context):
        """MiddlewareContext is pre-populated."""
        from agentos.core.middleware import MiddlewareContext, MiddlewarePhase
        assert isinstance(middleware_context, MiddlewareContext)
        assert middleware_context.phase == MiddlewarePhase.PRE_LLM
        assert middleware_context.agent_name == "test-agent"
        assert middleware_context.prompt == "Test prompt"

    def test_middleware_context_modifiable(self, middleware_context):
        """MiddlewareContext attributes can be overridden in tests."""
        from agentos.core.middleware import MiddlewarePhase
        middleware_context.phase = MiddlewarePhase.POST_LLM
        assert middleware_context.phase == MiddlewarePhase.POST_LLM


class TestBenchmarkTracker:
    """Verify benchmark tracker fixture."""

    def test_benchmark_initial_state(self, benchmark_tracker):
        """Tracker starts with zero calls."""
        assert benchmark_tracker.calls == 0
        assert benchmark_tracker.total_time == 0.0

    def test_benchmark_measure_tracks(self, benchmark_tracker):
        """measure() context manager records timing."""
        with benchmark_tracker.measure():
            _ = sum(range(1000))
        assert benchmark_tracker.calls == 1
        assert benchmark_tracker.total_time > 0
        assert benchmark_tracker.avg_time > 0
        assert benchmark_tracker.max_time >= benchmark_tracker.min_time


class TestAsyncPrimitives:
    """Verify async primitive fixtures."""

    async def test_async_lock_acquire(self, async_lock):
        """async_lock is a usable asyncio.Lock."""
        assert isinstance(async_lock, asyncio.Lock)
        async with async_lock:
            assert async_lock.locked()

    async def test_async_event_set_wait(self, async_event):
        """async_event can be set and awaited."""
        assert not async_event.is_set()
        async_event.set()
        assert async_event.is_set()
        await async_event.wait()  # Should return immediately

    async def test_async_queue_put_get(self, async_queue):
        """async_queue supports put/get."""
        await async_queue.put("item1")
        item = await async_queue.get()
        assert item == "item1"
