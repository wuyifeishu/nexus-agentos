"""AgentOS API middleware — request/response processing pipeline.

Provides authentication, CORS, request tracing, request-ID injection,
and rate-limiting middleware for the AgentOS API server.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional


# ── Request ID ────────────────────────────────────────────────────────────────


@dataclass
class RequestContext:
    """请求上下文。"""
    request_id: str = ""
    start_time: float = 0.0
    method: str = ""
    path: str = ""
    client_ip: str = ""
    user_agent: str = ""

    @property
    def elapsed_ms(self) -> float:
        return (time.monotonic() - self.start_time) * 1000


class RequestIDMiddleware:
    """Inject X-Request-ID into every request and propagate it."""

    def __init__(self, header: str = "X-Request-ID"):
        self.header = header

    def process_request(self, headers: dict) -> RequestContext:
        rid = headers.get(self.header.lower(), headers.get(self.header, ""))
        if not rid:
            rid = str(uuid.uuid4())[:12]
        return RequestContext(request_id=rid, start_time=time.monotonic())


# ── CORS ──────────────────────────────────────────────────────────────────────


@dataclass
class CORSConfig:
    """CORS 配置。"""
    allow_origins: list[str] = field(default_factory=lambda: ["*"])
    allow_methods: list[str] = field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    allow_headers: list[str] = field(default_factory=lambda: ["Content-Type", "Authorization", "X-Request-ID"])
    expose_headers: list[str] = field(default_factory=list)
    max_age: int = 86400
    allow_credentials: bool = False


class CORSMiddleware:
    """Add CORS headers to every response."""

    def __init__(self, config: Optional[CORSConfig] = None):
        self.config = config or CORSConfig()

    def apply(self, response_headers: dict) -> dict:
        origin = self.config.allow_origins[0] if self.config.allow_origins else ""
        response_headers["Access-Control-Allow-Origin"] = origin
        response_headers["Access-Control-Allow-Methods"] = ", ".join(self.config.allow_methods)
        response_headers["Access-Control-Allow-Headers"] = ", ".join(self.config.allow_headers)
        if self.config.expose_headers:
            response_headers["Access-Control-Expose-Headers"] = ", ".join(self.config.expose_headers)
        response_headers["Access-Control-Max-Age"] = str(self.config.max_age)
        if self.config.allow_credentials:
            response_headers["Access-Control-Allow-Credentials"] = "true"
        return response_headers


# ── Auth ──────────────────────────────────────────────────────────────────────


@dataclass
class AuthConfig:
    """认证配置。"""
    api_key_header: str = "X-API-Key"
    api_key: str = ""
    enabled: bool = True


class AuthMiddleware:
    """Simple API-key authentication middleware."""

    def __init__(self, config: Optional[AuthConfig] = None):
        self.config = config or AuthConfig()

    def authenticate(self, headers: dict) -> tuple[bool, str]:
        """Return (authorized, message)."""
        if not self.config.enabled or not self.config.api_key:
            return True, ""
        provided = headers.get(self.config.api_key_header.lower(), headers.get(self.config.api_key_header, ""))
        if provided != self.config.api_key:
            return False, "Invalid or missing API key"
        return True, ""


# ── Request logger ────────────────────────────────────────────────────────────


class RequestLogMiddleware:
    """Log every request with method, path, status, and elapsed time."""

    def __init__(self, logger: Optional[Callable[[str], None]] = None):
        self._log = logger or print

    def log(self, ctx: RequestContext, status: int) -> str:
        msg = (
            f"[{ctx.request_id}] {ctx.method} {ctx.path} "
            f"→ {status} ({ctx.elapsed_ms:.1f}ms)"
        )
        self._log(msg)
        return msg


# ── Middleware stack ──────────────────────────────────────────────────────────


class MiddlewareStack:
    """Ordered middleware pipeline for the AgentOS API."""

    def __init__(
        self,
        cors: Optional[CORSMiddleware] = None,
        auth: Optional[AuthMiddleware] = None,
        req_log: Optional[RequestLogMiddleware] = None,
        req_id: Optional[RequestIDMiddleware] = None,
    ):
        self.cors = cors or CORSMiddleware()
        self.auth = auth or AuthMiddleware()
        self.req_log = req_log or RequestLogMiddleware()
        self.req_id = req_id or RequestIDMiddleware()
