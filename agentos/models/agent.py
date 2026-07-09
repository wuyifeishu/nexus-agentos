"""AgentOS Agent Models — request/response types for agent lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    """Agent run status."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING_TOOL = "waiting_tool"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class AgentRunRequest(BaseModel):
    """Request to run an agent."""

    agent_name: str = Field(description="Agent identifier")
    input: str = Field(description="User input/message to the agent")
    model: str | None = Field(default=None, description="Override the default model")
    max_tokens: int | None = Field(
        default=None, ge=1, le=128000, description="Max tokens for the response"
    )
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Sampling temperature"
    )
    stream: bool = Field(default=False, description="Enable SSE streaming")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary metadata for tracing"
    )
    context: dict[str, Any] | None = Field(
        default=None, description="Additional context injected into agent"
    )
    timeout_seconds: int | None = Field(
        default=None, ge=1, le=3600, description="Max execution time in seconds"
    )


class AgentRunResponse(BaseModel):
    """Response from an agent run."""

    run_id: str = Field(description="Unique run identifier")
    agent_name: str
    status: AgentStatus
    output: str | None = Field(default=None)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, int] | None = Field(default=None)
    duration_ms: float = Field(default=0.0)
    error: str | None = Field(default=None)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentInfo(BaseModel):
    """Static agent information."""

    name: str
    description: str = ""
    model: str = ""
    version: str = "1.0.0"
    tools: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentListResponse(BaseModel):
    """List of registered agents."""

    agents: list[AgentInfo] = Field(default_factory=list)
    total: int = 0
