"""Agent API — FastAPI REST endpoint for ProductionAgent.

Serves ProductionAgent as HTTP API with health check, metrics,
task dispatch, and streaming support.

v1.9.13: Initial — POST /run, /run/stream, GET /health, /stats.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agentos.agent.model_router import ModelRouter
from agentos.agent.production import ProductionAgent, ProductionConfig
from agentos.agent.tool_agent import ToolExecutor
from agentos.llm.base import LLMProvider
from agentos.llm.smart_cache import SmartCache

__all__ = [
    "AgentAPI",
    "AgentAPIRequest",
    "AgentAPIResponse",
    "AgentAPIStats",
    "create_agent_api",
]


# ── Pydantic Models ──────────────────────────────────────────────────


class AgentAPIRequest(BaseModel):
    task: str = Field(..., description="The task string to execute.")
    session_id: str | None = Field(
        default=None, description="Session identifier for audit log grouping."
    )
    budget_usd: float | None = Field(
        default=None, description="Override daily budget (default from config)."
    )
    enable_audit: bool = Field(default=True)
    enable_cache: bool = Field(default=True)


class AgentAPIResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"req-{uuid.uuid4().hex[:6]}")
    success: bool
    task: str
    output: str
    error: str | None = None
    model: str | None = None
    complexity: str | None = None
    total_steps: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    cache_hit: bool = False


class AgentAPIStats(BaseModel):
    uptime_seconds: float
    total_requests: int
    success_count: int
    failure_count: int
    avg_latency_ms: float
    total_cost_usd: float
    cache_hit_rate: float
    cache_savings_usd: float
    budget_remaining_usd: float


# ── Agent API Server ─────────────────────────────────────────────────


@dataclass
class AgentAPI:
    """FastAPI app wrapping a ProductionAgent.

    Usage:
        from agentos.server.agent_api import create_agent_api
        app = create_agent_api(provider, executor)
        # uvicorn.run(app, host="0.0.0.0", port=8000)

    Endpoints:
        POST /agent/run       — execute task synchronously
        POST /agent/run/stream — execute task with SSE streaming
        GET  /agent/health    — health check
        GET  /agent/stats     — runtime statistics
        GET  /agent/budget    — remaining budget info
    """

    provider: LLMProvider
    executor: ToolExecutor
    router: ModelRouter | None = None
    cache: SmartCache | None = None
    config: ProductionConfig = field(default_factory=ProductionConfig)

    # runtime stats
    _start_time: float = field(default_factory=time.time, init=False)
    _total_requests: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _failure_count: int = field(default=0, init=False)
    _total_latency_ms: float = field(default=0.0, init=False)

    def build_app(self) -> FastAPI:
        """Build and return a FastAPI app."""
        app = FastAPI(title="AgentOS Agent API", version="1.9.13")
        self_app = self

        # agent factory — per request to isolate state
        def _build_agent(
            enable_audit: bool = True,
            enable_cache: bool = True,
            budget_usd: float | None = None,
            session_id: str | None = None,
        ) -> ProductionAgent:
            cfg = ProductionConfig(
                enable_audit=enable_audit,
                enable_cache=enable_cache,
                audit_log_dir=self_app.config.audit_log_dir,
                budget_usd=budget_usd or self_app.config.budget_usd,
                session_id=session_id or "",
            )
            return ProductionAgent(
                provider=self_app.provider,
                tool_executor=self_app.executor,
                config=cfg,
                router=self_app.router,
                cache=self_app.cache,
            )

        @app.post("/agent/run", response_model=AgentAPIResponse)
        async def agent_run(req: AgentAPIRequest):
            self_app._total_requests += 1
            t0 = time.time()

            try:
                agent = _build_agent(
                    enable_audit=req.enable_audit,
                    enable_cache=req.enable_cache,
                    budget_usd=req.budget_usd,
                    session_id=req.session_id,
                )
                result = agent.run(req.task)
                elapsed_ms = (time.time() - t0) * 1000
                self_app._total_latency_ms += elapsed_ms

                if result.success:
                    self_app._success_count += 1
                else:
                    self_app._failure_count += 1

                last_text = ""
                if result.final_answer:
                    last_text = str(result.final_answer)
                elif result.steps:
                    last_text = str(
                        result.steps[-1].final_answer
                        if hasattr(result.steps[-1], "final_answer")
                        else ""
                    )

                cache_hit = agent.cache_hit_rate > 0 and result.success

                return AgentAPIResponse(
                    success=result.success,
                    task=req.task,
                    output=last_text,
                    error=result.error,
                    model=getattr(agent.last_model, "name", None),
                    complexity=None,
                    total_steps=result.total_steps,
                    total_tokens=result.total_tokens,
                    cost_usd=round(result.total_cost_usd, 6),
                    duration_ms=round(elapsed_ms, 2),
                    cache_hit=cache_hit,
                )

            except Exception as e:
                self_app._failure_count += 1
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/agent/run/stream")
        async def agent_run_stream(req: AgentAPIRequest):
            self_app._total_requests += 1

            try:
                agent = _build_agent(
                    enable_audit=req.enable_audit,
                    enable_cache=req.enable_cache,
                    budget_usd=req.budget_usd,
                    session_id=req.session_id,
                )

                async def event_stream() -> AsyncIterator[str]:
                    for step in agent.run_stream(req.task):
                        if hasattr(step, "to_dict"):
                            import json

                            yield f"data: {json.dumps(step.to_dict())}\n\n"
                        else:
                            yield f"data: {str(step)}\n\n"
                    yield "data: [DONE]\n\n"

                return StreamingResponse(
                    event_stream(),
                    media_type="text/event-stream",
                )

            except Exception as e:
                self_app._failure_count += 1
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/agent/health")
        async def agent_health():
            return {
                "status": "ok",
                "uptime_seconds": round(time.time() - self_app._start_time, 2),
                "provider": self_app.provider.provider_name,
                "model": self_app.provider.model_name,
                "cache_enabled": self_app.cache is not None,
                "router_enabled": self_app.router is not None,
            }

        @app.get("/agent/stats", response_model=AgentAPIStats)
        async def agent_stats():
            total = self_app._total_requests
            avg_lat = self_app._total_latency_ms / total if total > 0 else 0.0

            # build a temp agent to get latest budget cache stats
            agent = _build_agent()
            hit_rate = agent.cache_hit_rate
            savings = agent.cache_savings
            budget = agent._router.daily_budget_remaining if agent._router else 0.0

            total_cost = (
                agent._router._total_spent if hasattr(agent._router, "_total_spent") else 0.0
            )

            return AgentAPIStats(
                uptime_seconds=round(time.time() - self_app._start_time, 2),
                total_requests=total,
                success_count=self_app._success_count,
                failure_count=self_app._failure_count,
                avg_latency_ms=round(avg_lat, 2),
                total_cost_usd=round(total_cost, 6),
                cache_hit_rate=round(hit_rate, 4),
                cache_savings_usd=round(savings, 6),
                budget_remaining_usd=round(budget, 4),
            )

        @app.get("/agent/budget")
        async def agent_budget():
            agent = _build_agent()
            remaining = agent._router.daily_budget_remaining if agent._router else 0.0
            total_spent = getattr(agent._router, "_total_spent", 0.0)
            return {
                "daily_budget_usd": self_app.config.budget_usd,
                "remaining_usd": round(remaining, 4),
                "spent_usd": round(total_spent, 6),
                "usage_pct": round(
                    (
                        (total_spent / self_app.config.budget_usd * 100)
                        if self_app.config.budget_usd > 0
                        else 0
                    ),
                    2,
                ),
            }

        return app


# ── Factory ─────────────────────────────────────────────────────────


def create_agent_api(
    provider: LLMProvider,
    executor: ToolExecutor,
    *,
    router: ModelRouter | None = None,
    cache: SmartCache | None = None,
    config: ProductionConfig | None = None,
) -> FastAPI:
    """Create a FastAPI app with ProductionAgent endpoints.

    Args:
        provider: LLM provider for agent inference.
        executor: Tool executor with registered tools.
        router: Model router (auto-created if None).
        cache: SmartCache for response caching (optional).
        config: Production configuration (uses defaults if None).

    Returns:
        FastAPI application ready to serve.
    """
    api = AgentAPI(
        provider=provider,
        executor=executor,
        router=router,
        cache=cache,
        config=config or ProductionConfig(),
    )
    return api.build_app()
