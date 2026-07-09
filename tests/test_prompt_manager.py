"""
Tests for AgentOS Prompt Manager (agentos/core/prompt_manager.py)
"""

import json

import pytest

from agentos.core.prompt_manager import (
    ABTest,
    ABTestManager,
    PromptRole,
    PromptStore,
    PromptTemplate,
)


class TestPromptTemplate:
    """PromptTemplate unit tests."""

    def test_creation(self):
        t = PromptTemplate(name="greeting", content="Hello {{name}}!")
        assert t.name == "greeting"
        assert t.version == 1
        assert t.content == "Hello {{name}}!"
        assert t.role == PromptRole.SYSTEM

    def test_extract_variables(self):
        t = PromptTemplate(
            name="welcome",
            content="Dear {{user}}, your balance is {{amount}} {{currency}}"
        )
        vars_ = t.extract_variables()
        assert vars_ == {"user", "amount", "currency"}

    def test_extract_variables_empty(self):
        t = PromptTemplate(name="static", content="Hello World")
        assert t.extract_variables() == set()

    def test_render_success(self):
        t = PromptTemplate(name="greeting", content="Hello {{name}}!")
        result = t.render({"name": "Alice"})
        assert result == "Hello Alice!"

    def test_render_multiple_vars(self):
        t = PromptTemplate(
            name="report",
            content="{{user}}: {{action}} on {{date}}"
        )
        result = t.render({"user": "Bob", "action": "login", "date": "2026-01-01"})
        assert result == "Bob: login on 2026-01-01"

    def test_render_missing_var_strict(self):
        t = PromptTemplate(name="greeting", content="Hello {{name}}!")
        with pytest.raises(ValueError, match="missing variables"):
            t.render({}, strict=True)

    def test_render_missing_var_non_strict(self):
        t = PromptTemplate(name="greeting", content="Hello {{name}}!")
        result = t.render({}, strict=False)
        assert "{{name}}" in result  # Placeholder left intact

    def test_validate_valid(self):
        t = PromptTemplate(name="test", content="Hello {{world}}")
        valid, issues = t.validate()
        assert valid
        assert len(issues) == 0

    def test_validate_missing_name(self):
        t = PromptTemplate(name="", content="Hello")
        valid, issues = t.validate()
        assert not valid
        assert any("Name" in i for i in issues)

    def test_validate_empty_content(self):
        t = PromptTemplate(name="test", content="")
        valid, issues = t.validate()
        assert not valid
        assert any("empty" in i.lower() for i in issues)

    def test_diff(self):
        t1 = PromptTemplate(name="p", version=1, content="Hello Alice")
        t2 = PromptTemplate(name="p", version=2, content="Hello Bob")
        diff = t1.diff(t2)
        assert "Alice" in diff
        assert "Bob" in diff

    def test_to_dict_and_from_dict(self):
        t = PromptTemplate(
            name="test", version=3, content="Hi {{x}}",
            role=PromptRole.USER, tags=["tag1"], author="dev"
        )
        d = t.to_dict()
        restored = PromptTemplate.from_dict(d)
        assert restored.name == "test"
        assert restored.version == 3
        assert restored.role == PromptRole.USER
        assert restored.tags == ["tag1"]

    def test_role_enum(self):
        assert PromptRole.SYSTEM.value == "system"
        assert PromptRole.USER.value == "user"
        assert PromptRole.ASSISTANT.value == "assistant"


class TestPromptStore:
    """PromptStore registry tests."""

    def test_add_template(self):
        store = PromptStore()
        t = PromptTemplate(name="greeting", content="Hello!")
        store.add(t)
        retrieved = store.get("greeting")
        assert retrieved is not None
        assert retrieved.content == "Hello!"

    def test_version_auto_increment(self):
        store = PromptStore()
        t1 = store.add(PromptTemplate(name="p", content="v1"))
        t2 = store.add(PromptTemplate(name="p", content="v2"))
        assert t1.version == 1
        assert t2.version == 2

    def test_get_specific_version(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        v1 = store.get("p", version=1)
        v2 = store.get("p", version=2)
        assert v1.content == "v1"
        assert v2.content == "v2"

    def test_get_latest(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        latest = store.get_latest("p")
        assert latest.content == "v2"

    def test_get_nonexistent(self):
        store = PromptStore()
        assert store.get("nope") is None
        assert store.get_latest("nope") is None
        assert store.get("nope", version=99) is None

    def test_set_active(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        store.set_active("p", 1)
        active = store.get("p")  # defaults to active
        assert active.version == 1

    def test_deactivate(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.deactivate("p")
        # After deactivate, get falls back to latest
        active = store.get("p")
        assert active is not None  # falls back

    def test_list_templates(self):
        store = PromptStore()
        store.add(PromptTemplate(name="a", content="A"))
        store.add(PromptTemplate(name="a", content="A2"))
        store.add(PromptTemplate(name="b", content="B"))
        listing = store.list_templates()
        names = [x["name"] for x in listing]
        assert "a" in names
        assert "b" in names
        assert listing[0]["total_versions"] == 2 or listing[1]["total_versions"] == 2

    def test_get_history(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        store.add(PromptTemplate(name="p", content="v3"))
        history = store.get_history("p")
        assert len(history) == 3
        assert history[0].version == 1
        assert history[2].version == 3

    def test_diff_versions(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="line1\nline2"))
        store.add(PromptTemplate(name="p", content="line1\nline2-modified"))
        diff = store.diff_versions("p", 1, 2)
        assert diff is not None
        assert "line2" in diff

    def test_diff_nonexistent(self):
        store = PromptStore()
        assert store.diff_versions("p", 1, 2) is None

    def test_remove_specific_version(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        removed = store.remove("p", version=1)
        assert removed == 1
        assert store.get("p", version=1) is None
        assert store.get("p", version=2) is not None

    def test_remove_all_versions(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        removed = store.remove("p")
        assert removed == 2
        assert store.get("p") is None

    def test_export_import_json(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="Hello {{name}}"))
        json_str = store.export_json()
        data = json.loads(json_str)
        assert "templates" in data
        assert len(data["templates"]) == 1

        # Import into new store
        store2 = PromptStore()
        count = store2.import_json(json_str)
        assert count == 1
        assert store2.get("p").content == "Hello {{name}}"

    def test_variables_auto_extract_on_add(self):
        store = PromptStore()
        t = store.add(PromptTemplate(name="p", content="{{a}} and {{b}}"))
        assert t.variables == {"a", "b"}


class TestABTest:
    """A/B test routing tests."""

    def test_route_deterministic(self):
        test = ABTest(
            name="test1", template_name="p",
            variant_a_version=1, variant_b_version=2, split_ratio=0.5,
        )
        # Same session should always route to same variant
        v1 = test.route("session-abc")
        v2 = test.route("session-abc")
        assert v1 == v2

    def test_route_different_sessions(self):
        test = ABTest(
            name="test1", template_name="p",
            variant_a_version=1, variant_b_version=2, split_ratio=0.5,
        )
        # Different sessions may route to different variants
        results = {test.route(f"session-{i}") for i in range(100)}
        assert 0 in results or 1 in results

    def test_route_inactive_defaults_to_a(self):
        test = ABTest(
            name="test1", template_name="p",
            variant_a_version=1, variant_b_version=2, split_ratio=0.5,
            is_active=False,
        )
        assert test.route("any-session") == 0

    def test_split_ratio_100_a(self):
        test = ABTest(
            name="test1", template_name="p",
            variant_a_version=1, variant_b_version=2, split_ratio=1.0,
        )
        for i in range(50):
            assert test.route(f"s{i}") == 0


class TestABTestManager:
    """A/B test manager integration tests."""

    def test_create_test(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        mgr = ABTestManager(store)
        test = mgr.create_test("exp1", "p", 1, 2, 0.5)
        assert test.name == "exp1"

    def test_get_template(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        mgr = ABTestManager(store)
        mgr.create_test("exp1", "p", 1, 2, 0.5)

        t = mgr.get_template("exp1", "test-session")
        assert t is not None
        assert t.content in ("v1", "v2")

    def test_get_template_nonexistent_test(self):
        store = PromptStore()
        mgr = ABTestManager(store)
        assert mgr.get_template("nope", "s") is None

    def test_get_results(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        mgr = ABTestManager(store)
        mgr.create_test("exp1", "p", 1, 2, 0.5)

        for i in range(20):
            mgr.get_template("exp1", f"session-{i}")

        results = mgr.get_results("exp1")
        assert results["total_served"] == 20
        assert "a_served" in results

    def test_stop_test(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        mgr = ABTestManager(store)
        mgr.create_test("exp1", "p", 1, 2)
        mgr.stop_test("exp1")
        results = mgr.get_results("exp1")
        assert not results["is_active"]

    def test_list_tests(self):
        store = PromptStore()
        store.add(PromptTemplate(name="p", content="v1"))
        store.add(PromptTemplate(name="p", content="v2"))
        mgr = ABTestManager(store)
        mgr.create_test("exp1", "p", 1, 2)
        mgr.create_test("exp2", "p", 1, 2)
        tests = mgr.list_tests()
        assert len(tests) == 2
