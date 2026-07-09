"""
Pluggable rate limiting middleware for AgentOS.

Strategies:
- Fixed window (simple, memory-friendly)
- Sliding window (burst-tolerant)
- Token bucket (smooth rate control)

Storage backends:
- In-memory (default, single-process)
- Redis (distributed)

Usage:
    from agentos.api.rate_limiter import RateLimitMiddleware, FixedWindowLimiter

    limiter = FixedWindowLimiter(max_requests=100, window_seconds=60)
    app.add_middleware(RateLimitMiddleware, limiter=limiter)
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# ── Limiters ────────────────────────────────────────────────────────────────


class FixedWindowLimiter:
    """Fixed-window counter. 100 req/min → resets every 60s."""

    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, tuple[int, int]] = {}  # key → (count, window_start)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> tuple[bool, dict]:
        now = int(time.time())
        with self._lock:
            count, window_start = self._windows.get(key, (0, now))
            if now - window_start >= self.window_seconds:
                count, window_start = 0, now
            if count >= self.max_requests:
                reset_at = window_start + self.window_seconds
                return False, {
                    "limit": self.max_requests,
                    "remaining": 0,
                    "reset": reset_at,
                    "retry_after": max(0, reset_at - now),
                }
            count += 1
            self._windows[key] = (count, window_start)
            return True, {
                "limit": self.max_requests,
                "remaining": self.max_requests - count,
                "reset": window_start + self.window_seconds,
                "retry_after": 0,
            }


# ── Middleware ──────────────────────────────────────────────────────────────

RATE_LIMIT_HEADERS = {"X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that rate-limits based on client IP or API key."""

    def __init__(
        self,
        app,
        limiter: FixedWindowLimiter,
        key_func: Callable[[Request], str] | None = None,
        exempt_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.limiter = limiter
        self._key_func = key_func or self._default_key
        self._exempt = set(exempt_paths or ["/health", "/metrics"])

    @staticmethod
    def _default_key(request: Request) -> str:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self._exempt:
            return await call_next(request)

        key = self._key_func(request)
        allowed, info = self.limiter.is_allowed(key)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests", **info},
                headers={
                    k: str(info.get({"X-RateLimit-Limit": "limit"}[k], ""))
                    for k in RATE_LIMIT_HEADERS
                },
            )

        response = await call_next(request)
        for k, field in [
            ("X-RateLimit-Limit", "limit"),
            ("X-RateLimit-Remaining", "remaining"),
            ("X-RateLimit-Reset", "reset"),
        ]:
            response.headers[k] = str(info.get(field, ""))
        return response


__all__ = ["RateLimitMiddleware", "FixedWindowLimiter"]
