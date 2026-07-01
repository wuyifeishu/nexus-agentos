"""AgentOS API version negotiation.

Supports header-based and URL-path-based versioning for the AgentOS REST API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VersionStrategy(Enum):

    """版本策略枚举。"""

    HEADER = "header"        # Accept: application/json; version=1
    PATH = "path"            # /api/v1/...
    QUERY = "query"          # /api/endpoint?version=1


@dataclass
class APIVersion:
    """API 版本记录。"""
    major: int
    minor: int = 0

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}"

    @classmethod
    def parse(cls, raw: str) -> APIVersion:
        raw = raw.strip().lstrip("vV")
        parts = [int(p) for p in raw.split(".")]
        return cls(major=parts[0], minor=parts[1] if len(parts) > 1 else 0)

    def __lt__(self, other: APIVersion) -> bool:
        return (self.major, self.minor) < (other.major, other.minor)

    def __le__(self, other: APIVersion) -> bool:
        return (self.major, self.minor) <= (other.major, other.minor)


@dataclass
class VersionConfig:
    """版本管理配置。"""
    current: APIVersion = field(default_factory=lambda: APIVersion(1, 0))
    min_supported: APIVersion = field(default_factory=lambda: APIVersion(1, 0))
    deprecated: list[APIVersion] = field(default_factory=list)   # versions that emit deprecation warnings
    strategy: VersionStrategy = VersionStrategy.HEADER
    header_name: str = "Accept"


class VersionNegotiator:
    """Negotiate and validate API version from incoming requests."""

    def __init__(self, config: Optional[VersionConfig] = None):
        self.config = config or VersionConfig()

    def extract_from_headers(self, headers: dict) -> Optional[APIVersion]:
        """Extract version from Accept header (e.g. 'application/json; version=1')."""
        accept = headers.get(self.config.header_name.lower(), headers.get(self.config.header_name, ""))
        for part in accept.split(";"):
            part = part.strip()
            if part.startswith("version="):
                try:
                    return APIVersion.parse(part.split("=", 1)[1])
                except (ValueError, IndexError):
                    return None
        return None

    def extract_from_path(self, path: str) -> Optional[APIVersion]:
        """Extract version from URL path (e.g. '/api/v2/endpoint')."""
        import re
        m = re.match(r"^/api/v(\d+(?:\.\d+)?)/", path)
        if m:
            try:
                return APIVersion.parse(m.group(1))
            except ValueError:
                return None
        return None

    def extract_from_query(self, query: str) -> Optional[APIVersion]:
        """Extract version from query string (e.g. 'version=2')."""
        import urllib.parse
        params = urllib.parse.parse_qs(query)
        versions = params.get("version", [])
        if versions:
            try:
                return APIVersion.parse(versions[0])
            except ValueError:
                return None
        return None

    def negotiate(self, headers: dict, path: str = "", query: str = "") -> tuple[APIVersion, list[str]]:
        """Return (resolved_version, warnings)."""
        version: Optional[APIVersion] = None

        if self.config.strategy == VersionStrategy.HEADER:
            version = self.extract_from_headers(headers)
        elif self.config.strategy == VersionStrategy.PATH:
            version = self.extract_from_path(path)
        elif self.config.strategy == VersionStrategy.QUERY:
            version = self.extract_from_query(query)

        if version is None:
            version = self.config.current

        warnings: list[str] = []

        if version < self.config.min_supported:
            warnings.append(
                f"API {version} is no longer supported (min: {self.config.min_supported})"
            )

        if version in self.config.deprecated:
            warnings.append(f"API {version} is deprecated — upgrade to {self.config.current}")

        return version, warnings
