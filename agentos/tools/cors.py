"""
CORS — Cross-Origin Resource Sharing middleware helper.

Supports:
    - Fluent builder for CORS configuration
    - Origin validation (allowlist/regex)
    - Method (GET/POST/PUT/DELETE/etc.) and header control
    - Preflight (OPTIONS) response builder
    - Max-Age, Credentials, Expose-Headers
    - Serialize to dict of response headers
"""

from __future__ import annotations

import re
from re import Pattern

# ============================================================================
# CORS
# ============================================================================

SAFELISTED_METHODS = frozenset({"GET", "HEAD", "POST"})
SAFELISTED_HEADERS = frozenset(
    {
        "accept",
        "accept-language",
        "content-language",
        "content-type",
    }
)


class CORSConfig:
    """CORS configuration builder.

    Usage:
        cors = (CORSConfig()
            .allow_origins("https://example.com", "https://app.example.com")
            .allow_methods("GET", "POST", "PUT")
            .allow_headers("Content-Type", "Authorization")
            .allow_credentials()
            .max_age(3600)
        )

        # Check if origin is allowed
        ok = cors.is_origin_allowed("https://example.com")

        # Build preflight response headers
        headers = cors.preflight_headers("https://example.com")
    """

    def __init__(self):
        self._origins: list[str] = []
        self._origin_patterns: list[Pattern] = []
        self._allow_any_origin: bool = False
        self._methods: set[str] = set()
        self._headers: set[str] = set()
        self._expose_headers: set[str] = set()
        self._allow_credentials: bool = False
        self._max_age: int | None = None

    # ---------- Fluent setters ----------

    def allow_origins(self, *origins: str) -> CORSConfig:
        for origin in origins:
            if origin == "*":
                self._allow_any_origin = True
            elif "*" in origin and origin != "*":
                # Convert glob to regex
                pattern = re.escape(origin).replace(r"\*", ".*")
                self._origin_patterns.append(re.compile(f"^{pattern}$"))
            else:
                self._origins.append(origin.rstrip("/"))
        return self

    def allow_methods(self, *methods: str) -> CORSConfig:
        self._methods.update(m.upper() for m in methods)
        return self

    def allow_headers(self, *headers: str) -> CORSConfig:
        self._headers.update(h.lower() for h in headers)
        return self

    def expose_headers(self, *headers: str) -> CORSConfig:
        self._expose_headers.update(h.lower() for h in headers)
        return self

    def allow_credentials(self) -> CORSConfig:
        self._allow_credentials = True
        return self

    def max_age(self, seconds: int) -> CORSConfig:
        self._max_age = seconds
        return self

    # ---------- Convenience ----------

    def allow_all_origins(self) -> CORSConfig:
        self._allow_any_origin = True
        return self

    def allow_all_methods(self) -> CORSConfig:
        self._methods = {"GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"}
        return self

    def allow_all_headers(self) -> CORSConfig:
        self._headers = {"*"}
        return self

    # ---------- Logic ----------

    def is_origin_allowed(self, origin: str) -> bool:
        if self._allow_any_origin:
            return True
        origin = origin.rstrip("/")
        if origin in self._origins:
            return True
        for pattern in self._origin_patterns:
            if pattern.match(origin):
                return True
        return False

    def preflight_headers(
        self,
        origin: str,
        request_method: str | None = None,
        request_headers: list[str] | None = None,
    ) -> dict[str, str]:
        """Build response headers for a preflight OPTIONS request."""
        headers: dict = {}

        if not self.is_origin_allowed(origin):
            return headers

        if self._allow_any_origin and not self._allow_credentials:
            headers["Access-Control-Allow-Origin"] = "*"
        else:
            headers["Access-Control-Allow-Origin"] = origin

        if self._allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"

        # Methods — return all allowed methods (preflight spec)
        if self._methods:
            headers["Access-Control-Allow-Methods"] = ", ".join(sorted(self._methods))
        elif request_method:
            headers["Access-Control-Allow-Methods"] = request_method.upper()

        # Headers
        if request_headers:
            allowed = set(h.lower() for h in request_headers)
            if self._headers and "*" not in self._headers:
                allowed &= self._headers
            if allowed:
                headers["Access-Control-Allow-Headers"] = ", ".join(sorted(allowed))
        elif self._headers:
            headers["Access-Control-Allow-Headers"] = ", ".join(sorted(self._headers))

        # Expose
        if self._expose_headers:
            headers["Access-Control-Expose-Headers"] = ", ".join(sorted(self._expose_headers))

        # Max-Age
        if self._max_age is not None:
            headers["Access-Control-Max-Age"] = str(self._max_age)

        return headers

    def actual_headers(self, origin: str) -> dict[str, str]:
        """Build response headers for the actual (non-preflight) request."""
        headers: dict = {}

        if not self.is_origin_allowed(origin):
            return headers

        if self._allow_any_origin and not self._allow_credentials:
            headers["Access-Control-Allow-Origin"] = "*"
        else:
            headers["Access-Control-Allow-Origin"] = origin

        if self._allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"

        if self._expose_headers:
            headers["Access-Control-Expose-Headers"] = ", ".join(sorted(self._expose_headers))

        return headers

    def is_preflight(self, method: str, headers: list[str] | None = None) -> bool:
        """Check if a request is a CORS preflight request."""
        if method.upper() != "OPTIONS":
            return False
        # Preflight requires Origin header + either non-safelisted method or custom header
        # (Origin header presence is assumed by the caller)
        return True
