"""Tests for agentos.tools.config_manager."""

import json
import os
import tempfile

from agentos.tools.config_manager import ConfigManager, ConfigSchema


class TestConfigManager:
    def test_defaults(self):
        cm = ConfigManager(defaults={"host": "localhost", "port": 8080})
        assert cm.get("host") == "localhost"
        assert cm.get("port") == 8080

    def test_default_missing(self):
        cm = ConfigManager()
        assert cm.get("nonexistent") is None
        assert cm.get("nonexistent", "fallback") == "fallback"

    def test_runtime_override(self):
        cm = ConfigManager(defaults={"x": 1})
        cm.set("x", 99)
        assert cm.get("x") == 99

    def test_load_json_file(self):
        d = {"key": "value", "nested": {"a": 1}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(d, f)
            path = f.name
        try:
            cm = ConfigManager()
            cm.load_file(path)
            assert cm.get("key") == "value"
        finally:
            os.unlink(path)

    def test_file_override_default(self):
        cm = ConfigManager(defaults={"host": "localhost"})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"host": "prod.example.com"}, f)
            path = f.name
        try:
            cm.load_file(path)
            assert cm.get("host") == "prod.example.com"
        finally:
            os.unlink(path)

    def test_env_override(self):
        cm = ConfigManager(defaults={"db_url": "localhost"})
        os.environ["TEST_DB_URL"] = "prod-db"
        try:
            cm.load_env("TEST_")
            assert cm.get("db_url") == "prod-db"
        finally:
            del os.environ["TEST_DB_URL"]

    def test_env_value_parsing(self):
        cm = ConfigManager()
        os.environ["T_INT"] = "42"
        os.environ["T_FLOAT"] = "3.14"
        os.environ["T_BOOL"] = "true"
        os.environ["T_STR"] = "hello"
        try:
            cm.load_env("T_")
            assert cm.get("int") == 42
            assert cm.get("float") == 3.14
            assert cm.get("bool") is True
            assert cm.get("str") == "hello"
        finally:
            for k in ("T_INT", "T_FLOAT", "T_BOOL", "T_STR"):
                os.environ.pop(k, None)

    def test_priority_runtime_over_env(self):
        cm = ConfigManager(defaults={"x": 1})
        os.environ["P_X"] = "2"
        try:
            cm.load_env("P_")
            cm.set("x", 3)
            assert cm.get("x") == 3
        finally:
            os.environ.pop("P_X", None)

    def test_priority_env_over_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"x": 10}, f)
            path = f.name
        try:
            cm = ConfigManager()
            cm.load_file(path)
            os.environ["P_X"] = "20"
            cm.load_env("P_")
            assert cm.get("x") == 20
        finally:
            os.unlink(path)
            os.environ.pop("P_X", None)

    def test_dot_path(self):
        cm = ConfigManager(defaults={"server": {"host": "localhost", "port": 8080}})
        assert cm.get_dot("server.host") == "localhost"
        assert cm.get_dot("server.port") == 8080
        assert cm.get_dot("server.nonexistent") is None
        assert cm.get_dot("nonexistent.path") is None

    def test_all(self):
        cm = ConfigManager(defaults={"a": 1, "b": 2})
        cm.set("c", 3)
        result = cm.all()
        assert result["a"] == 1
        assert result["b"] == 2
        assert result["c"] == 3

    def test_on_change(self):
        calls = []

        def cb(key, old, new):
            calls.append((key, old, new))

        cm = ConfigManager()
        cm.on_change(cb)
        cm.set("x", 42)
        assert calls == [("x", None, 42)]
        cm.set("x", 99)
        assert calls[-1] == ("x", 42, 99)

    def test_reload(self):
        d = {"v": 1}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(d, f)
            path = f.name
        try:
            cm = ConfigManager()
            cm.load_file(path)
            assert cm.get("v") == 1
            # Write new value
            with open(path, "w") as fw:
                json.dump({"v": 2}, fw)
            cm.reload(force=True)
            assert cm.get("v") == 2
        finally:
            os.unlink(path)

    def test_deep_merge_dicts(self):
        cm = ConfigManager(defaults={"db": {"host": "a", "port": 1}})
        cm.set("db", {"host": "b"})
        result = cm.all()
        # runtime set replaces entire 'db' dict in deep_merge for runtime layer
        assert result["db"]["host"] == "b"


class TestConfigSchema:
    def test_valid(self):
        s = ConfigSchema()
        s.field("port", type_=int, required=True, min_val=1, max_val=65535)
        errors = s.validate({"port": 8080})
        assert len(errors) == 0

    def test_type_error(self):
        s = ConfigSchema().field("port", type_=int)
        errors = s.validate({"port": "abc"})
        assert len(errors) == 1
        assert "expected int" in errors[0].message

    def test_required(self):
        s = ConfigSchema().field("host", required=True)
        errors = s.validate({})
        assert len(errors) == 1
        assert "required" in errors[0].message

    def test_choices(self):
        s = ConfigSchema().field("level", type_=str, choices=["debug", "info", "error"])
        errors = s.validate({"level": "warn"})
        assert len(errors) == 1
        assert "invalid choice" in errors[0].message

    def test_range(self):
        s = ConfigSchema().field("retries", type_=int, min_val=0, max_val=10)
        assert len(s.validate({"retries": 5})) == 0
        assert len(s.validate({"retries": -1})) == 1
        assert len(s.validate({"retries": 11})) == 1

    def test_integration_with_manager(self):
        s = ConfigSchema().field("port", type_=int, required=True, min_val=1)
        cm = ConfigManager(defaults={"port": 8080}, schema=s)
        assert len(cm.validate()) == 0
        cm.set("port", "invalid")
        errors = cm.validate()
        assert len(errors) == 1
