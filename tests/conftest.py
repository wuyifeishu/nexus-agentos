"""AgentOS Conftest — shared fixtures, factories, and test infrastructure.

Provides reusable test primitives across all 64+ test modules:
- Async test client and event loop
- Mock LLM providers (streaming/non-streaming)
- Agent factories (minimal, configured, swarm)
- Tool factories (function, class-based, async)
- Resource lifecycle (temp files, mock servers)
- Benchmark suite configuration
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ============================================================================
# Event loop & async
# ============================================================================

@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default event loop policy for all tests."""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session")
def _session_event_loop(event_loop_policy):
    """Session-scoped event loop."""
    loop = event_loop_policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client for testing API endpoints.

    Yields an httpx AsyncClient with base URL pointed at the test server.
    Tests that don't need HTTP can use mock_async_client instead.
    """
    from agentos.api.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def mock_async_client() -> AsyncMock:
    """Mock async HTTP client — never touches network."""
    client = AsyncMock(spec=AsyncClient)
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    client.patch = AsyncMock()
    return client


# ============================================================================
# Mock LLM Providers
# ============================================================================

@dataclass
class MockLLMResponse:
    """Controlled LLM response for testing."""
    content: str = "Mock response"
    tool_calls: list[dict] | None = None
    finish_reason: str = "stop"
    usage: dict = field(default_factory=lambda: {
        "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150
    })

    def to_dict(self) -> dict:
        return {
            "id": f"mock-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "mock-model",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": self.content,
                    "tool_calls": self.tool_calls or [],
                },
                "finish_reason": self.finish_reason,
            }],
            "usage": self.usage,
        }


@pytest.fixture
def mock_response_factory() -> Callable[..., MockLLMResponse]:
    """Factory for creating mock LLM responses with custom content."""
    return MockLLMResponse


@pytest.fixture
def mock_success_response() -> MockLLMResponse:
    """Pre-built success response."""
    return MockLLMResponse(content="Success", finish_reason="stop")


@pytest.fixture
def mock_tool_call_response() -> MockLLMResponse:
    """Pre-built response with a function call."""
    return MockLLMResponse(
        content=None,
        tool_calls=[{
            "id": "call_abc123",
            "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"Beijing"}'},
        }],
        finish_reason="tool_calls",
    )


@pytest.fixture
def mock_streaming_chunks() -> list[dict]:
    """Mock SSE streaming chunks for testing streaming behavior."""
    return [
        {"id": "mock-1", "object": "chat.completion.chunk", "created": 1,
         "model": "mock", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"id": "mock-1", "object": "chat.completion.chunk", "created": 1,
         "model": "mock", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]},
        {"id": "mock-1", "object": "chat.completion.chunk", "created": 1,
         "model": "mock", "choices": [{"index": 0, "delta": {"content": " World"}, "finish_reason": None}]},
        {"id": "mock-1", "object": "chat.completion.chunk", "created": 1,
         "model": "mock", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]


# ============================================================================
# Agent fixtures & factories
# ============================================================================

@pytest.fixture
def agent_name() -> str:
    """Default test agent name."""
    return "test-agent"


@pytest.fixture
def run_id() -> str:
    """Unique run ID per test."""
    return f"run-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def session_id() -> str:
    """Unique session ID per test."""
    return f"sess-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def make_agent():
    """Factory fixture: create a minimal Agent with custom config.

    Usage:
        agent = make_agent(name="my-agent", model="gpt-4")
    """
    from agentos.core.di import Agent

    def _make(
        name: str = "test-agent",
        **kwargs,
    ) -> Agent:
        return Agent(name=name)

    return _make


# ============================================================================
# Tool fixtures & factories
# ============================================================================

@pytest.fixture
def make_sync_tool():
    """Factory for creating sync function tools."""
    def _make(name: str = "test_tool", return_value: Any = "tool_result"):
        def tool_fn(**kwargs) -> Any:
            return return_value
        tool_fn.__name__ = name
        return tool_fn
    return _make


@pytest.fixture
def make_async_tool():
    """Factory for creating async function tools."""
    def _make(name: str = "async_tool", return_value: Any = "async_result"):
        async def tool_fn(**kwargs) -> Any:
            await asyncio.sleep(0)
            return return_value
        tool_fn.__name__ = name
        return tool_fn
    return _make


# ============================================================================
# File system fixtures
# ============================================================================

@pytest.fixture
def temp_dir() -> Iterator[Path]:
    """Temporary directory that auto-cleans."""
    with tempfile.TemporaryDirectory(prefix="agentos_test_") as td:
        yield Path(td)


@pytest.fixture
def temp_file(temp_dir) -> Iterator[Path]:
    """Temporary file with unique content."""
    fp = temp_dir / f"test_file_{uuid.uuid4().hex[:8]}.txt"
    fp.write_text("test content", encoding="utf-8")
    yield fp


@pytest.fixture
def make_temp_file(temp_dir):
    """Factory: create a temp file with custom content and name."""
    def _make(name: str, content: str = "test") -> Path:
        fp = temp_dir / name
        fp.write_text(content, encoding="utf-8")
        return fp
    return _make


@pytest.fixture
def make_json_file(temp_dir):
    """Factory: create a temp JSON file."""
    def _make(name: str, data: dict) -> Path:
        fp = temp_dir / name
        fp.write_text(json.dumps(data), encoding="utf-8")
        return fp
    return _make


# ============================================================================
# Configuration fixtures
# ============================================================================

@pytest.fixture
def test_config_dict() -> dict:
    """Minimal valid AgentOS configuration."""
    return {
        "version": "1.0",
        "agent": {
            "name": "test-agent",
            "model": "mock-model",
            "max_tokens": 4096,
            "temperature": 0.7,
        },
        "tools": {"enabled": ["search", "file"]},
        "logging": {"level": "DEBUG"},
    }


@pytest.fixture
def make_config_file(temp_dir, test_config_dict):
    """Factory: create a config YAML file."""
    def _make(overrides: dict | None = None) -> Path:
        import yaml
        config = {**test_config_dict, **(overrides or {})}
        fp = temp_dir / f"config_{uuid.uuid4().hex[:8]}.yaml"
        fp.write_text(yaml.dump(config), encoding="utf-8")
        return fp
    return _make


# ============================================================================
# Time & concurrency helpers
# ============================================================================

@pytest.fixture
def freeze_time():
    """Freeze time.time() for deterministic testing."""
    with patch("time.time", return_value=1700000000.0):
        yield


@pytest.fixture
def advance_time():
    """Controllable clock for time-sensitive tests."""
    class Clock:
        def __init__(self):
            self._t = 1700000000.0
        def __call__(self):
            return self._t
        def advance(self, seconds: float):
            self._t += seconds
        def set(self, t: float):
            self._t = t
        @property
        def now(self):
            return self._t

    clock = Clock()
    with patch("time.time", clock):
        yield clock


@pytest.fixture
def lock() -> threading.Lock:
    """Thread-safe lock for testing concurrent access."""
    return threading.Lock()


# ============================================================================
# Environment variable helpers
# ============================================================================

@pytest.fixture
def clean_env():
    """Temporarily clean sensitive env vars."""
    sensitive = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"]
    saved = {k: os.environ.get(k) for k in sensitive}
    for k in sensitive:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


@pytest.fixture
def set_env():
    """Temporarily set environment variables."""
    _originals = {}

    def _set(**kwargs):
        for k, v in kwargs.items():
            _originals[k] = os.environ.get(k)
            os.environ[k] = str(v)

    yield _set
    for k, orig in _originals.items():
        if orig is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = orig


# ============================================================================
# UID / ID generation fixtures
# ============================================================================

@pytest.fixture
def predictable_uuid():
    """Predictable UUID for deterministic tests."""
    counter = 0

    def _uuid():
        nonlocal counter
        counter += 1
        return f"00000000-0000-4000-a000-{counter:012d}"

    with patch("uuid.uuid4", side_effect=lambda: uuid.UUID(_uuid())):
        yield


# ============================================================================
# Performance / benchmark helpers
# ============================================================================

@pytest.fixture
def benchmark_tracker():
    """Track execution counts and timings for performance assertions."""
    @dataclass
    class BenchmarkTracker:
        calls: int = 0
        total_time: float = 0.0
        max_time: float = 0.0
        min_time: float = float("inf")

        @contextmanager
        def measure(self):
            t0 = time.perf_counter()
            try:
                yield
            finally:
                elapsed = time.perf_counter() - t0
                self.calls += 1
                self.total_time += elapsed
                self.max_time = max(self.max_time, elapsed)
                self.min_time = min(self.min_time, elapsed)

        @property
        def avg_time(self) -> float:
            return self.total_time / max(self.calls, 1)

    return BenchmarkTracker()


# ============================================================================
# Async helpers
# ============================================================================

@pytest_asyncio.fixture
async def async_lock():
    """Async lock for concurrent test coordination."""
    return asyncio.Lock()


@pytest_asyncio.fixture
async def async_event():
    """Async event for test synchronization."""
    return asyncio.Event()


@pytest_asyncio.fixture
async def async_queue():
    """Async queue for producer-consumer test patterns."""
    return asyncio.Queue()


# ============================================================================
# Middleware test context
# ============================================================================

@pytest.fixture
def middleware_context() -> Any:
    """Pre-built middleware context for testing middleware components."""
    from agentos.core.middleware import MiddlewareContext, MiddlewarePhase
    return MiddlewareContext(
        phase=MiddlewarePhase.PRE_LLM,
        agent_name="test-agent",
        run_id="run-test-001",
        prompt="Test prompt",
        model_name="mock-model",
        metadata={"source": "test"},
    )


# ============================================================================
# Session context (for persistence tests)
# ============================================================================

@pytest.fixture
def test_session_context():
    """Minimal session context for testing session-aware components."""
    return {
        "session_id": f"sess-{uuid.uuid4().hex[:8]}",
        "user_id": "test-user-001",
        "workspace_id": "ws-test",
        "metadata": {},
    }
