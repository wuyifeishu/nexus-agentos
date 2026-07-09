"""Tests for agentos.core.config — Configuration Management."""

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from agentos.core.config import (
    ConfigManager,
    ConfigNotFoundError,
    ConfigSource,
)


class TestConfigSource:
    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("PREFIX_KEY1", "hello")
        monkeypatch.setenv("PREFIX_KEY2", "42")
        monkeypatch.setenv("OTHER_VAR", "ignored")
        src = ConfigSource.from_env(prefix="PREFIX_")
        assert src.data["key1"] == "hello"
        assert src.data["key2"] == 42
        assert "other_var" not in src.data

    def test_from_env_no_prefix(self, monkeypatch):
        monkeypatch.setenv("MY_CONFIG", "test")
        src = ConfigSource.from_env()
        assert src.data["my_config"] == "test"

    def test_from_dict(self):
        src = ConfigSource.from_dict({"host": "localhost", "port": 8080})
        assert src.data["host"] == "localhost"
        assert src.data["port"] == 8080

    def test_from_dict_nested(self):
        src = ConfigSource.from_dict({"database": {"host": "db1", "port": 5432}})
        assert src.data["database"]["host"] == "db1"
        assert src.data["database"]["port"] == 5432

    def test_from_yaml(self):
        yaml_content = """
        server:
          host: 0.0.0.0
          port: 8080
        debug: true
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            path = Path(f.name)

        try:
            src = ConfigSource.from_yaml(path)
            assert src.data["server_host"] == "0.0.0.0"
            assert src.data["server_port"] == 8080
            assert src.data["debug"] is True
        finally:
            path.unlink()

    def test_from_json(self):
        data = {"host": "jsonhost", "port": 9090}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(data, f)
            path = Path(f.name)

        try:
            src = ConfigSource.from_json(path)
            assert src.data["host"] == "jsonhost"
            assert src.data["port"] == 9090
        finally:
            path.unlink()


class TestConfigManager:
    @pytest.fixture
    def cm(self):
        return ConfigManager(auto_env=False)

    def test_get_str(self, cm):
        cm.add_source(ConfigSource.from_dict({"name": "test-app"}))
        assert cm.get_str("name") == "test-app"

    def test_get_default(self, cm):
        assert cm.get("missing", default="fallback") == "fallback"

    def test_get_required_missing(self, cm):
        with pytest.raises(ConfigNotFoundError):
            cm.get("nonexistent")

    def test_get_int(self, cm):
        cm.add_source(ConfigSource.from_dict({"port": "8080"}))
        assert cm.get_int("port") == 8080

    def test_get_float(self, cm):
        cm.add_source(ConfigSource.from_dict({"rate": "2.5"}))
        assert cm.get_float("rate") == 2.5

    def test_get_bool(self, cm):
        cm.add_source(ConfigSource.from_dict({"debug": "true"}))
        assert cm.get_bool("debug") is True

    def test_get_bool_false(self, cm):
        cm.add_source(ConfigSource.from_dict({"debug": "false"}))
        assert cm.get_bool("debug") is False

    def test_get_list(self, cm):
        cm.add_source(ConfigSource.from_dict({"hosts": "a,b,c"}))
        assert cm.get_list("hosts") == ["a", "b", "c"]

    def test_get_list_already_list(self, cm):
        cm.add_source(ConfigSource.from_dict({"hosts": ["a", "b"]}))
        assert cm.get_list("hosts") == ["a", "b"]

    def test_keys(self, cm):
        cm.add_source(ConfigSource.from_dict({"a": 1, "b": 2}))
        assert sorted(cm.keys()) == ["a", "b"]

    def test_to_dict(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"host": "prod", "port": 80}))
        d = cm.to_dict()
        assert d["host"] == "prod"
        assert d["port"] == 80

    def test_secret_masking(self, cm):
        cm.add_source(ConfigSource.from_dict({"password": "s3cret"}))
        cm.add_source(ConfigSource.from_dict({"public": "visible"}))
        cm.mark_secret("password")
        d = cm.to_dict(mask_secrets=True)
        assert d["password"] == "***MASKED***"
        assert d["public"] == "visible"

    def test_precedence(self):
        cm = ConfigManager(auto_env=False)
        cm.add_source(ConfigSource.from_dict({"key": "low"}, precedence=500))
        cm.add_source(ConfigSource.from_dict({"key": "high"}, precedence=100))
        assert cm.get_str("key") == "high"

    # -- bind to dataclass --

    def test_bind_dataclass(self, cm):
        @dataclass
        class AppConfig:
            host: str = "0.0.0.0"
            port: int = 8080
            debug: bool = False

        cm.add_source(ConfigSource.from_dict({"host": "prod.local", "port": "80"}))
        cfg = cm.bind(AppConfig)
        assert cfg.host == "prod.local"
        assert cfg.port == 80
        assert cfg.debug is False

    def test_bind_missing_required(self, cm):
        @dataclass
        class BadConfig:
            required_key: str  # no default

        with pytest.raises(ConfigNotFoundError):
            cm.bind(BadConfig)

    def test_set_and_get(self, cm):
        cm.set("runtime_key", "runtime_value")
        assert cm.get_str("runtime_key") == "runtime_value"

    def test_reload(self, cm):
        cm.add_source(ConfigSource.from_dict({"v": "1"}))
        assert cm.get_str("v") == "1"
        # Simulate a new source added after reload
        cm.add_source(ConfigSource.from_dict({"v": "2"}, precedence=50))
        cm.reload()
        assert cm.get_str("v") == "2"

    def test_get_dict(self, cm):
        cm.add_source(ConfigSource.from_dict({"meta": {"env": "prod", "region": "us"}}))
        d = cm.get_dict("meta")
        assert d["env"] == "prod"
        assert d["region"] == "us"


class TestEnvValueParsing:
    def test_bool_parsing(self, monkeypatch):
        monkeypatch.setenv("TEST_BOOL_TRUE", "true")
        monkeypatch.setenv("TEST_BOOL_FALSE", "false")
        monkeypatch.setenv("TEST_BOOL_YES", "yes")
        monkeypatch.setenv("TEST_BOOL_NO", "no")
        cm = ConfigManager(auto_env=True, env_prefix="TEST_")
        assert cm.get_bool("bool_true") is True
        assert cm.get_bool("bool_false") is False
        assert cm.get_bool("bool_yes") is True
        assert cm.get_bool("bool_no") is False

    def test_null_parsing(self, monkeypatch):
        monkeypatch.setenv("TEST_NULL", "null")
        cm = ConfigManager(auto_env=True, env_prefix="TEST_")
        assert cm.get("null") is None

    def test_json_parsing(self, monkeypatch):
        monkeypatch.setenv("TEST_JSON", '{"key": "val"}')
        cm = ConfigManager(auto_env=True, env_prefix="TEST_")
        assert cm.get("json") == {"key": "val"}
