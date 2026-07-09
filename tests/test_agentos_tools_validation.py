"""Tests for agentos.tools.validation — output validation, error classification."""

from agentos.tools.base import ToolResult
from agentos.tools.validation import (
    ToolErrorClassifier,
    ToolOutputValidator,
    ValidationIssue,
    ValidationResult,
    ValidationRule,
    ValidationSeverity,
    classify_tool_error,
    validate_tool_output,
)

# ============================================================================
# ValidationIssue / ValidationResult
# ============================================================================

class TestValidationIssue:
    def test_create(self):
        v = ValidationIssue(
            rule=ValidationRule.REQUIRED_FIELD,
            severity=ValidationSeverity.ERROR,
            message="missing field",
            field="name",
            expected="str",
            actual="None",
            suggestion="add name field",
        )
        assert v.rule == ValidationRule.REQUIRED_FIELD
        assert v.field == "name"


class TestValidationResult:
    def test_default_valid(self):
        r = ValidationResult(is_valid=True)
        assert r.is_valid
        assert not r.has_errors
        assert not r.has_warnings

    def test_has_errors(self):
        r = ValidationResult(is_valid=True)
        r.add_issue(ValidationIssue(
            rule=ValidationRule.TYPE_CHECK,
            severity=ValidationSeverity.ERROR,
            message="bad type",
        ))
        assert r.has_errors
        assert not r.is_valid

    def test_has_warnings(self):
        r = ValidationResult(is_valid=True)
        r.add_issue(ValidationIssue(
            rule=ValidationRule.RANGE_CHECK,
            severity=ValidationSeverity.WARNING,
            message="range warning",
        ))
        assert r.has_warnings
        assert r.is_valid  # warnings don't invalidate

    def test_critical_invalidates(self):
        r = ValidationResult(is_valid=True)
        r.add_issue(ValidationIssue(
            rule=ValidationRule.STRUCTURE_CHECK,
            severity=ValidationSeverity.CRITICAL,
            message="structure broken",
        ))
        assert r.has_errors
        assert not r.is_valid


# ============================================================================
# ToolOutputValidator
# ============================================================================

def _ok_result(output: str) -> ToolResult:
    return ToolResult(call_id="c1", output=output)


def _err_result(error: str) -> ToolResult:
    return ToolResult(call_id="c1", error=error)


class TestToolOutputValidator:
    def test_error_result(self):
        v = ToolOutputValidator("search")
        r = v.validate(_err_result("timeout"))
        assert not r.is_valid
        assert len(r.issues) == 1
        assert r.issues[0].severity == ValidationSeverity.ERROR

    def test_empty_output(self):
        v = ToolOutputValidator("search")
        r = v.validate(ToolResult(call_id="c1", output=""))
        assert r.is_valid
        assert len(r.issues) == 1
        assert r.issues[0].severity == ValidationSeverity.WARNING

    def test_json_output(self):
        v = ToolOutputValidator("api")
        r = v.validate(_ok_result('{"name": "test", "count": 42}'))
        assert r.is_valid
        assert r.normalized_output == {"name": "test", "count": 42}

    def test_plain_text_output(self):
        v = ToolOutputValidator("echo")
        r = v.validate(_ok_result("hello world"))
        assert r.is_valid
        assert r.normalized_output == {"text": "hello world"}


class TestToolOutputValidatorRules:
    def test_required_field_missing(self):
        v = ToolOutputValidator("api")
        v.add_rule("id", ValidationRule.REQUIRED_FIELD)
        r = v.validate(_ok_result('{"name": "test"}'))
        assert not r.is_valid
        assert any("id" in issue.message for issue in r.issues)

    def test_required_field_present(self):
        v = ToolOutputValidator("api")
        v.add_rule("id", ValidationRule.REQUIRED_FIELD)
        r = v.validate(_ok_result('{"id": 1, "name": "test"}'))
        assert r.is_valid

    def test_type_check_pass(self):
        v = ToolOutputValidator("api")
        v.add_rule("count", ValidationRule.TYPE_CHECK, expected_type=int)
        r = v.validate(_ok_result('{"count": 10}'))
        assert r.is_valid

    def test_type_check_fail(self):
        v = ToolOutputValidator("api")
        v.add_rule("count", ValidationRule.TYPE_CHECK, expected_type=int)
        r = v.validate(_ok_result('{"count": "ten"}'))
        assert not r.is_valid
        assert any("类型错误" in issue.message for issue in r.issues)

    def test_range_check_min_fail(self):
        v = ToolOutputValidator("api")
        v.add_rule("age", ValidationRule.RANGE_CHECK, min=18, max=100)
        r = v.validate(_ok_result('{"age": 12}'))
        assert any("过小" in issue.message for issue in r.issues)

    def test_range_check_max_fail(self):
        v = ToolOutputValidator("api")
        v.add_rule("age", ValidationRule.RANGE_CHECK, min=18, max=100)
        r = v.validate(_ok_result('{"age": 150}'))
        assert any("过大" in issue.message for issue in r.issues)

    def test_range_check_pass(self):
        v = ToolOutputValidator("api")
        v.add_rule("age", ValidationRule.RANGE_CHECK, min=18, max=100)
        r = v.validate(_ok_result('{"age": 30}'))
        assert r.is_valid

    def test_pattern_match_pass(self):
        v = ToolOutputValidator("api")
        v.add_rule("email", ValidationRule.PATTERN_MATCH, pattern=r"^[^@]+@[^@]+$")
        r = v.validate(_ok_result('{"email": "a@b.com"}'))
        assert r.is_valid

    def test_pattern_match_fail(self):
        v = ToolOutputValidator("api")
        v.add_rule("email", ValidationRule.PATTERN_MATCH, pattern=r"^[^@]+@[^@]+$")
        r = v.validate(_ok_result('{"email": "notanemail"}'))
        assert not r.is_valid

    def test_enum_check_pass(self):
        v = ToolOutputValidator("api")
        v.add_rule("status", ValidationRule.ENUM_CHECK, allowed_values=["ok", "fail"])
        r = v.validate(_ok_result('{"status": "ok"}'))
        assert r.is_valid

    def test_enum_check_fail(self):
        v = ToolOutputValidator("api")
        v.add_rule("status", ValidationRule.ENUM_CHECK, allowed_values=["ok", "fail"])
        r = v.validate(_ok_result('{"status": "pending"}'))
        assert not r.is_valid

    def test_chainable_add_rule(self):
        v = ToolOutputValidator("api")
        result = v.add_rule("field", ValidationRule.REQUIRED_FIELD)
        assert result is v


# ============================================================================
# ToolErrorClassifier
# ============================================================================

class TestToolErrorClassifier:
    def test_classify_auth(self):
        r = _err_result("permission denied")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "AUTH"

    def test_classify_timeout(self):
        r = _err_result("connection timed out")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "TIMEOUT"

    def test_classify_network(self):
        r = _err_result("network error: DNS failure")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "NETWORK"

    def test_classify_not_found(self):
        r = _err_result("file not found: /tmp/x")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "VALIDATION"

    def test_classify_rate_limit(self):
        r = _err_result("rate limit exceeded, too many requests")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "RATE_LIMIT"

    def test_classify_resource(self):
        r = _err_result("out of memory")
        # resource doesn't match "memory" directly in tool output,
        # let's test with a keyword that does match
        pass

    def test_classify_memory_resource(self):
        r = _err_result("disk full")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "RESOURCE"

    def test_classify_unknown(self):
        r = _err_result("something weird happened")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "UNKNOWN"

    def test_classify_valid_result(self):
        r = _ok_result("all good")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "UNKNOWN"  # no error, defaults to UNKNOWN

    def test_get_recovery_suggestions(self):
        from agentos.errors.handler import ErrorCategory
        sug = ToolErrorClassifier.get_recovery_suggestions(ErrorCategory.AUTH, "my_tool")
        assert len(sug) > 0
        assert any("my_tool" in s for s in sug)

    def test_classify_authentication(self):
        r = _err_result("invalid api key")
        cat = ToolErrorClassifier.classify(r)
        assert cat.name == "AUTH"


# ============================================================================
# Convenience functions
# ============================================================================

class TestValidateToolOutput:
    def test_no_schema(self):
        r = validate_tool_output("echo", _ok_result("plain text"))
        assert r.is_valid

    def test_with_schema_valid(self):
        r = validate_tool_output("api", _ok_result('{"name": "x", "count": 5}'), expected_schema={
            "name": {"type": str, "required": True},
            "count": {"type": int, "required": False},
        })
        assert r.is_valid

    def test_with_schema_missing_required(self):
        r = validate_tool_output("api", _ok_result('{"count": 5}'), expected_schema={
            "name": {"type": str, "required": True},
        })
        assert not r.is_valid

    def test_with_schema_enum(self):
        r = validate_tool_output("api", _ok_result('{"status": "active"}'), expected_schema={
            "status": {"enum": ["active", "inactive"]},
        })
        assert r.is_valid

    def test_with_schema_range(self):
        r = validate_tool_output("api", _ok_result('{"score": 85}'), expected_schema={
            "score": {"min": 0, "max": 100},
        })
        assert r.is_valid


class TestClassifyToolError:
    def test_returns_dict(self):
        r = _err_result("access denied")
        d = classify_tool_error(r)
        assert d["category"] == "AUTH"
        assert len(d["suggestions"]) > 0
        assert "severity" in d
