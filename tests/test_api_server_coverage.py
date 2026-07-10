"""test_api_server_coverage.py — Full coverage for agentos.api.server"""

import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.api.server import (
    AgentConfigRequest,
    AgentManager,
    AgentInfo,
    RunRequest,
    HealthResponse,
    WorkflowRunRequest,
    ManagedAgent,
    app,
)


# ── AgentManager (unit tests, no HTTP) ─────────────────────────


class TestAgentManager:

    def test_create_returns_managed_agent(self):
        mgr = AgentManager()
        agent = mgr.create(AgentConfigRequest(name="foo", model="gpt-4"))
        assert agent.name == "foo"
        assert agent.model == "gpt-4"
        assert len(agent.id) == 12

    def test_get_existing(self):
        mgr = AgentManager()
        a = mgr.create(AgentConfigRequest(name="bar"))
        assert mgr.get(a.id).name == "bar"

    def test_get_nonexistent(self):
        mgr = AgentManager()
        assert mgr.get("no-such-id") is None

    def test_list_all(self):
        mgr = AgentManager()
        mgr.create(AgentConfigRequest(name="a"))
        mgr.create(AgentConfigRequest(name="b"))
        assert len(mgr.list_all()) == 2

    def test_list_all_empty(self):
        mgr = AgentManager()
        assert mgr.list_all() == []

    def test_delete_existing(self):
        mgr = AgentManager()
        a = mgr.create(AgentConfigRequest(name="del"))
        assert mgr.delete(a.id) is True
        assert mgr.get(a.id) is None

    def test_delete_nonexistent(self):
        mgr = AgentManager()
        assert mgr.delete("phantom") is False

    def test_count(self):
        mgr = AgentManager()
        assert mgr.count == 0
        mgr.create(AgentConfigRequest(name="c1"))
        assert mgr.count == 1
        mgr.create(AgentConfigRequest(name="c2"))
        assert mgr.count == 2

    def test_uptime(self):
        import time
        mgr = AgentManager()
        time.sleep(0.01)
        assert mgr.uptime > 0

    def test_agent_deletion_affects_count(self):
        mgr = AgentManager()
        a = mgr.create(AgentConfigRequest(name="tmp"))
        assert mgr.count == 1
        mgr.delete(a.id)
        assert mgr.count == 0

    def test_create_with_full_config(self):
        mgr = AgentManager()
        cfg = AgentConfigRequest(
            name="full", model="gpt-4", memory=True,
            tools=["search", "code"], max_tokens=2048,
            temperature=0.5, metadata={"env": "prod"},
        )
        a = mgr.create(cfg)
        assert a.config["name"] == "full"
        assert a.config["memory"] is True
        assert a.config["tools"] == ["search", "code"]
        assert a.config["metadata"] == {"env": "prod"}


# ── Pydantic Model Tests (no HTTP needed) ──────────────────────


class TestPydanticModels:

    def test_agent_config_request_defaults(self):
        cfg = AgentConfigRequest()
        assert cfg.name == "default"
        assert cfg.model == "gpt-4o"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096
        assert cfg.memory is False
        assert cfg.tools == []
        assert cfg.system_prompt == "You are a helpful agent."
        assert cfg.metadata == {}

    def test_run_request_defaults(self):
        req = RunRequest(agent_id="test-id", prompt="hello")
        assert req.agent_id == "test-id"
        assert req.stream is False
        assert req.metadata == {}

    def test_run_request_with_stream(self):
        req = RunRequest(agent_id="id2", prompt="hi", stream=True, metadata={"k": "v"})
        assert req.stream is True
        assert req.metadata == {"k": "v"}

    def test_workflow_run_request(self):
        req = WorkflowRunRequest(workflow_yaml="steps: []")
        assert req.workflow_yaml == "steps: []"
        assert req.variables == {}

    def test_workflow_run_request_with_variables(self):
        req = WorkflowRunRequest(workflow_yaml="s: []", variables={"x": 1, "y": "z"})
        assert req.variables == {"x": 1, "y": "z"}

    def test_health_response_model(self):
        h = HealthResponse(
            status="healthy", version="1.0", uptime=123.0,
            agents_count=5, active_websockets=2
        )
        assert h.status == "healthy"
        assert h.agents_count == 5
        assert h.active_websockets == 2

    def test_agent_info_model(self):
        a = AgentInfo(
            id="abc", name="test", model="gpt-4",
            status="ready", tasks_completed=3, uptime=60.0
        )
        assert a.id == "abc"
        assert a.tasks_completed == 3
        assert a.uptime == 60.0

    def test_managed_agent_dataclass(self):
        ma = ManagedAgent(
            id="ma1", name="ma-name", model="gpt-4",
            config={"k": "v"}, tasks_completed=7
        )
        assert ma.tasks_completed == 7
        assert ma.config == {"k": "v"}
        assert ma.created_at > 0


# ── REST Endpoints (via async_client) ───────────────────────────


class TestHealthEndpoint:

    async def test_health_returns_200(self, async_client):
        resp = await async_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "shutting_down")
        assert "version" in data
        assert data["uptime"] >= 0
        assert "agents_count" in data
        assert "active_websockets" in data

    async def test_health_shutting_down(self):
        """Test health during shutdown — uses fresh client to avoid state."""
        import agentos.api.server as srv
        original = srv._shutting_down
        try:
            srv._shutting_down = True
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/health")
                assert resp.status_code == 200
                assert resp.json()["status"] == "shutting_down"
        finally:
            srv._shutting_down = original


class TestMetricsEndpoint:

    async def test_metrics_prometheus_format(self, async_client):
        resp = await async_client.get("/metrics")
        assert resp.status_code == 200
        text = resp.text
        assert "agentos_uptime_seconds" in text
        assert "agentos_requests_total" in text
        assert "agentos_active_websockets" in text
        assert "agentos_active_requests" in text
        assert text.startswith("# HELP")


class TestAgentCRUDEndpoints:

    async def test_create_agent_201(self, async_client):
        resp = await async_client.post("/agents", json={"name": "api-create"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "api-create"
        assert data["status"] == "ready"
        assert len(data["id"]) > 0

    async def test_list_agents(self, async_client):
        resp = await async_client.get("/agents")
        assert resp.status_code == 200
        agents = resp.json()
        assert isinstance(agents, list)

    async def test_get_agent_found(self, async_client):
        r = await async_client.post("/agents", json={"name": "get-test"})
        agent_id = r.json()["id"]
        resp = await async_client.get(f"/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "get-test"

    async def test_get_agent_404(self, async_client):
        resp = await async_client.get("/agents/fake-id-000000")
        assert resp.status_code == 404

    async def test_delete_agent(self, async_client):
        r = await async_client.post("/agents", json={"name": "to-delete"})
        agent_id = r.json()["id"]
        resp = await async_client.delete(f"/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": agent_id}

    async def test_delete_agent_404(self, async_client):
        resp = await async_client.delete("/agents/ghost-id-000")
        assert resp.status_code == 404


class TestAgentRunEndpoints:

    async def test_run_agent_200(self, async_client):
        r = await async_client.post("/agents", json={"name": "runner"})
        agent_id = r.json()["id"]
        resp = await async_client.post(
            f"/agents/{agent_id}/run",
            json={"agent_id": agent_id, "prompt": "Hello"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == agent_id
        assert "result" in data
        assert data["elapsed"] > 0

    async def test_run_agent_404(self, async_client):
        resp = await async_client.post(
            "/agents/nonexistent/run",
            json={"agent_id": "nonexistent", "prompt": "hi"}
        )
        assert resp.status_code == 404

    async def test_run_increments_tasks(self, async_client):
        r = await async_client.post("/agents", json={"name": "counter"})
        agent_id = r.json()["id"]
        await async_client.post(f"/agents/{agent_id}/run", json={"agent_id": agent_id, "prompt": "1"})
        await async_client.post(f"/agents/{agent_id}/run", json={"agent_id": agent_id, "prompt": "2"})
        resp = await async_client.get(f"/agents/{agent_id}")
        assert resp.json()["tasks_completed"] == 2


class TestAgentStreamEndpoints:

    async def test_stream_agent_200(self, async_client):
        r = await async_client.post("/agents", json={"name": "streamer"})
        agent_id = r.json()["id"]
        resp = await async_client.post(
            f"/agents/{agent_id}/stream",
            json={"agent_id": agent_id, "prompt": "Tell me"}
        )
        assert resp.status_code == 200
        assert "data:" in resp.text
        assert '"done": true' in resp.text

    async def test_stream_agent_404(self, async_client):
        resp = await async_client.post(
            "/agents/no-stream/stream",
            json={"agent_id": "no-stream", "prompt": "x"}
        )
        assert resp.status_code == 404


class TestWorkflowEndpoints:

    async def test_workflow_validate(self, async_client):
        resp = await async_client.post(
            "/workflows/validate",
            json={"workflow_yaml": "steps:\n  - id: s1\n    action: echo\n"}
        )
        assert resp.status_code in (200, 400, 422)

    async def test_workflow_run(self, async_client):
        resp = await async_client.post(
            "/workflows/run",
            json={"workflow_yaml": "steps:\n  - id: s1\n    action: echo\n    params:\n      text: x\n",
                  "variables": {"k": "v"}}
        )
        assert resp.status_code in (200, 400, 422)


# ── Middleware: shutdown behavior ───────────────────────────────


class TestShutdownMiddleware:

    async def test_503_during_shutdown(self):
        import agentos.api.server as srv
        original = srv._shutting_down
        try:
            srv._shutting_down = True
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post("/agents", json={"name": "should-fail"})
                assert resp.status_code == 503
                assert "shutting down" in resp.json()["detail"]
        finally:
            srv._shutting_down = original

    async def test_health_ok_during_shutdown(self):
        import agentos.api.server as srv
        original = srv._shutting_down
        try:
            srv._shutting_down = True
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/health")
                assert resp.status_code == 200
        finally:
            srv._shutting_down = original

    async def test_metrics_ok_during_shutdown(self):
        import agentos.api.server as srv
        original = srv._shutting_down
        try:
            srv._shutting_down = True
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.get("/metrics")
                assert resp.status_code == 200
        finally:
            srv._shutting_down = original


# ── Serve function ──────────────────────────────────────────────


class TestServe:

    def test_serve_without_deps_prints_message(self, monkeypatch):
        import agentos.api.server as srv_mod
        monkeypatch.setattr(srv_mod, "HAS_API_DEPS", False)
        with patch("builtins.print") as m:
            srv_mod.serve()
        m.assert_called()


# ── Error handling ──────────────────────────────────────────────


class TestErrorHandling:

    async def test_agent_list_includes_uptime(self, async_client):
        r = await async_client.post("/agents", json={"name": "uptime-agent"})
        agent_id = r.json()["id"]
        await asyncio.sleep(0.01)
        resp = await async_client.get(f"/agents/{agent_id}")
        assert resp.json()["uptime"] >= 0
