"""
AgentOS API Versioning — Semantic Versioning Middleware & Router
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Production-grade API versioning with:
  - URL path versioning (default): /v1/resource, /v2/resource
  - Header-based versioning: Accept: application/json; version=1
  - Query parameter versioning: /resource?api_version=1
  - Semantic version negotiation (closest match)
  - Deprecation notices with sunset dates
  - Automatic OpenAPI versioned docs

Architecture:
  VersioningMiddleware  → extract version from request
  VersionedRouter       → route to correct version handler
  DeprecationPolicy     → warn/block deprecated versions
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# ---------------------------------------------------------------------------
# Semantic Version
# ---------------------------------------------------------------------------


@dataclass(order=True, frozen=True)
class SemVer:
    """Semantic version (major.minor.patch)."""

    major: int
    minor: int = 0
    patch: int = 0

    _PARSE_RE = re.compile(r"^v?(\d+)(?:\.(\d+)(?:\.(\d+))?)?")

    @classmethod
    def parse(cls, version_str: str) -> SemVer | None:
        """Parse a version string like 'v1', '2.0', '1.2.3'."""
        m = cls._PARSE_RE.match(version_str.strip())
        if not m:
            return None
        return cls(
            major=int(m.group(1)),
            minor=int(m.group(2) or 0),
            patch=int(m.group(3) or 0),
        )

    def is_compatible(self, other: SemVer) -> bool:
        """Check if other version is API-compatible (same major)."""
        return self.major == other.major

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}"


# ---------------------------------------------------------------------------
# Version Extraction Strategy
# ---------------------------------------------------------------------------


class VersionStrategy(StrEnum):
    """How to extract API version from requests."""

    URL_PATH = "url_path"  # /v1/resource
    HEADER = "header"  # Accept: application/json; version=1
    QUERY_PARAM = "query_param"  # /resource?api_version=1


class VersionExtractor:
    """Extract API version from incoming requests."""

    STRATEGIES: list[VersionStrategy] = [
        VersionStrategy.URL_PATH,
        VersionStrategy.HEADER,
        VersionStrategy.QUERY_PARAM,
    ]

    def __init__(self, strategies: list[VersionStrategy] | None = None):
        self._strategies = strategies or self.STRATEGIES

    def extract(self, request: Request) -> SemVer | None:
        """Try each strategy in order; return first match."""
        for strategy in self._strategies:
            version = self._try_strategy(request, strategy)
            if version is not None:
                return version
        return None

    def _try_strategy(self, request: Request, strategy: VersionStrategy) -> SemVer | None:
        if strategy == VersionStrategy.URL_PATH:
            return self._from_url(request)
        elif strategy == VersionStrategy.HEADER:
            return self._from_header(request)
        elif strategy == VersionStrategy.QUERY_PARAM:
            return self._from_query(request)
        return None

    @staticmethod
    def _from_url(request: Request) -> SemVer | None:
        """Extract from /v{major}/... or /v{major}.{minor}/..."""
        path = request.url.path.lstrip("/")
        parts = path.split("/")
        for i, part in enumerate(parts):
            if part.lower().startswith("v") and part[1:].replace(".", "").isdigit():
                return SemVer.parse(part)
        return None

    @staticmethod
    def _from_header(request: Request) -> SemVer | None:
        """Extract from Accept header or custom X-API-Version."""
        custom = request.headers.get("X-API-Version")
        if custom:
            return SemVer.parse(custom)

        accept = request.headers.get("Accept", "")
        version_match = re.search(r"version=(\d+(?:\.\d+)*)", accept)
        if version_match:
            return SemVer.parse(version_match.group(1))
        return None

    @staticmethod
    def _from_query(request: Request) -> SemVer | None:
        """Extract from ?api_version=1 or ?v=2.0."""
        for param in ("api_version", "v", "version"):
            value = request.query_params.get(param)
            if value:
                return SemVer.parse(value)
        return None


# ---------------------------------------------------------------------------
# Deprecation Policy
# ---------------------------------------------------------------------------


@dataclass
class DeprecationInfo:
    """Information about a deprecated API version."""

    version: SemVer
    sunset_date: datetime | None = None
    migration_guide_url: str | None = None
    message: str = "This API version is deprecated."

    @property
    def is_sunset(self) -> bool:
        if self.sunset_date is None:
            return False
        return datetime.now(UTC) > self.sunset_date


class DeprecationPolicy:
    """Manage API version deprecation."""

    def __init__(self):
        self._deprecated: dict[SemVer, DeprecationInfo] = {}

    def deprecate(self, version: str, sunset_days: int = 90, **kwargs) -> None:
        """Mark a version as deprecated."""
        semver = SemVer.parse(version)
        if semver is None:
            raise ValueError(f"Invalid version: {version}")
        sunset = datetime.now(UTC) + timedelta(days=sunset_days)
        self._deprecated[semver] = DeprecationInfo(
            version=semver,
            sunset_date=sunset,
            **kwargs,
        )

    def is_deprecated(self, version: SemVer) -> bool:
        return version in self._deprecated

    def get_info(self, version: SemVer) -> DeprecationInfo | None:
        return self._deprecated.get(version)

    def should_block(self, version: SemVer) -> bool:
        info = self._deprecated.get(version)
        return info is not None and info.is_sunset

    def list_deprecated(self) -> dict[str, dict[str, Any]]:
        return {
            str(v): {
                "sunset_date": d.sunset_date.isoformat() if d.sunset_date else None,
                "is_sunset": d.is_sunset,
                "migration_guide": d.migration_guide_url,
            }
            for v, d in self._deprecated.items()
        }


# ---------------------------------------------------------------------------
# Versioned Router
# ---------------------------------------------------------------------------


class VersionedRouter:
    """
    Route requests to version-specific handlers.

    Supports semantic version negotiation:
      - Exact match: /v1.0.0 → v1.0.0 handler
      - Minor fallback: /v1.2.x → v1.2.0 handler
      - Major fallback: /v1.x.x → latest v1 handler
    """

    def __init__(self):
        self._handlers: dict[SemVer, Callable] = {}
        self._default_version: SemVer | None = None

    def register(self, version: str, handler: Callable) -> None:
        """Register a handler for a specific version."""
        semver = SemVer.parse(version)
        if semver is None:
            raise ValueError(f"Invalid version: {version}")
        self._handlers[semver] = handler

    def set_default(self, version: str) -> None:
        """Set the default version when no version is specified."""
        self._default_version = SemVer.parse(version)

    def resolve(self, requested: SemVer) -> tuple[Callable | None, SemVer | None]:
        """
        Resolve a version to its handler.
        Returns (handler, actual_version) or (None, None).
        """
        # Exact match
        if requested in self._handlers:
            return self._handlers[requested], requested

        # Minor fallback: within same major, find closest <= requested
        candidates = [v for v in self._handlers if v.major == requested.major and v <= requested]
        if candidates:
            best = max(candidates)  # highest compatible version
            return self._handlers[best], best

        # No match → default or None
        if self._default_version:
            default = self._default_version
            return self._handlers.get(default), default

        return None, None

    def list_versions(self) -> list[str]:
        return sorted(str(v) for v in self._handlers.keys())


# ---------------------------------------------------------------------------
# Starlette Middleware
# ---------------------------------------------------------------------------


class APIVersioningMiddleware:
    """
    Starlette-compatible API versioning middleware.

    Usage:
        app = Starlette()
        app.add_middleware(
            APIVersioningMiddleware,
            supported_versions=["v1", "v2"],
            default_version="v1",
        )
    """

    def __init__(
        self,
        app,
        supported_versions: list[str] | None = None,
        default_version: str | None = None,
        deprecation_policy: DeprecationPolicy | None = None,
        strategies: list[VersionStrategy] | None = None,
    ):
        self.app = app
        self._supported = {SemVer.parse(v) for v in (supported_versions or []) if SemVer.parse(v)}
        self._default = SemVer.parse(default_version) if default_version else None
        self._deprecation = deprecation_policy or DeprecationPolicy()
        self._extractor = VersionExtractor(strategies)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        version = self._extractor.extract(request) or self._default

        # No version → pass through
        if version is None:
            await self.app(scope, receive, send)
            return

        # Check if version is supported
        if self._supported and version not in self._supported:
            response = self._version_error_response(version, "unsupported")
            await response(scope, receive, send)
            return

        # Check deprecation → add warning header
        if self._deprecation.should_block(version):
            response = self._version_error_response(version, "sunset")
            await response(scope, receive, send)
            return

        # Add version to request state
        request.state.api_version = version
        request.state.api_version_str = str(version)

        # Add deprecation warning header
        if self._deprecation.is_deprecated(version):
            info = self._deprecation.get_info(version)
            if info:
                response = await self._with_deprecation_warning(scope, receive, send, info)
                return

        await self.app(scope, receive, send)

    async def _with_deprecation_warning(self, scope, receive, send, info: DeprecationInfo) -> None:
        """Wrap response with deprecation headers."""

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"deprecation"] = b"true"
                headers[b"sunset"] = (
                    info.sunset_date.isoformat().encode() if info.sunset_date else b"unknown"
                )
                if info.migration_guide_url:
                    headers[b"link"] = f'<{info.migration_guide_url}>; rel="deprecation"'.encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _version_error_response(version: SemVer, reason: str) -> Response:
        if reason == "unsupported":
            detail = f"API version {version} is not supported."
            status_code = 400
        else:
            detail = f"API version {version} has been sunset."
            status_code = 410

        return JSONResponse(
            {"error": reason, "detail": detail, "version": str(version)},
            status_code=status_code,
        )


# ---------------------------------------------------------------------------
# Backward Compatibility Aliases
# ---------------------------------------------------------------------------

# Old API → New API mapping
APIVersion = SemVer  # SemVer replaces APIVersion
VersionConfig = DeprecationPolicy  # DeprecationPolicy replaces VersionConfig
VersionNegotiator = VersionedRouter  # VersionedRouter replaces VersionNegotiator
