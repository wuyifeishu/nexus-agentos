"""
AgentOS v0.30 FastAPI REST服务 — 暴露Agent能力。
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
import uuid

from agentos.core.loop import AgentLoop, AgentResult, LoopState


class RunRequest(BaseModel):
    """Agent 运行请求体。"""

    task: str
    session_id: str = ""
    stream: bool = False
    max_iterations: int = 100
    model: str = "auto"


class RunResponse(BaseModel):
    """Agent 运行响应体。"""

    session_id: str
    output: str
    iterations: int
    cost_usd: float
    tokens_used: dict
    duration_ms: float
    state: str
    error: str | None = None


class AgentAPI:
    """AgentOS REST API 服务。"""

    def __init__(self, loop: AgentLoop):
        self.loop = loop
        self.app = FastAPI(title="AgentOS v0.30", version="0.30.0")
        self._setup_middleware()
        self._setup_routes()

    def _setup_middleware(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        @self.app.get("/health")
        async def health():
            return {"status": "ok", "version": "0.30.0"}

        @self.app.post("/run", response_model=RunResponse)
        async def run_task(req: RunRequest):
            sid = req.session_id or str(uuid.uuid4())[:8]
            result = await self.loop.run(task=req.task, session_id=sid)
            return RunResponse(
                session_id=sid,
                output=result.output,
                iterations=result.iterations,
                cost_usd=result.cost_usd,
                tokens_used=result.tokens_used,
                duration_ms=result.duration_ms,
                state=result.final_state.value,
                error=result.error,
            )

        @self.app.post("/cancel/{session_id}")
        async def cancel(session_id: str):
            self.loop.cancel()
            return {"cancelled": True}

        @self.app.get("/sessions/{session_id}")
        async def get_session(session_id: str):
            ctx = self.loop.context_manager
            return {
                "session_id": session_id,
                "task": ctx.current_task,
                "step_count": ctx.step_count,
                "messages": len(ctx._messages),
            }

        @self.app.get("/costs")
        async def get_costs():
            return {
                "total_cost": self.loop.cost_tracker.total_cost,
                "total_tokens": self.loop.cost_tracker.total_tokens,
                "by_model": self.loop.cost_tracker.cost_by_model(),
                "records_count": len(self.loop.cost_tracker.records),
            }

        @self.app.get("/tools")
        async def list_tools():
            return {
                "count": len(self.loop.tool_registry._tools),
                "tools": [
                    {"name": t.name, "description": t.description, "is_read": t.is_read, "category": t.category}
                    for t in self.loop.tool_registry._tools.values()
                ],
            }

    def serve(self, host: str = "0.0.0.0", port: int = 8080):
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)
