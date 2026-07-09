"""AgentOS Response Models — RFC 9457 compatible, OpenAPI-ready.

Provides the canonical API response envelope used across all endpoints.
All responses are wrapped in APIResponse[T] for consistency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

T = TypeVar("T")


# ============================================================================
# Meta & pagination
# ============================================================================


class APIResponseMeta(BaseModel):
    """Response metadata: timing, version, request tracking."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 response timestamp",
    )
    version: str = Field(default="1.0", description="API version")
    request_id: str = Field(default="", description="Unique request ID for tracing")


class PaginationMeta(BaseModel):
    """Cursor-based pagination metadata."""

    page: int = Field(default=1, ge=1, description="Current page (1-based)")
    page_size: int = Field(default=20, ge=1, le=200, description="Items per page")
    total_items: int = Field(default=0, ge=0, description="Total matching items")
    total_pages: int = Field(default=0, ge=0, description="Total pages")
    next_cursor: str | None = Field(default=None, description="Opaque cursor for next page")
    has_next: bool = Field(default=False, description="Whether a next page exists")
    has_prev: bool = Field(default=False, description="Whether a previous page exists")

    @field_validator("total_pages", mode="before")
    @classmethod
    def compute_total_pages(cls, v, info):
        if v == 0 and info.data.get("total_items", 0) > 0:
            page_size = info.data.get("page_size", 20)
            return max(1, (info.data["total_items"] + page_size - 1) // page_size)
        return v

    @model_validator(mode="after")
    def compute_pagination_flags(self):
        self.has_next = self.page < self.total_pages
        self.has_prev = self.page > 1
        return self


# ============================================================================
# Error detail (RFC 9457 Problem Details)
# ============================================================================


class APIErrorDetail(BaseModel):
    """Single error entry conforming to RFC 9457 Problem Details."""

    type: str = Field(
        default="about:blank",
        description="URI reference identifying the problem type",
    )
    title: str = Field(description="Short, human-readable summary")
    status: int = Field(default=500, ge=100, le=599)
    detail: str = Field(default="", description="Human-readable explanation")
    instance: str | None = Field(
        default=None, description="URI reference identifying the specific occurrence"
    )
    code: str = Field(default="INTERNAL_ERROR", description="Machine-readable error code")
    field: str | None = Field(default=None, description="Field name for validation errors")


# ============================================================================
# Response envelope
# ============================================================================


class APIResponse(BaseModel, Generic[T]):
    """Canonical API response envelope.

    All endpoints return this structure with the generic type T for the data field.

    Success:
        {"success": true, "data": {...}, "meta": {...}}

    Error:
        {"success": false, "error": {...}, "meta": {...}}
    """

    success: bool = Field(default=True, description="Whether the request succeeded")
    data: T | None = Field(default=None, description="Response payload")
    error: APIErrorDetail | None = Field(
        default=None, description="Error detail (only when success=False)"
    )
    meta: APIResponseMeta = Field(default_factory=APIResponseMeta, description="Response metadata")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response."""

    success: bool = Field(default=True)
    data: list[T] = Field(default_factory=list, description="Page items")
    pagination: PaginationMeta = Field(
        default_factory=PaginationMeta, description="Pagination metadata"
    )
    meta: APIResponseMeta = Field(default_factory=APIResponseMeta, description="Response metadata")


# ============================================================================
# Health & version
# ============================================================================


class HealthComponent(BaseModel):
    """Individual component health status."""

    name: str
    status: str = Field(description="healthy | degraded | unhealthy")
    latency_ms: float = Field(default=0.0, description="Check latency in ms")
    error: str | None = Field(default=None)


class HealthResponse(BaseModel):
    """Full health check response."""

    status: str = Field(description="healthy | degraded | unhealthy")
    uptime_seconds: float
    components: list[HealthComponent] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class VersionResponse(BaseModel):
    """Version info response."""

    version: str
    build: str = ""
    commit_sha: str | None = None
    python_version: str = ""
    environment: str = "production"
