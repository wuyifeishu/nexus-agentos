"""
AgentOS v0.95 Testing Fixtures — 可复用测试基础设施。

提供 mock 对象工厂、预设配置 fixtures、临时文件上下文，
供单元测试和集成测试共用。
"""

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


# ─── Mock LLM ───────────────────────────────────────────────

@dataclass
class MockLLMResponse:
    """Mock LLM 响应。"""
    content: str = "This is a mock LLM response."
    model: str = "mock-gpt-4"
    usage: Dict[str, int] = field(default_factory=lambda: {
        "prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80
    })
    finish_reason: str = "stop"
    tool_calls: Optional[List[Dict]] = None


class MockLLMClient:
    """可配置的 Mock LLM 客户端，支持预设响应序列和工具调用。"""

    def __init__(self, responses: Optional[List[MockLLMResponse]] = None):
        self.responses = responses or [MockLLMResponse()]
        self._idx = 0
        self.calls: List[Dict] = []

    async def chat(self, messages: List[Dict], **kwargs) -> MockLLMResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        resp = self.responses[min(self._idx, len(self.responses) - 1)]
        self._idx += 1
        return resp

    def reset(self):
        self._idx = 0
        self.calls.clear()


# ─── Fixture 工厂 ────────────────────────────────────────────

def mock_openai_client():
    """创建一个完整的 mock OpenAI client。"""
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="mock response"))],
        model="mock-gpt-4",
        usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    return client


def mock_model_response(content: str = "ok", model: str = "mock-model"):
    return MockLLMResponse(content=content, model=model)


def sample_config(overrides: Optional[Dict] = None) -> Dict[str, Any]:
    """返回一份可用于测试的完整 AgentOSConfig 字典。"""
    base = {
        "models": {
            "default": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.7},
            "fast": {"provider": "openai", "model": "gpt-4o-mini", "temperature": 0.3},
        },
        "loop": {"max_iterations": 10, "timeout_seconds": 30},
        "memory": {"backend": "short_term", "max_tokens": 8000},
        "security": {"guardrails_enabled": True, "pii_sanitize": True},
        "observability": {"metrics_enabled": False, "tracing_enabled": False},
    }
    if overrides:
        _deep_merge(base, overrides)
    return base


def sample_loop_config(overrides: Optional[Dict] = None) -> Dict[str, Any]:
    """返回 LoopConfig 字典。"""
    base = {"max_iterations": 5, "timeout_seconds": 15, "reflection_enabled": True}
    if overrides:
        base.update(overrides)
    return base


@contextmanager
def temp_workspace(suffix: str = ""):
    """创建临时工作目录，yield Path 对象，退出时清理。"""
    d = tempfile.mkdtemp(suffix=f"_agentos_test{suffix}")
    try:
        yield Path(d)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def mock_memory_store():
    """返回一个 dict-backed 模拟 memory store。"""
    store = {"messages": [], "summary": "", "entities": {}}
    return store


def sample_agent_state(state: str = "idle", context: Optional[Dict] = None):
    """返回一份预设的 AgentState 字典。"""
    return {
        "state": state,
        "iteration": 0,
        "total_tokens": 0,
        "total_cost": 0.0,
        "context": context or {"task": "test task"},
        "history": [],
    }


def sample_audit_report():
    """返回一份预设的 AuditReport 字典。"""
    return {
        "findings": [
            {"severity": "low", "category": "code_injection", "description": "eval() usage detected", "location": "test.py:42"},
            {"severity": "info", "category": "best_practice", "description": "hardcoded secret pattern", "location": "config.py:11"},
        ],
        "summary": {"critical": 0, "high": 0, "medium": 0, "low": 1, "info": 1},
        "score": 85,
    }


def sample_health_status(healthy: bool = True):
    """返回一份预设的 HealthStatus 字典。"""
    return {
        "status": "healthy" if healthy else "degraded",
        "checks": [
            {"name": "openai_connectivity", "pass": True, "latency_ms": 120},
            {"name": "disk_space", "pass": True, "free_gb": 42.0},
            {"name": "memory", "pass": True, "used_percent": 35.0},
        ],
        "timestamp": "2025-01-01T00:00:00Z",
    }


def sample_docker_config():
    """返回一份预设的 DockerConfig 字典。"""
    return {
        "image": "agentos:latest",
        "ports": {"8000/tcp": 8000},
        "volumes": {"./data": "/app/data"},
        "environment": {"LOG_LEVEL": "INFO"},
        "healthcheck": {"test": "curl -f localhost:8000/health", "interval": "30s"},
    }


def sample_middleware_stack():
    """返回一份预设的 MiddlewareStack 配置字典。"""
    return {
        "cors": {"allowed_origins": ["*"], "allowed_methods": ["GET", "POST"]},
        "auth": {"enabled": True, "token_header": "X-API-Key"},
        "request_id": {"enabled": True, "header_name": "X-Request-ID"},
        "request_log": {"enabled": True, "log_body": False},
    }


def sample_alert_config():
    """返回一份预设的 AlertConfig 字典。"""
    return {
        "rules": [
            {"name": "high_latency", "condition": "latency_p95 > 5000", "severity": "warning"},
            {"name": "error_rate", "condition": "error_rate > 0.05", "severity": "critical"},
        ],
        "webhooks": [{"url": "https://hooks.slack.com/test", "channel": "#alerts"}],
    }


# ─── 辅助 ────────────────────────────────────────────────────

def _deep_merge(base: Dict, override: Dict):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
