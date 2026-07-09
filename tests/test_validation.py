"""Tests for agentos.tools.validation — ToolOutputValidator, ToolErrorClassifier."""

import pytest

from agentos.errors.handler import ErrorCategory
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


class TestValidationSeverity:
    def test_values(self):
        assert ValidationSeverity.INFO == "info"
        assert ValidationSeverity.WARNING == "warning"
        assert ValidationSeverity.ERROR == "error"
        assert ValidationSeverity.CRITICAL == "critical"


class TestValidationIssue:
    def test_create(self):
        issue = ValidationIssue(
            rule=ValidationRule.JSON_FORMAT,
            severity=ValidationSeverity.ERROR,
            message="bad json",
            field="data",
            expected="{}",
            actual="[",
            suggestion="fix json",
        )
        assert issue.rule == ValidationRule.JSON_FORMAT
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.field == "data"
        assert issue.expected == "{}"
        assert issue.actual == "["
        assert issue.suggestion == "fix json"

    def test_defaults(self):
        issue = ValidationIssue(rule=ValidationRule.REQUIRED_FIELD, severity=ValidationSeverity.WARNING, message="x")
        assert issue.field is None
        assert issue.expected is None
        assert issue.actual is None
        assert issue.suggestion == ""


class TestValidationResult:
    def test_valid_default(self):
        r = ValidationResult(is_valid=True)
        assert r.is_valid is True
        assert r.has_errors is False
        assert r.has_warnings is False

    def test_add_error_makes_invalid(self):
        r = ValidationResult(is_valid=True)
        issue = ValidationIssue(rule=ValidationRule.TYPE_CHECK, severity=ValidationSeverity.ERROR, message="type err")
        r.add_issue(issue)
        assert r.is_valid is False
        assert r.has_errors is True

    def test_add_critical_makes_invalid(self):
        r = ValidationResult(is_valid=True)
        r.add_issue(ValidationIssue(rule=ValidationRule.JSON_FORMAT, severity=ValidationSeverity.CRITICAL, message="x"))
        assert r.is_valid is False

    def test_warning_keeps_valid(self):
        r = ValidationResult(is_valid=True)
        r.add_issue(ValidationIssue(rule=ValidationRule.LENGTH_CHECK, severity=ValidationSeverity.WARNING, message="x"))
        assert r.is_valid is True
        assert r.has_warnings is True

    def test_normalized_output(self):
        r = ValidationResult(is_valid=True, normalized_output={"key": "val"})
        assert r.normalized_output == {"key": "val"}


class TestToolOutputValidator:
    def test_add_rule_chain(self):
        v = ToolOutputValidator("test")
        v2 = v.add_rule("name", ValidationRule.TYPE_CHECK, expected_type=str)
        assert v2 is v

    def test_validate_error_result(self):
        v = ToolOutputValidator("test")
        result = ToolResult.fail("call1", error="something went wrong")
        vr = v.validate(result)
        assert vr.is_valid is False
        assert len(vr.issues) == 1
        assert "工具执行失败" in vr.issues[0].message

    def test_validate_empty_output(self):
        v = ToolOutputValidator("test")
        result = ToolResult.ok("call1", output="")
        vr = v.validate(result)
        assert vr.is_valid is True
        assert any("空输出" in i.message for i in vr.issues)

    def test_validate_json_output(self):
        v = ToolOutputValidator("test")
        result = ToolResult.ok("call1", output='{"name": "marvis", "score": 100}')
        vr = v.validate(result)
        assert vr.is_valid is True
        assert vr.normalized_output == {"name": "marvis", "score": 100}

    def test_validate_plain_text(self):
        v = ToolOutputValidator("test")
        result = ToolResult.ok("call1", output="hello world")
        vr = v.validate(result)
        assert vr.is_valid is True
        assert vr.normalized_output == {"text": "hello world"}

    def test_validate_python_dict_format(self):
        v = ToolOutputValidator("test")
        result = ToolResult.ok("call1", output="{'key': 'value'}")
        vr = v.validate(result)
        assert vr.normalized_output == {"key": "value"}

    def test_type_check_rule_pass(self):
        v = ToolOutputValidator("test")
        v.add_rule("count", ValidationRule.TYPE_CHECK, expected_type=int)
        result = ToolResult.ok("call1", output='{"count": 42}')
        vr = v.validate(result)
        assert vr.is_valid is True

    def test_type_check_rule_fail(self):
        v = ToolOutputValidator("test")
        v.add_rule("count", ValidationRule.TYPE_CHECK, expected_type=int)
        result = ToolResult.ok("call1", output='{"count": "abc"}')
        vr = v.validate(result)
        assert vr.is_valid is False
        assert any("类型错误" in i.message for i in vr.issues)

    def test_range_check_min(self):
        v = ToolOutputValidator("test")
        v.add_rule("age", ValidationRule.RANGE_CHECK, min=0)
        result = ToolResult.ok("call1", output='{"age": -5}')
        vr = v.validate(result)
        assert any("过小" in i.message for i in vr.issues)

    def test_range_check_max(self):
        v = ToolOutputValidator("test")
        v.add_rule("age", ValidationRule.RANGE_CHECK, max=150)
        result = ToolResult.ok("call1", output='{"age": 999}')
        vr = v.validate(result)
        assert any("过大" in i.message for i in vr.issues)

    def test_range_check_ok(self):
        v = ToolOutputValidator("test")
        v.add_rule("age", ValidationRule.RANGE_CHECK, min=0, max=150)
        result = ToolResult.ok("call1", output='{"age": 30}')
        vr = v.validate(result)
        assert vr.is_valid is True

    def test_pattern_match_pass(self):
        v = ToolOutputValidator("test")
        v.add_rule("email", ValidationRule.PATTERN_MATCH, pattern=r".+@.+\..+")
        result = ToolResult.ok("call1", output='{"email": "a@b.com"}')
        vr = v.validate(result)
        assert vr.is_valid is True

    def test_pattern_match_fail(self):
        v = ToolOutputValidator("test")
        v.add_rule("email", ValidationRule.PATTERN_MATCH, pattern=r".+@.+\..+")
        result = ToolResult.ok("call1", output='{"email": "notanemail"}')
        vr = v.validate(result)
        assert any("格式错误" in i.message for i in vr.issues)

    def test_enum_check_pass(self):
        v = ToolOutputValidator("test")
        v.add_rule("status", ValidationRule.ENUM_CHECK, allowed_values=["active", "inactive"])
        result = ToolResult.ok("call1", output='{"status": "active"}')
        vr = v.validate(result)
        assert vr.is_valid is True

    def test_enum_check_fail(self):
        v = ToolOutputValidator("test")
        v.add_rule("status", ValidationRule.ENUM_CHECK, allowed_values=["active", "inactive"])
        result = ToolResult.ok("call1", output='{"status": "deleted"}')
        vr = v.validate(result)
        assert any("不在允许范围" in i.message for i in vr.issues)

    def test_required_field_missing(self):
        v = ToolOutputValidator("test")
        v.add_rule("name", ValidationRule.REQUIRED_FIELD)
        result = ToolResult.ok("call1", output='{"other": "val"}')
        vr = v.validate(result)
        assert any("缺少必需字段" in i.message for i in vr.issues)

    def test_multiple_rules(self):
        v = ToolOutputValidator("test")
        v.add_rule("count", ValidationRule.TYPE_CHECK, expected_type=int)
        v.add_rule("count", ValidationRule.RANGE_CHECK, min=0, max=100)
        result = ToolResult.ok("call1", output='{"count": 50}')
        vr = v.validate(result)
        assert vr.is_valid is True


class TestToolErrorClassifier:
    @pytest.mark.parametrize("error_msg,category", [
        ("permission denied", ErrorCategory.AUTH),
        ("access denied", ErrorCategory.AUTH),
        ("forbidden", ErrorCategory.AUTH),
        ("timeout", ErrorCategory.TIMEOUT),
        ("timed out", ErrorCategory.TIMEOUT),
        ("network error", ErrorCategory.NETWORK),
        ("connection refused", ErrorCategory.NETWORK),
        ("dns failure", ErrorCategory.NETWORK),
        ("not found", ErrorCategory.VALIDATION),
        ("file not found", ErrorCategory.VALIDATION),
        ("no such file", ErrorCategory.VALIDATION),
        ("authentication failed", ErrorCategory.AUTH),
        ("auth required", ErrorCategory.AUTH),
        ("api key invalid", ErrorCategory.AUTH),
        ("invalid key", ErrorCategory.AUTH),
        ("unauthorized", ErrorCategory.AUTH),
        ("memory exhausted", ErrorCategory.RESOURCE),
        ("disk full", ErrorCategory.RESOURCE),
        ("resource limit", ErrorCategory.RESOURCE),
        ("syntax error", ErrorCategory.VALIDATION),
        ("invalid input", ErrorCategory.VALIDATION),
        ("malformed", ErrorCategory.VALIDATION),
        ("rate limit exceeded", ErrorCategory.RATE_LIMIT),
        ("too many requests", ErrorCategory.RATE_LIMIT),
        ("quota exceeded", ErrorCategory.RATE_LIMIT),
    ])
    def test_classify(self, error_msg, category):
        result = ToolResult.fail("c1", error=error_msg)
        assert ToolErrorClassifier.classify(result) == category

    def test_classify_no_error(self):
        result = ToolResult.ok("c1", output="all good")
        assert ToolErrorClassifier.classify(result) == ErrorCategory.UNKNOWN

    def test_get_recovery_suggestions_auth(self):
        suggestions = ToolErrorClassifier.get_recovery_suggestions(ErrorCategory.AUTH, "login_tool")
        assert len(suggestions) > 0
        assert any("login_tool" in s for s in suggestions)

    def test_get_recovery_suggestions_timeout(self):
        suggestions = ToolErrorClassifier.get_recovery_suggestions(ErrorCategory.TIMEOUT, "search")
        assert len(suggestions) > 0
        assert any("search" in s or "超时" in s for s in suggestions)

    def test_get_recovery_suggestions_unknown(self):
        suggestions = ToolErrorClassifier.get_recovery_suggestions(ErrorCategory.UNKNOWN, "x")
        assert len(suggestions) > 0


class TestValidateToolOutput:
    def test_without_schema(self):
        result = ToolResult.ok("c1", output='{"ok": true}')
        vr = validate_tool_output("test", result)
        assert vr.is_valid is True

    def test_with_schema(self):
        schema = {"name": {"type": str, "required": True}}
        result = ToolResult.ok("c1", output='{"name": "marvis"}')
        vr = validate_tool_output("test", result, expected_schema=schema)
        assert vr.is_valid is True

    def test_with_schema_missing_required(self):
        schema = {"name": {"type": str, "required": True}}
        result = ToolResult.ok("c1", output='{"other": "x"}')
        vr = validate_tool_output("test", result, expected_schema=schema)
        assert vr.is_valid is False

    def test_with_schema_pattern(self):
        schema = {"email": {"pattern": r".+@.+"}}
        result = ToolResult.ok("c1", output='{"email": "badmail"}')
        vr = validate_tool_output("test", result, expected_schema=schema)
        assert any("格式错误" in i.message for i in vr.issues)

    def test_with_schema_enum(self):
        schema = {"color": {"enum": ["red", "blue"]}}
        result = ToolResult.ok("c1", output='{"color": "green"}')
        vr = validate_tool_output("test", result, expected_schema=schema)
        assert any("不在允许范围" in i.message for i in vr.issues)

    def test_with_schema_range(self):
        schema = {"score": {"min": 0, "max": 100}}
        result = ToolResult.ok("c1", output='{"score": 150}')
        vr = validate_tool_output("test", result, expected_schema=schema)
        assert any("过大" in i.message for i in vr.issues)


class TestClassifyToolError:
    def test_returns_dict(self):
        result = ToolResult.fail("c1", error="timeout")
        info = classify_tool_error(result)
        assert info["category"] == ErrorCategory.TIMEOUT.name
        assert info["error_message"] == "timeout"
        assert len(info["suggestions"]) > 0

    def test_unknown_returns_warning(self):
        result = ToolResult.ok("c1", output="fine")
        info = classify_tool_error(result)
        assert info["severity"] == "warning"
