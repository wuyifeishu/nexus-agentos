"""Tests for agentos.core.config — ConfigManager, ConfigSource, helpers."""

import json
import os
import tempfile
from dataclasses import dataclass

import pytest

from agentos.core.config import (
    ConfigError,
    ConfigManager,
    ConfigNotFoundError,
    ConfigSource,
    SourceType,
    _coerce,
    _flatten_dict,
    _parse_env_value,
)

# ============================================================================
# _parse_env_value
# ============================================================================

class TestParseEnvValue:
    def test_bool_true(self):
        assert _parse_env_value("true") is True
        assert _parse_env_value("yes") is True
        assert _parse_env_value("on") is True

    def test_bool_false(self):
        assert _parse_env_value("false") is False
        assert _parse_env_value("no") is False
        assert _parse_env_value("off") is False

    def test_null(self):
        assert _parse_env_value("null") is None
        assert _parse_env_value("none") is None
        assert _parse_env_value("") is None

    def test_int(self):
        assert _parse_env_value("42") == 42
        assert _parse_env_value("-10") == -10

    def test_float(self):
        assert _parse_env_value("3.14") == 3.14

    def test_json(self):
        assert _parse_env_value('[1,2,3]') == [1, 2, 3]
        assert _parse_env_value('{"a":1}') == {"a": 1}

    def test_fallback_to_string(self):
        assert _parse_env_value("hello world") == "hello world"


# ============================================================================
# _flatten_dict
# ============================================================================

class TestFlattenDict:
    def test_flat(self):
        assert _flatten_dict({"a": 1, "b": 2}) == {"a": 1, "b": 2}

    def test_nested(self):
        d = {"database": {"host": "localhost", "port": 5432}}
        result = _flatten_dict(d)
        assert result == {"database_host": "localhost", "database_port": 5432}

    def test_deep_nested(self):
        d = {"a": {"b": {"c": 1}}}
        assert _flatten_dict(d) == {"a_b_c": 1}

    def test_skip_environ_style(self):
        d = {"DB_HOST": "1", "nested": {"x": 2}}
        result = _flatten_dict(d)
        assert "db_host" in result
        assert "nested_x" in result

    def test_skip_list_value(self):
        d = {"items": [1, 2, 3]}
        assert _flatten_dict(d) == {"items": [1, 2, 3]}


# ============================================================================
# _coerce
# ============================================================================

class TestCoerce:
    def test_none(self):
        assert _coerce(None, str) is None

    def test_bool_from_str(self):
        assert _coerce("true", bool) is True

    def test_bool_already_bool(self):
        assert _coerce(True, bool) is True

    def test_int(self):
        assert _coerce("42", int) == 42

    def test_float(self):
        assert _coerce("3.14", float) == 3.14

    def test_str(self):
        assert _coerce(42, str) == "42"

    def test_list_from_str(self):
        assert _coerce("a,b,c", list) == ["a", "b", "c"]

    def test_list_already_list(self):
        assert _coerce([1, 2], list) == [1, 2]

    def test_dict(self):
        assert _coerce({"a": 1}, dict) == {"a": 1}

    def test_optional_pass(self):
        assert _coerce("hello", str | None) == "hello"
        assert _coerce(None, str | None) is None

    def test_dataclass_coerce(self):
        @dataclass
        class Sub:
            x: int = 1
        result = _coerce({"x": 42}, Sub)
        assert result.x == 42


# ============================================================================
# ConfigSource
# ============================================================================

class TestConfigSource:
    def test_from_dict(self):
        s = ConfigSource.from_dict({"a": 1, "b": "hello"})
        assert s.source_type == SourceType.DICT
        assert s.data == {"a": 1, "b": "hello"}
        assert s.precedence == 500

    def test_from_env(self):
        os.environ["TEST_CFG_KEY"] = "42"
        s = ConfigSource.from_env(prefix="TEST_CFG_")
        assert "key" in s.data
        assert s.data["key"] == 42
        del os.environ["TEST_CFG_KEY"]

    def test_from_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"host": "localhost", "port": 5432}, f)
            f.flush()
            s = ConfigSource.from_json(f.name)
        os.unlink(f.name)
        assert s.data["host"] == "localhost"
        assert s.data["port"] == 5432

    def test_from_dotenv(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("HOST=localhost\nPORT=8080\nDEBUG=true\n")
            f.flush()
            s = ConfigSource.from_dotenv(f.name)
        os.unlink(f.name)
        assert s.data["host"] == "localhost"
        assert s.data["port"] == 8080
        assert s.data["debug"] is True

    def test_from_dotenv_not_found(self):
        with pytest.raises(ConfigError):
            ConfigSource.from_dotenv("/nonexistent/path/.env")

    def test_from_dotenv_not_found_override(self):
        s = ConfigSource.from_dotenv("/nonexistent/path/.env", override=True)
        assert s.data == {}

    def test_from_yaml_not_found(self):
        with pytest.raises(ConfigError):
            ConfigSource.from_yaml("/nonexistent/config.yaml")

    def test_from_json_not_found(self):
        with pytest.raises(ConfigError):
            ConfigSource.from_json("/nonexistent/config.json")


# ============================================================================
# ConfigManager
# ============================================================================

class TestConfigManager:
    def test_get_basic(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"host": "localhost"}))
        assert cm.get("host") == "localhost"

    def test_get_missing_raises(self):
        cm = ConfigManager(auto_env=False)
        with pytest.raises(ConfigNotFoundError):
            cm.get("nonexistent")

    def test_get_default(self):
        cm = ConfigManager(auto_env=False)
        assert cm.get("missing", "default") == "default"

    def test_get_str(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"port": 8080}))
        assert cm.get_str("port") == "8080"

    def test_get_int(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"port": "8080"}))
        assert cm.get_int("port") == 8080

    def test_get_float(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"rate": "3.14"}))
        assert cm.get_float("rate") == 3.14

    def test_get_bool(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"debug": "true", "verbose": "yes"}))
        assert cm.get_bool("debug") is True
        assert cm.get_bool("verbose") is True

    def test_get_bool_real_false(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"debug": False}))
        assert cm.get_bool("debug") is False

    def test_get_list_from_str(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"hosts": "a,b,c"}))
        assert cm.get_list("hosts") == ["a", "b", "c"]

    def test_get_list_already_list(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"hosts": ["a", "b"]}))
        assert cm.get_list("hosts") == ["a", "b"]

    def test_get_dict(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"db": {"host": "localhost"}}))
        assert cm.get_dict("db") == {"host": "localhost"}

    def test_keys(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"a": 1, "b": 2}))
        assert cm.keys() == ["a", "b"]

    def test_to_dict(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"a": 1}))
        assert cm.to_dict() == {"a": 1}

    def test_mask_secrets(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"password": "secret123", "host": "localhost"}))
        cm.mark_secret("password")
        d = cm.to_dict(mask_secrets=True)
        assert d["password"] == "***MASKED***"
        assert d["host"] == "localhost"

    def test_precedence(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"key": "low"}, precedence=500))
        cm.add_source(ConfigSource.from_dict({"key": "high"}, precedence=100))
        assert cm.get("key") == "high"

    def test_set(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"key": "old"}))
        cm.set("key", "new")
        assert cm.get("key") == "new"

    def test_on_change(self):
        cm = ConfigManager(auto_env=False)
        changes = []

        def cb(key, old, new):
            changes.append((key, old, new))

        cm.on_change(cb)
        cm.add_source(ConfigSource.from_dict({"key": "old"}))
        cm.set("key", "new")
        assert changes == [("key", "old", "new")]

    def test_reload(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"key": "v1"}))
        assert cm.get("key") == "v1"
        cm.reload()
        assert cm.get("key") == "v1"

    def test_repr(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"a": 1}))
        r = repr(cm)
        assert "ConfigManager" in r
        assert "sources=1" in r

    def test_custom_separator(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"items": "a|b|c"}))
        assert cm.get_list("items", separator="|") == ["a", "b", "c"]

    def test_auto_env(self):
        os.environ["AGENTOS_TEST_X"] = "hello"
        cm = ConfigManager(auto_env=True, env_prefix="AGENTOS_")
        assert cm.get("test_x") == "hello"
        del os.environ["AGENTOS_TEST_X"]

    def test_bind_dataclass(self):
        @dataclass
        class AppConfig:
            host: str = "0.0.0.0"
            port: int = 8080
            debug: bool = False

        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"host": "10.0.0.1", "port": "3000", "debug": "true"}))
        cfg = cm.bind(AppConfig)
        assert cfg.host == "10.0.0.1"
        assert cfg.port == 3000
        assert cfg.debug is True

    def test_bind_defaults(self):
        @dataclass
        class AppConfig:
            host: str = "0.0.0.0"
            port: int = 8080

        cm = ConfigManager(auto_env=False)
        cfg = cm.bind(AppConfig)
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8080
