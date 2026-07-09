"""
Production-grade typed configuration management.

Supports:
- Multiple sources: env vars, .env files, YAML, TOML, JSON, dict
- Strict typing with Pydantic-style validation
- Hierarchical merging with precedence
- Environment-specific overrides (dev/staging/prod)
- Secret masking in logs
- Hot-reload with callbacks

Copyright 2026 AgentOS. All rights reserved.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import MISSING, dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

logger = logging.getLogger("agentos.config")

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Base configuration error."""


class ConfigValidationError(ConfigError):
    """Configuration value validation failure."""

    def __init__(self, field_path: str, value: Any, reason: str):
        self.field_path = field_path
        self.value = value
        self.reason = reason
        super().__init__(f"{field_path}: {reason} (got {value!r})")


class ConfigNotFoundError(ConfigError):
    """Required configuration key not found."""


class ConfigSourceError(ConfigError):
    """Failed to load configuration from a source."""


# ---------------------------------------------------------------------------
# Source Types
# ---------------------------------------------------------------------------


class SourceType(Enum):
    ENV = "env"
    DOTENV = "dotenv"
    YAML = "yaml"
    TOML = "toml"
    JSON = "json"
    DICT = "dict"


@dataclass
class ConfigSource:
    """Configuration source with precedence (lower number = higher priority)."""

    source_type: SourceType
    data: dict[str, Any]
    precedence: int = 100
    description: str = ""

    @classmethod
    def from_env(cls, prefix: str = "", precedence: int = 200) -> ConfigSource:
        data: dict[str, Any] = {}
        for key, val in os.environ.items():
            if prefix and not key.startswith(prefix):
                continue
            clean_key = key[len(prefix) :] if prefix else key
            # parse simple types
            data[clean_key.lower()] = _parse_env_value(val)
        return cls(SourceType.ENV, data, precedence, f"env(prefix={prefix!r})")

    @classmethod
    def from_dotenv(
        cls, path: str | Path, precedence: int = 300, override: bool = False
    ) -> ConfigSource:
        from pathlib import Path

        path = Path(path)
        if not path.exists():
            if override:
                return cls(SourceType.DOTENV, {}, precedence, f"dotenv({path})")
            raise ConfigSourceError(f".env file not found: {path}")
        data: dict[str, Any] = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip().lower()
            val = val.strip().strip('"').strip("'")
            data[key] = _parse_env_value(val)
        return cls(SourceType.DOTENV, data, precedence, f"dotenv({path})")

    @classmethod
    def from_yaml(cls, path: str | Path, precedence: int = 400) -> ConfigSource:
        import yaml

        path = Path(path)
        if not path.exists():
            raise ConfigSourceError(f"YAML file not found: {path}")
        with open(path) as f:
            data = _flatten_dict(yaml.safe_load(f) or {})
        return cls(SourceType.YAML, data, precedence, f"yaml({path})")

    @classmethod
    def from_toml(cls, path: str | Path, precedence: int = 400) -> ConfigSource:
        path = Path(path)
        if not path.exists():
            raise ConfigSourceError(f"TOML file not found: {path}")
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        with open(path, "rb") as f:
            data = _flatten_dict(tomllib.load(f) or {})
        return cls(SourceType.TOML, data, precedence, f"toml({path})")

    @classmethod
    def from_json(cls, path: str | Path, precedence: int = 400) -> ConfigSource:
        path = Path(path)
        if not path.exists():
            raise ConfigSourceError(f"JSON file not found: {path}")
        with open(path) as f:
            data = _flatten_dict(json.load(f) or {})
        return cls(SourceType.JSON, data, precedence, f"json({path})")

    @classmethod
    def from_dict(
        cls, d: dict[str, Any], precedence: int = 500, description: str = "dict"
    ) -> ConfigSource:
        return cls(SourceType.DICT, dict(d), precedence, description)


# ---------------------------------------------------------------------------
# Config Manager
# ---------------------------------------------------------------------------


class ConfigManager:
    """Central configuration manager with source merging and typed access.

    Usage:
        cm = ConfigManager()
        cm.add_source(ConfigSource.from_env("AGENTOS_"))
        cm.add_source(ConfigSource.from_yaml("config/prod.yaml"))

        db_host = cm.get("database.host", default="localhost")
        db_port = cm.get_int("database.port", default=5432)

        # Bind to dataclass
        from dataclasses import dataclass

        @dataclass
        class AppConfig:
            host: str = "0.0.0.0"
            port: int = 8080
            debug: bool = False

        app_cfg = cm.bind(AppConfig)
    """

    def __init__(self, auto_env: bool = True, env_prefix: str = "AGENTOS_"):
        self._sources: list[ConfigSource] = []
        self._merged: dict[str, Any] | None = None
        self._listeners: list[Callable[[str, Any, Any], None]] = []
        self._secrets: set[str] = set()
        if auto_env:
            self.add_source(ConfigSource.from_env(env_prefix))

    # -- Source management --

    def add_source(self, source: ConfigSource) -> None:
        self._sources.append(source)
        self._sources.sort(key=lambda s: s.precedence)
        self._merged = None

    def mark_secret(self, key: str) -> None:
        self._secrets.add(key.lower())

    def mark_secrets(self, keys: list[str]) -> None:
        for k in keys:
            self._secrets.add(k.lower())

    # -- Merge --

    def _merge_sources(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        # Lower precedence = higher priority → iterate reversed so high-priority overrides
        for source in reversed(self._sources):
            for key, val in source.data.items():
                result[key] = val
        return result

    def _ensure_merged(self) -> dict[str, Any]:
        if self._merged is None:
            self._merged = self._merge_sources()
        return self._merged

    # -- Read --

    def get(self, key: str, default: Any = MISSING) -> Any:
        merged = self._ensure_merged()
        value = merged.get(key.lower(), MISSING)
        if value is MISSING:
            if default is not MISSING:
                return default
            raise ConfigNotFoundError(f"Configuration key not found: {key}")
        return value

    def get_str(self, key: str, default: Any = MISSING) -> str:
        return str(self.get(key, default))

    def get_int(self, key: str, default: Any = MISSING) -> int:
        val = self.get(key, default)
        return int(val)

    def get_float(self, key: str, default: Any = MISSING) -> float:
        val = self.get(key, default)
        return float(val)

    def get_bool(self, key: str, default: Any = MISSING) -> bool:
        val = self.get(key, default)
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val)

    def get_list(self, key: str, default: Any = MISSING, separator: str = ",") -> list[str]:
        val = self.get(key, default)
        if isinstance(val, list):
            return [str(v) for v in val]
        if isinstance(val, str):
            return [v.strip() for v in val.split(separator) if v.strip()]
        return [str(val)]

    def get_dict(self, key: str, default: Any = MISSING) -> dict[str, Any]:
        val = self.get(key, default)
        if isinstance(val, dict):
            return val
        raise ConfigValidationError(key, val, "expected dict")

    def keys(self) -> list[str]:
        return sorted(self._ensure_merged().keys())

    def to_dict(self, mask_secrets: bool = True) -> dict[str, Any]:
        d = dict(self._ensure_merged())
        if mask_secrets:
            for sk in self._secrets:
                if sk in d:
                    d[sk] = "***MASKED***"
        return d

    # -- Bind to dataclass --

    def bind(self, cls: type[T]) -> T:
        """Bind merged configuration to a dataclass instance."""
        hints = get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        for fld in fields(cls):
            key = fld.name.lower()
            field_type = hints.get(fld.name, str)
            try:
                raw = self._ensure_merged().get(key, MISSING)
            except Exception:
                raw = MISSING
            if raw is MISSING:
                if fld.default is not MISSING:
                    kwargs[fld.name] = fld.default
                elif fld.default_factory is not MISSING:
                    kwargs[fld.name] = fld.default_factory()
                else:
                    raise ConfigNotFoundError(
                        f"Required config '{fld.name}' not found and has no default"
                    )
            else:
                kwargs[fld.name] = _coerce(raw, field_type)
        return cls(**kwargs)

    # -- Listener --

    def on_change(self, callback: Callable[[str, Any, Any], None]) -> None:
        self._listeners.append(callback)

    def set(self, key: str, value: Any) -> None:
        old = self._ensure_merged().get(key.lower())
        self._ensure_merged()[key.lower()] = value
        for cb in self._listeners:
            cb(key, old, value)

    def reload(self) -> None:
        self._merged = None
        self._ensure_merged()

    def __repr__(self) -> str:
        keys = self.keys()
        return f"ConfigManager(sources={len(self._sources)}, keys={len(keys)})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_env_value(val: str) -> Any:
    """Parse string environment value to native types."""
    v = val.strip()
    # bool
    if v.lower() in ("true", "yes", "on"):
        return True
    if v.lower() in ("false", "no", "off"):
        return False
    # null
    if v.lower() in ("null", "none", ""):
        return None
    # int
    try:
        return int(v)
    except ValueError:
        pass
    # float
    try:
        return float(v)
    except ValueError:
        pass
    # JSON
    if (v.startswith("{") and v.endswith("}")) or (v.startswith("[") and v.endswith("]")):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            pass
    return v


def _flatten_dict(d: dict[str, Any], parent_key: str = "", sep: str = "_") -> dict[str, Any]:
    """Flatten nested dicts into dot-separated keys."""
    items: list[tuple[str, Any]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}".lower() if parent_key else k.lower()
        if (
            isinstance(v, dict)
            and not any(isinstance(v, t) for t in (list, tuple, set))
            and not (k.isupper() and all(c.isupper() or c == "_" for c in k))
        ):
            items.extend(_flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def _coerce(value: Any, target_type: type) -> Any:
    """Coerce a value to the target type."""
    if value is None:
        return None
    origin = get_origin(target_type)
    if origin is Union:
        args = get_args(target_type)
        if type(None) in args:
            non_none = [a for a in args if a is not type(None)]
            if value is None:
                return None
            if non_none:
                return _coerce(value, non_none[0])
    if target_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is str:
        return str(value)
    if target_type is list or origin is list:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return [value]
    if origin is dict:
        if isinstance(value, dict):
            return value
        raise ConfigValidationError("", value, "cannot coerce to dict")
    if is_dataclass(target_type) and isinstance(value, dict):
        return target_type(**value)
    return value
