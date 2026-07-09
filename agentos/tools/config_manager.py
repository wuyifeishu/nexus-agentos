"""
ConfigManager — layered configuration with schema validation, env overlay, and hot reload.

Layers (priority low → high):
    1. defaults — hardcoded defaults
    2. file — YAML/JSON config file(s)
    3. env — environment variable overrides (PREFIX_KEY=value)
    4. runtime — programmatic overrides via set()

Supports: dot-path access, schema validation, file watching for hot reload.
"""

import json
import os
import threading
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

# ============================================================================
# Schema Validation
# ============================================================================


class ConfigSchemaError(Exception):
    """Validation error with path and message."""

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"[{path}] {message}")


class ConfigSchema:
    """Declarative schema for config validation."""

    def __init__(self):
        self._fields: dict[str, dict[str, Any]] = {}

    def field(
        self,
        name: str,
        type_: type = str,
        required: bool = False,
        default: Any = None,
        choices: list[Any] | None = None,
        min_val: float | None = None,
        max_val: float | None = None,
        description: str = "",
    ) -> "ConfigSchema":
        self._fields[name] = {
            "type": type_,
            "required": required,
            "default": default,
            "choices": choices,
            "min": min_val,
            "max": max_val,
            "description": description,
        }
        return self

    def validate(self, config: dict[str, Any], prefix: str = "") -> list[ConfigSchemaError]:
        errors = []
        for name, spec in self._fields.items():
            path = f"{prefix}.{name}" if prefix else name
            value = config.get(name)
            if value is None:
                if spec["required"]:
                    errors.append(ConfigSchemaError(path, "required field missing"))
                continue
            if not isinstance(value, spec["type"]):
                errors.append(
                    ConfigSchemaError(
                        path, f"expected {spec['type'].__name__}, got {type(value).__name__}"
                    )
                )
                continue
            if spec["choices"] and value not in spec["choices"]:
                errors.append(
                    ConfigSchemaError(path, f"invalid choice '{value}', allowed: {spec['choices']}")
                )
            if spec["min"] is not None and value < spec["min"]:
                errors.append(ConfigSchemaError(path, f"value {value} below min {spec['min']}"))
            if spec["max"] is not None and value > spec["max"]:
                errors.append(ConfigSchemaError(path, f"value {value} above max {spec['max']}"))
        return errors


# ============================================================================
# ConfigManager
# ============================================================================


class ConfigManager:
    """Layered configuration manager.

    Usage:
        cm = ConfigManager(defaults={"host": "localhost", "port": 8080})
        cm.load_file("config.yaml")
        cm.load_env("APP_")  # APP_HOST=0.0.0.0 overrides host
        cm.get("host")  # returns "0.0.0.0"
    """

    def __init__(
        self,
        defaults: dict[str, Any] | None = None,
        schema: ConfigSchema | None = None,
    ):
        self._defaults = deepcopy(defaults) if defaults else {}
        self._file_layer: dict[str, Any] = {}
        self._env_layer: dict[str, Any] = {}
        self._runtime_layer: dict[str, Any] = {}
        self._schema = schema
        self._lock = threading.RLock()
        self._watchers: dict[str, float] = {}  # path → mtime
        self._on_change: list[Callable[[str, Any, Any], None]] = []

    # ---------- file loading ----------

    def load_file(self, path: str | Path) -> None:
        """Load config from YAML or JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        content = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            data = self._parse_yaml(content)
        else:
            data = json.loads(content)
        with self._lock:
            self._file_layer = self._deep_merge(self._file_layer, data)
            if str(path) not in self._watchers:
                self._watchers[str(path)] = path.stat().st_mtime

    def _parse_yaml(self, content: str) -> dict[str, Any]:
        try:
            import yaml

            return yaml.safe_load(content) or {}
        except ImportError:
            raise ImportError("PyYAML required for YAML config files. pip install pyyaml")

    # ---------- env loading ----------

    def load_env(self, prefix: str = "") -> None:
        """Overlay environment variables. PREFIX_KEY → config key (lowercase)."""
        with self._lock:
            for key, value in os.environ.items():
                if not prefix or key.startswith(prefix):
                    config_key = key[len(prefix) :].lower() if prefix else key.lower()
                    # Try to parse numbers/booleans
                    parsed = self._parse_value(value)
                    self._env_layer[config_key] = parsed

    @staticmethod
    def _parse_value(value: str) -> Any:
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        if value.lower() in ("null", "none", ""):
            return None
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    # ---------- runtime access ----------

    def set(self, key: str, value: Any) -> None:
        old = self.get(key)
        with self._lock:
            self._runtime_layer[key] = value
        new_val = value
        if old != new_val:
            self._notify(key, old, new_val)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            # Priority: runtime > env > file > defaults
            if key in self._runtime_layer:
                return self._runtime_layer[key]
            if key in self._env_layer:
                return self._env_layer[key]
            if key in self._file_layer:
                return self._file_layer[key]
            if key in self._defaults:
                return self._defaults[key]
            return default

    def get_dot(self, path: str, default: Any = None) -> Any:
        """Dot-path access: get_dot('server.host') → get('server')['host']"""
        keys = path.split(".")
        current = None
        for i, key in enumerate(keys):
            if i == 0:
                current = self.get(key)
            elif isinstance(current, dict):
                current = current.get(key)
            else:
                return default
            if current is None:
                return default
        return current

    def all(self) -> dict[str, Any]:
        """Return merged config dict."""
        with self._lock:
            result = deepcopy(self._defaults)
            result = self._deep_merge(result, self._file_layer)
            result = self._deep_merge(result, self._env_layer)
            result = self._deep_merge(result, self._runtime_layer)
            return result

    def reload(self, force: bool = False) -> None:
        """Reload file layer from disk (check mtime unless force=True)."""
        with self._lock:
            for path_str, mtime in list(self._watchers.items()):
                p = Path(path_str)
                if p.exists():
                    new_mtime = p.stat().st_mtime
                    if force or new_mtime > mtime:
                        self._file_layer = {}
                        self.load_file(path_str)
                        self._watchers[path_str] = new_mtime

    # ---------- validation ----------

    def validate(self) -> list[ConfigSchemaError]:
        if not self._schema:
            return []
        return self._schema.validate(self.all())

    # ---------- events ----------

    def on_change(self, callback: Callable[[str, Any, Any], None]) -> None:
        self._on_change.append(callback)

    def _notify(self, key: str, old: Any, new: Any) -> None:
        for cb in self._on_change:
            try:
                cb(key, old, new)
            except Exception:
                pass

    # ---------- internal ----------

    @staticmethod
    def _deep_merge(base: dict, overlay: dict) -> dict:
        result = deepcopy(base)
        for k, v in overlay.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = ConfigManager._deep_merge(result[k], v)
            else:
                result[k] = v
        return result
