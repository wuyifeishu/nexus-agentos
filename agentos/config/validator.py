"""AgentOS configuration validation — JSON Schema-based config integrity checks.  # noqa: E501

Validates agentos.yaml and environment configurations at startup and reload.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ── Schema definition ─────────────────────────────────────────────────────────

AGENTOS_CONFIG_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "AgentOS Configuration",
    "type": "object",
    "required": ["agentos"],
    "properties": {
        "agentos": {
            "type": "object",
            "required": ["version"],
            "properties": {
                "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
                "name": {"type": "string", "minLength": 1},
                "debug": {"type": "boolean"},
                "models": {
                    "type": "object",
                    "properties": {
                        "default_provider": {
                            "type": "string",
                            "enum": ["openai", "anthropic", "gemini", "deepseek"],
                        },
                        "default_model": {"type": "string"},
                        "temperature": {"type": "number", "minimum": 0.0, "maximum": 2.0},
                        "max_retries": {"type": "integer", "minimum": 0, "maximum": 10},
                        "request_timeout": {"type": "integer", "minimum": 1, "maximum": 600},
                    },
                },
                "memory": {
                    "type": "object",
                    "properties": {
                        "short_term_limit": {"type": "integer", "minimum": 1},
                        "long_term_backend": {
                            "type": "string",
                            "enum": ["chromadb", "faiss", "qdrant", "pinecone"],
                        },
                        "summarization_threshold": {"type": "integer", "minimum": 100},
                    },
                },
                "server": {
                    "type": "object",
                    "properties": {
                        "host": {"type": "string"},
                        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                        "workers": {"type": "integer", "minimum": 1, "maximum": 64},
                        "timeout_keep_alive": {"type": "integer", "minimum": 1},
                    },
                },
                "security": {
                    "type": "object",
                    "properties": {
                        "sandbox": {"type": "boolean"},
                        "allowed_commands": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "pii_sanitizer": {"type": "boolean"},
                        "audit_log": {"type": "boolean"},
                    },
                },
                "benchmarks": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "iterations": {"type": "integer", "minimum": 1},
                        "output_format": {"type": "string", "enum": ["json", "csv", "markdown"]},
                    },
                },
            },
        },
    },
}


# ── Validation result ─────────────────────────────────────────────────────────


class ValidationLevel(Enum):
    """校验等级。"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """校验问题。"""

    level: ValidationLevel
    path: str
    message: str


@dataclass
class ValidationResult:
    """校验结果。"""

    valid: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == ValidationLevel.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == ValidationLevel.WARNING]

    def add_error(self, path: str, message: str):
        self.issues.append(ValidationIssue(ValidationLevel.ERROR, path, message))
        self.valid = False

    def add_warning(self, path: str, message: str):
        self.issues.append(ValidationIssue(ValidationLevel.WARNING, path, message))

    def __str__(self) -> str:
        if self.valid and not self.issues:
            return "Configuration valid"
        lines = [
            f"Configuration {'valid' if self.valid else 'invalid'} ({len(self.errors)} errors, {len(self.warnings)} warnings)"  # noqa: E501
        ]
        for i in self.issues:
            lines.append(f"  [{i.level.value}] {i.path}: {i.message}")
        return "\n".join(lines)


# ── Validator ─────────────────────────────────────────────────────────────────


def _validate_type(value: Any, expected: str, schema: dict) -> str | None:
    """Return error string or None."""
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    py_type = type_map.get(expected)
    if py_type is None:
        return None
    if not isinstance(value, py_type):
        return f"expected {expected}, got {type(value).__name__}"
    return None


def _walk_schema(
    config: dict, schema: dict, path: str = "", result: ValidationResult | None = None
) -> ValidationResult:
    if result is None:
        result = ValidationResult()

    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(config, dict):
            result.add_error(path, f"expected object, got {type(config).__name__}")
            return result
        # Required fields
        for req in schema.get("required", []):
            if req not in config:
                result.add_error(f"{path}.{req}" if path else req, "required field missing")
        # Properties
        for prop, prop_schema in schema.get("properties", {}).items():
            if prop in config:
                child_path = f"{path}.{prop}" if path else prop
                _walk_schema(config[prop], prop_schema, child_path, result)
        # Enum check for object itself (rare)
    elif schema_type in ("string", "integer", "number", "boolean"):
        err = _validate_type(config, schema_type, schema)
        if err:
            result.add_error(path, err)
            return result
        if "enum" in schema and config not in schema["enum"]:
            result.add_error(path, f"must be one of {schema['enum']}, got {config!r}")
        if "pattern" in schema and isinstance(config, str):
            import re

            if not re.match(schema["pattern"], config):
                result.add_error(path, f"'{config}' does not match pattern {schema['pattern']}")
        if "minimum" in schema and isinstance(config, (int, float)):
            if config < schema["minimum"]:
                result.add_error(path, f"{config} < minimum {schema['minimum']}")
        if "maximum" in schema and isinstance(config, (int, float)):
            if config > schema["maximum"]:
                result.add_error(path, f"{config} > maximum {schema['maximum']}")
        if "minLength" in schema and isinstance(config, str):
            if len(config) < schema["minLength"]:
                result.add_error(path, f"length {len(config)} < min {schema['minLength']}")
    elif schema_type == "array":
        if not isinstance(config, list):
            result.add_error(path, f"expected array, got {type(config).__name__}")
            return result

    return result


def validate_config(config: dict, schema: dict | None = None) -> ValidationResult:
    """Validate an AgentOS configuration dict against the built-in JSON Schema."""
    schema = schema or AGENTOS_CONFIG_SCHEMA
    return _walk_schema(config, schema)


def validate_config_file(file_path: str) -> ValidationResult:
    """Load and validate an AgentOS configuration YAML/JSON file."""
    import os

    if not os.path.exists(file_path):
        result = ValidationResult()
        result.add_error("", f"config file not found: {file_path}")
        return result

    with open(file_path) as f:
        if file_path.endswith((".yaml", ".yml")):
            try:
                import yaml

                config = yaml.safe_load(f)
            except ImportError:
                import json

                config = json.load(f)  # fallback, may fail
        else:
            config = json.load(f)

    return validate_config(config)


def generate_schema_json() -> str:
    """Return the AgentOS config JSON Schema as a formatted JSON string."""
    return json.dumps(AGENTOS_CONFIG_SCHEMA, indent=2)
