"""Tests for agentos.core.config — typed configuration management."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agentos.core.config import (
    ConfigManager,
    ConfigNotFoundError,
    ConfigSource,
    ConfigValidationError,
    SourceType,
)

# ============================================================================
# ConfigSource
# ============================================================================

class TestConfigSourceFromEnv:
    def test_prefix_filtering(self, monkeypatch):
        monkeypatch.setenv("AGENTOS_DB_HOST", "localhost")
        monkeypatch.setenv("AGENTOS_PORT", "8080")
        monkeypatch.setenv("OTHER_VAR", "ignored")

        source = ConfigSource.from_env(prefix="AGENTOS_")
        assert "db_host" in source.data
        assert source.data["db_host"] == "localhost"
        assert source.data["port"] == 8080
        assert "other_var" not in source.data

    def test_no_prefix(self, monkeypatch):
        monkeypatch.setenv("SIMPLE_KEY", "hello")
        source = ConfigSource.from_env()
        assert "simple_key" in source.data

    def test_parse_bool(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ON", "true")
        monkeypatch.setenv("FEATURE_OFF", "false")
        source = ConfigSource.from_env(prefix="FEATURE_")
        assert source.data["on"] is True
        assert source.data["off"] is False

    def test_parse_int_float(self, monkeypatch):
        monkeypatch.setenv("COUNT", "42")
        monkeypatch.setenv("RATIO", "3.14")
        source = ConfigSource.from_env(prefix="")
        assert source.data["count"] == 42
        assert source.data["ratio"] == 3.14

    def test_parse_null(self, monkeypatch):
        monkeypatch.setenv("EMPTY", "")
        monkeypatch.setenv("NONE_VAL", "none")
        source = ConfigSource.from_env(prefix="")
        assert source.data["empty"] is None
        assert source.data["none_val"] is None

    def test_parse_json(self, monkeypatch):
        monkeypatch.setenv("JSON_LIST", '["a","b","c"]')
        monkeypatch.setenv("JSON_DICT", '{"key":"value"}')
        source = ConfigSource.from_env(prefix="JSON_")
        assert source.data["list"] == ["a", "b", "c"]
        assert source.data["dict"] == {"key": "value"}


class TestConfigSourceFromDict:
    def test_basic(self):
        source = ConfigSource.from_dict({"host": "example.com", "port": 5432})
        assert source.source_type == SourceType.DICT
        assert source.data["host"] == "example.com"

    def test_precedence(self):
        source = ConfigSource.from_dict({"key": "value"}, precedence=10)
        assert source.precedence == 10


# ============================================================================
# ConfigManager — Basic
# ============================================================================

class TestConfigManagerBasic:
    def test_auto_env_disabled(self):
        cm = ConfigManager(auto_env=False)
        assert len(cm._sources) == 0

    def test_get_from_dict_source(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"db_host": "prod-db", "db_port": 5432}))
        assert cm.get("db_host") == "prod-db"
        assert cm.get_int("db_port") == 5432

    def test_get_with_default(self):
        cm = ConfigManager(auto_env=False)
        assert cm.get("nonexistent", default="fallback") == "fallback"

    def test_get_missing_raises(self):
        cm = ConfigManager(auto_env=False)
        with pytest.raises(ConfigNotFoundError):
            cm.get("nonexistent")

    def test_get_str(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"name": "agentos"}))
        assert cm.get_str("name") == "agentos"

    def test_get_float(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"threshold": 0.75}))
        assert cm.get_float("threshold") == 0.75

    def test_get_bool_boolean(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"debug": True}))
        assert cm.get_bool("debug") is True

    def test_get_bool_string_true(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"debug": "true"}))
        assert cm.get_bool("debug") is True

    def test_get_bool_string_false(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"debug": "false"}))
        assert cm.get_bool("debug") is False

    def test_get_bool_empty(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"debug": 0}))
        assert cm.get_bool("debug") is False

    def test_get_list_comma(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"hosts": "a,b,c"}))
        result = cm.get_list("hosts")
        assert result == ["a", "b", "c"]

    def test_get_list_actual_list(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"hosts": ["a", "b"]}))
        result = cm.get_list("hosts")
        assert result == ["a", "b"]

    def test_get_dict(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"db": {"host": "localhost", "port": 5432}}))
        result = cm.get_dict("db")
        assert result["host"] == "localhost"

    def test_keys(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"a": 1, "b": 2}))
        assert "a" in cm.keys()
        assert "b" in cm.keys()

    def test_reload(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"key": "old"}))
        assert cm.get("key") == "old"
        cm.set("key", "new")
        assert cm.get("key") == "new"
        cm.reload()
        assert cm.get("key") == "old"

    def test_repr(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"a": 1}))
        repr_str = repr(cm)
        assert "ConfigManager" in repr_str
        assert "sources" in repr_str


# ============================================================================
# ConfigManager — Secret Masking
# ============================================================================

class TestConfigManagerSecrets:
    def test_mark_single_secret(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"api_key": "sk-123456"}))
        cm.mark_secret("api_key")
        d = cm.to_dict()
        assert d["api_key"] == "***MASKED***"

    def test_mark_secrets_list(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"token": "abc", "password": "xyz"}))
        cm.mark_secrets(["token", "password"])
        d = cm.to_dict()
        assert d["token"] == "***MASKED***"
        assert d["password"] == "***MASKED***"

    def test_no_mask_when_disabled(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"api_key": "sk-123"}))
        cm.mark_secret("api_key")
        d = cm.to_dict(mask_secrets=False)
        assert d["api_key"] == "sk-123"


# ============================================================================
# ConfigManager — Change Listeners
# ============================================================================

class TestConfigManagerListeners:
    def test_on_change_fired(self):
        cm = ConfigManager(auto_env=False)
        changes = []

        def listener(key, old, new):
            changes.append((key, old, new))

        cm.on_change(listener)
        cm.add_source(ConfigSource.from_dict({"key": "initial"}))
        cm.set("key", "new_value")
        assert len(changes) == 1
        assert changes[0] == ("key", "initial", "new_value")


# ============================================================================
# ConfigManager — Bind to Dataclass
# ============================================================================

class TestConfigManagerBind:
    @dataclass
    class AppConfig:
        host: str = "0.0.0.0"
        port: int = 8080
        debug: bool = False
        workers: int = 4

    def test_bind_defaults(self):
        cm = ConfigManager(auto_env=False)
        cfg = cm.bind(self.AppConfig)
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8080
        assert cfg.debug is False

    def test_bind_overrides(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"host": "production", "port": 9000, "debug": "true"}))
        cfg = cm.bind(self.AppConfig)
        assert cfg.host == "production"
        assert cfg.port == 9000
        assert cfg.debug is True

    def test_bind_missing_required_raises(self):
        @dataclass
        class Required:
            mandatory: str  # No default

        cm = ConfigManager(auto_env=False)
        with pytest.raises(ConfigNotFoundError):
            cm.bind(Required)

    def test_bind_optional_field(self):
        @dataclass
        class OptionalFields:
            a: str = "default_a"
            b: int = 42

        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"a": "override"}))
        cfg = cm.bind(OptionalFields)
        assert cfg.a == "override"
        assert cfg.b == 42


# ============================================================================
# ConfigManager — Precedence
# ============================================================================

class TestConfigManagerPrecedence:
    def test_lower_precedence_wins(self):
        """Lower precedence number = higher priority."""
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"key": "low"}, precedence=500))
        cm.add_source(ConfigSource.from_dict({"key": "high"}, precedence=100))
        assert cm.get("key") == "high"

    def test_multiple_sources_merged(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"a": 1}, precedence=100))
        cm.add_source(ConfigSource.from_dict({"b": 2}, precedence=200))
        assert cm.get("a") == 1
        assert cm.get("b") == 2


# ============================================================================
# Config Errors
# ============================================================================

class TestConfigErrors:
    def test_config_validation_error(self):
        err = ConfigValidationError("path.to.field", "bad", "expected int")
        assert "path.to.field" in str(err)
        assert "bad" in str(err)

    def test_config_not_found_error(self):
        err = ConfigNotFoundError("missing key")
        assert "missing key" in str(err)


# ============================================================================
# SourceType
# ============================================================================

class TestSourceType:
    def test_enum_values(self):
        assert SourceType.ENV.value == "env"
        assert SourceType.DICT.value == "dict"
        assert SourceType.YAML.value == "yaml"
        assert SourceType.JSON.value == "json"
        assert SourceType.TOML.value == "toml"
        assert SourceType.DOTENV.value == "dotenv"
