"""Test AgentOS API Models — response envelopes, errors, pagination, agent models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from agentos.models.agent import (
    AgentInfo,
    AgentListResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentStatus,
)
from agentos.models.error import (
    AuthenticationError,
    AuthorizationError,
    ErrorCode,
    InternalError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)
from agentos.models.response import (
    APIErrorDetail,
    APIResponse,
    APIResponseMeta,
    HealthComponent,
    HealthResponse,
    PaginatedResponse,
    PaginationMeta,
    VersionResponse,
)

# ============================================================================
# APIResponse
# ============================================================================

class TestAPIResponse:
    """Envelope-level response model tests."""

    def test_success_response_defaults(self):
        """Minimal success response has correct defaults."""
        resp = APIResponse[str](success=True, data="hello")
        d = resp.model_dump()
        assert d["success"] is True
        assert d["data"] == "hello"
        assert d["error"] is None
        assert d["meta"]["version"] == "1.0"

    def test_error_response(self):
        """Error response includes error detail."""
        err = APIErrorDetail(
            title="Not Found",
            status=404,
            detail="Agent 'xyz' not found",
            code="NOT_FOUND",
        )
        resp = APIResponse[str](success=False, error=err)
        assert resp.success is False
        assert resp.data is None
        assert resp.error.title == "Not Found"
        assert resp.error.status == 404

    def test_meta_has_timestamp(self):
        """Meta always includes an ISO timestamp."""
        resp = APIResponse[str](success=True, data="x")
        assert "T" in resp.meta.timestamp  # ISO 8601

    def test_meta_request_id_default_empty(self):
        """request_id defaults to empty string."""
        meta = APIResponseMeta()
        assert meta.request_id == ""

    def test_meta_custom_request_id(self):
        """request_id can be set for tracing."""
        meta = APIResponseMeta(request_id="req-abc-123")
        assert meta.request_id == "req-abc-123"

    def test_generic_type_parameter(self):
        """Generic[T] preserves type at runtime."""
        resp = APIResponse[int](success=True, data=42)
        assert resp.data == 42

    def test_none_data_on_success(self):
        """Success with data=None is valid (e.g., 204 No Content)."""
        resp = APIResponse[dict](success=True, data=None)
        assert resp.success is True
        assert resp.data is None


# ============================================================================
# PaginatedResponse
# ============================================================================

class TestPaginatedResponse:
    """Pagination model tests."""

    def test_empty_page(self):
        """Empty paginated response is valid."""
        resp = PaginatedResponse[str](
            data=[],
            pagination=PaginationMeta(total_items=0, total_pages=0),
        )
        assert resp.data == []
        assert resp.pagination.total_items == 0

    def test_single_page(self):
        """Single page with all items."""
        resp = PaginatedResponse[int](
            data=[1, 2, 3],
            pagination=PaginationMeta(
                page=1, page_size=10, total_items=3, total_pages=1,
            ),
        )
        assert len(resp.data) == 3
        assert resp.pagination.page == 1
        assert resp.pagination.total_pages == 1
        assert resp.pagination.has_next is False
        assert resp.pagination.has_prev is False

    def test_multi_page(self):
        """Multi-page with correct has_next."""
        resp = PaginatedResponse[int](
            data=[11, 12, 13],
            pagination=PaginationMeta(
                page=2, page_size=3, total_items=10, total_pages=4,
            ),
        )
        assert resp.pagination.has_next is True
        assert resp.pagination.has_prev is True

    def test_pagination_computes_total_pages(self):
        """total_pages auto-computed when 0 with total_items > 0."""
        meta = PaginationMeta(page_size=10, total_items=25, total_pages=0)
        # Validator should compute 3
        assert meta.total_pages == 3

    def test_last_page_no_next(self):
        """Last page has_next=False."""
        meta = PaginationMeta(page=3, page_size=10, total_items=25, total_pages=3)
        assert meta.has_next is False

    def test_page_size_bounds(self):
        """page_size must be 1-200."""
        with pytest.raises(PydanticValidationError):
            PaginationMeta(page_size=0)
        with pytest.raises(PydanticValidationError):
            PaginationMeta(page_size=201)


# ============================================================================
# APIErrorDetail
# ============================================================================

class TestAPIErrorDetail:
    """RFC 9457 Problem Details model tests."""

    def test_minimal_error(self):
        """Minimal error with required fields."""
        err = APIErrorDetail(title="Bad Request", status=400)
        assert err.title == "Bad Request"
        assert err.status == 400
        assert err.type == "about:blank"
        assert err.code == "INTERNAL_ERROR"

    def test_full_error(self):
        """Full error with all fields."""
        err = APIErrorDetail(
            type="https://errors.agentos.dev/validation",
            title="Validation Error",
            status=422,
            detail="Field 'email' must be valid",
            instance="/api/v1/agents/run",
            code="VALIDATION_ERROR",
            field="email",
        )
        assert err.code == "VALIDATION_ERROR"
        assert err.field == "email"
        assert "email" in err.detail

    def test_status_bounds(self):
        """status must be 100-599."""
        with pytest.raises(PydanticValidationError):
            APIErrorDetail(title="Invalid", status=600)
        with pytest.raises(PydanticValidationError):
            APIErrorDetail(title="Invalid", status=99)


# ============================================================================
# Error hierarchy
# ============================================================================

class TestErrorHierarchy:
    """Test the typed exception hierarchy."""

    def test_agentos_error_is_http_exception(self):
        """All errors extend FastAPI HTTPException."""
        err = InternalError("boom")
        from fastapi import HTTPException
        assert isinstance(err, HTTPException)

    def test_error_code_enum_values(self):
        """ErrorCode enum has expected values."""
        assert ErrorCode.VALIDATION_ERROR.value == "VALIDATION_ERROR"
        assert ErrorCode.NOT_FOUND.value == "NOT_FOUND"
        assert ErrorCode.RATE_LIMITED.value == "RATE_LIMITED"

    def test_not_found_default_message(self):
        """NotFoundError with resource type and id."""
        err = NotFoundError("Agent", "agent-001")
        assert err.status_code == 404
        assert err.code == ErrorCode.NOT_FOUND
        assert "agent-001" in err.detail

    def test_not_found_no_identifier(self):
        """NotFoundError without id."""
        err = NotFoundError("Session")
        assert "Session not found" == err.detail

    def test_validation_error_accumulation(self):
        """ValidationError accumulates field errors."""
        err = ValidationError(detail="Bad input", field="name")
        assert len(err.errors) == 1
        err.add_error("email", "Invalid format")
        assert len(err.errors) == 2
        assert err.has_errors is True

    def test_validation_error_to_dict(self):
        """ValidationError.to_dict() includes errors list."""
        err = ValidationError(detail="Invalid", field="x")
        d = err.to_dict()
        assert "errors" in d
        assert len(d["errors"]) == 1

    def test_authentication_error(self):
        """AuthenticationError has 401."""
        err = AuthenticationError("Token expired")
        assert err.status_code == 401
        assert err.code == ErrorCode.UNAUTHENTICATED

    def test_authorization_error(self):
        """AuthorizationError has 403."""
        err = AuthorizationError("No admin access")
        assert err.status_code == 403
        assert err.code == ErrorCode.UNAUTHORIZED

    def test_rate_limit_error_with_retry_after(self):
        """RateLimitError sets Retry-After header."""
        err = RateLimitError(retry_after=60)
        assert err.status_code == 429
        assert err.code == ErrorCode.RATE_LIMITED
        assert err.headers["Retry-After"] == "60"

    def test_rate_limit_error_no_retry_after(self):
        """RateLimitError without retry_after has no header."""
        err = RateLimitError("Chill out")
        assert "Retry-After" not in err.headers

    def test_internal_error_is_500(self):
        """InternalError always 500."""
        err = InternalError()
        assert err.status_code == 500

    def test_service_unavailable(self):
        """ServiceUnavailableError has 503."""
        err = ServiceUnavailableError(retry_after=120)
        assert err.status_code == 503
        assert err.code == ErrorCode.SERVICE_UNAVAILABLE
        assert err.headers["Retry-After"] == "120"

    def test_to_api_error_dict(self):
        """to_api_error() produces APIErrorDetail-compatible dict."""
        err = NotFoundError("File", "/tmp/x.txt")
        d = err.to_api_error()
        assert d["status"] == 404
        assert d["code"] == "NOT_FOUND"
        assert "type" in d
        assert "title" in d


# ============================================================================
# Health & Version
# ============================================================================

class TestHealthModels:
    """Health check models."""

    def test_health_component_minimal(self):
        """Minimal HealthComponent."""
        c = HealthComponent(name="db", status="healthy", latency_ms=2.5)
        assert c.status == "healthy"
        assert c.name == "db"

    def test_health_component_with_error(self):
        """Degraded component with error message."""
        c = HealthComponent(
            name="redis", status="unhealthy", latency_ms=3000.0,
            error="Connection refused",
        )
        assert c.error == "Connection refused"

    def test_health_response(self):
        """Full health response."""
        h = HealthResponse(
            status="healthy",
            uptime_seconds=3600.0,
            components=[
                HealthComponent(name="api", status="healthy", latency_ms=1.0),
            ],
        )
        assert h.status == "healthy"
        assert len(h.components) == 1
        assert "T" in h.timestamp

    def test_version_response(self):
        """Version response includes all fields."""
        v = VersionResponse(
            version="1.17.0",
            build="abc123",
            commit_sha="a1b2c3d",
            python_version="3.12",
            environment="staging",
        )
        assert v.version == "1.17.0"
        assert v.build == "abc123"
        assert v.environment == "staging"


# ============================================================================
# Agent models
# ============================================================================

class TestAgentModels:
    """Agent request/response model tests."""

    def test_agent_run_request_valid(self):
        """Minimal valid request."""
        req = AgentRunRequest(agent_name="my-agent", input="Hello")
        assert req.agent_name == "my-agent"
        assert req.input == "Hello"
        assert req.stream is False
        assert req.metadata == {}

    def test_agent_run_request_with_options(self):
        """Full request with all optional fields."""
        req = AgentRunRequest(
            agent_name="assistant",
            input="Summarize",
            model="gpt-4",
            max_tokens=2048,
            temperature=0.5,
            stream=True,
            timeout_seconds=30,
            metadata={"source": "slack"},
            context={"thread_id": "t-001"},
        )
        assert req.model == "gpt-4"
        assert req.temperature == 0.5
        assert req.timeout_seconds == 30
        assert req.context["thread_id"] == "t-001"

    def test_agent_run_request_max_tokens_bounds(self):
        """max_tokens must be 1-128000."""
        with pytest.raises(PydanticValidationError):
            AgentRunRequest(agent_name="a", input="x", max_tokens=0)
        with pytest.raises(PydanticValidationError):
            AgentRunRequest(agent_name="a", input="x", max_tokens=200000)

    def test_agent_run_request_temperature_bounds(self):
        """temperature must be 0.0-2.0."""
        with pytest.raises(PydanticValidationError):
            AgentRunRequest(agent_name="a", input="x", temperature=-0.1)
        with pytest.raises(PydanticValidationError):
            AgentRunRequest(agent_name="a", input="x", temperature=2.1)

    def test_agent_run_request_timeout_bounds(self):
        """timeout_seconds must be 1-3600."""
        with pytest.raises(PydanticValidationError):
            AgentRunRequest(agent_name="a", input="x", timeout_seconds=0)

    def test_agent_run_response(self):
        """Response has all fields."""
        resp = AgentRunResponse(
            run_id="run-001",
            agent_name="test-agent",
            status=AgentStatus.COMPLETED,
            output="Done",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            duration_ms=1234.5,
        )
        assert resp.status == AgentStatus.COMPLETED
        assert resp.duration_ms == 1234.5
        assert resp.usage["total_tokens"] == 150

    def test_agent_status_enum_values(self):
        """AgentStatus has all expected states."""
        assert AgentStatus.IDLE.value == "idle"
        assert AgentStatus.RUNNING.value == "running"
        assert AgentStatus.FAILED.value == "failed"

    def test_agent_info_minimal(self):
        """Minimal AgentInfo."""
        info = AgentInfo(name="bot")
        assert info.name == "bot"
        assert info.tools == []

    def test_agent_list_response(self):
        """AgentListResponse with multiple agents."""
        agents = [
            AgentInfo(name="a", description="Agent A"),
            AgentInfo(name="b", description="Agent B"),
        ]
        resp = AgentListResponse(agents=agents, total=2)
        assert len(resp.agents) == 2
        assert resp.total == 2
