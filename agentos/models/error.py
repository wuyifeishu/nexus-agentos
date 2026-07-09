"""AgentOS Error Models — typed HTTP exceptions for the API layer.

Provides a hierarchy of FastAPI-compatible HTTP exceptions with:
- Machine-readable error codes
- RFC 9457 problem detail fields
- Structured validation error accumulation
- Built-in logging integration
"""

from __future__ import annotations

import logging
from enum import StrEnum

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    """Machine-readable error codes for API responses."""

    # General
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"

    # Auth
    UNAUTHENTICATED = "UNAUTHENTICATED"
    UNAUTHORIZED = "UNAUTHORIZED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    INSUFFICIENT_SCOPE = "INSUFFICIENT_SCOPE"

    # Resource
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    GONE = "GONE"

    # Rate limiting
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    # Agent-specific
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    AGENT_RUN_FAILED = "AGENT_RUN_FAILED"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"

    # Model / LLM
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    CONTEXT_LENGTH_EXCEEDED = "CONTEXT_LENGTH_EXCEEDED"
    CONTENT_FILTER = "CONTENT_FILTER"


# ============================================================================
# Base error
# ============================================================================


class AgentOSError(HTTPException):
    """Base exception for all AgentOS API errors.

    Extends FastAPI's HTTPException with structured error codes
    and optional field-level details.
    """

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        detail: str = "",
        field: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.field = field
        self._log()

    def _log(self):
        """Log the error at appropriate level."""
        log_msg = f"[{self.code.value}] {self.detail}"
        if self.field:
            log_msg += f" (field: {self.field})"
        if self.status_code >= 500:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    def to_api_error(self) -> dict:
        """Convert to APIErrorDetail-compatible dict."""
        return {
            "type": f"https://errors.agentos.dev/{self.code.value.lower()}",
            "title": self._title(),
            "status": self.status_code,
            "detail": self.detail,
            "code": self.code.value,
            "field": self.field,
        }

    def _title(self) -> str:
        titles = {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            409: "Conflict",
            429: "Too Many Requests",
            500: "Internal Server Error",
            503: "Service Unavailable",
        }
        return titles.get(self.status_code, "Error")


# ============================================================================
# Concrete error types
# ============================================================================


class ValidationError(AgentOSError):
    """422 — Input validation failed.

    Supports accumulating multiple field errors via add_error().
    """

    def __init__(
        self,
        detail: str = "Validation failed",
        field: str | None = None,
        errors: list[dict[str, str]] | None = None,
    ):
        super().__init__(
            status_code=422,
            code=ErrorCode.VALIDATION_ERROR,
            detail=detail,
            field=field,
        )
        self.errors: list[dict[str, str]] = errors or []
        if field and detail:
            self.errors.append({"field": field, "message": detail})

    def add_error(self, field: str, message: str) -> None:
        """Accumulate an additional field error."""
        self.errors.append({"field": field, "message": message})
        if not self.detail:
            self.detail = f"Validation error on '{field}': {message}"

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def to_dict(self) -> dict:
        return {
            **self.to_api_error(),
            "errors": self.errors,
        }


class NotFoundError(AgentOSError):
    """404 — Resource not found."""

    def __init__(self, resource_type: str = "Resource", identifier: str = ""):
        detail = f"{resource_type} not found"
        if identifier:
            detail = f"{resource_type} '{identifier}' not found"
        super().__init__(
            status_code=404,
            code=ErrorCode.NOT_FOUND,
            detail=detail,
        )


class AuthenticationError(AgentOSError):
    """401 — Missing or invalid credentials."""

    def __init__(self, detail: str = "Authentication required"):
        super().__init__(
            status_code=401,
            code=ErrorCode.UNAUTHENTICATED,
            detail=detail,
        )


class AuthorizationError(AgentOSError):
    """403 — Insufficient permissions."""

    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(
            status_code=403,
            code=ErrorCode.UNAUTHORIZED,
            detail=detail,
        )


class RateLimitError(AgentOSError):
    """429 — Too many requests.

    Includes retry-after header when available.
    """

    def __init__(
        self,
        detail: str = "Rate limit exceeded",
        retry_after: int | None = None,
    ):
        headers = {}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        super().__init__(
            status_code=429,
            code=ErrorCode.RATE_LIMITED,
            detail=detail,
            headers=headers,
        )
        self.retry_after = retry_after


class InternalError(AgentOSError):
    """500 — Unexpected internal error. User-safe, no stack traces exposed."""

    def __init__(self, detail: str = "An unexpected error occurred"):
        super().__init__(
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR,
            detail=detail,
        )


class ServiceUnavailableError(AgentOSError):
    """503 — Service temporarily unavailable (e.g., during maintenance)."""

    def __init__(
        self,
        detail: str = "Service temporarily unavailable",
        retry_after: int | None = None,
    ):
        headers = {}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        super().__init__(
            status_code=503,
            code=ErrorCode.SERVICE_UNAVAILABLE,
            detail=detail,
            headers=headers,
        )
