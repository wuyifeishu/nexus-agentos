"""
测试 v1.15.0 工具输出验证层。
"""

import json

import pytest

from agentos.errors.handler import ErrorCategory
from agentos.tools.base import ToolResult
from agentos.tools.validation import (
    ToolErrorClassifier,
    ToolOutputValidator,
    ValidationRule,
    ValidationSeverity,
    classify_tool_error,
    validate_tool_output,
)


class TestToolOutputValidator:
    """测试工具输出验证器。"""

    def test_validate_successful_result(self):
        """测试验证成功的工具结果。"""
        tool_result = ToolResult.ok(
            call_id="test-123",
            output=json.dumps({"name": "test", "count": 42, "status": "active"})
        )

        validator = ToolOutputValidator("test_tool")
        validator.add_rule("name", ValidationRule.REQUIRED_FIELD)
        validator.add_rule("count", ValidationRule.TYPE_CHECK, expected_type=int)
        validator.add_rule("status", ValidationRule.ENUM_CHECK,
                          allowed_values=["active", "inactive", "pending"])

        result = validator.validate(tool_result)

        assert result.is_valid
        assert len(result.issues) == 0
        assert result.normalized_output == {"name": "test", "count": 42, "status": "active"}

    def test_validate_failed_tool(self):
        """测试验证失败的工具结果。"""
        tool_result = ToolResult.fail(
            call_id="test-456",
            error="Permission denied: cannot access /root/file.txt"
        )

        validator = ToolOutputValidator("test_tool")
        result = validator.validate(tool_result)

        assert not result.is_valid
        assert len(result.issues) == 1
        assert result.issues[0].severity == ValidationSeverity.ERROR
        assert "工具执行失败" in result.issues[0].message

    def test_validate_empty_output(self):
        """测试验证空输出。"""
        tool_result = ToolResult.ok(call_id="test-789", output="")

        validator = ToolOutputValidator("test_tool")
        result = validator.validate(tool_result)

        assert result.is_valid  # 空输出是警告，不是错误
        assert len(result.issues) == 1
        assert result.issues[0].severity == ValidationSeverity.WARNING
        assert "工具返回空输出" in result.issues[0].message

    def test_validate_missing_required_field(self):
        """测试验证缺少必需字段。"""
        tool_result = ToolResult.ok(
            call_id="test-999",
            output=json.dumps({"count": 42})  # 缺少 name 字段
        )

        validator = ToolOutputValidator("test_tool")
        validator.add_rule("name", ValidationRule.REQUIRED_FIELD)
        validator.add_rule("count", ValidationRule.TYPE_CHECK, expected_type=int)

        result = validator.validate(tool_result)

        assert not result.is_valid
        assert len(result.issues) == 1
        assert result.issues[0].rule == ValidationRule.REQUIRED_FIELD
        assert "缺少必需字段" in result.issues[0].message

    def test_validate_type_mismatch(self):
        """测试验证类型不匹配。"""
        tool_result = ToolResult.ok(
            call_id="test-111",
            output=json.dumps({"count": "42"})  # 应该是 int
        )

        validator = ToolOutputValidator("test_tool")
        validator.add_rule("count", ValidationRule.TYPE_CHECK, expected_type=int)

        result = validator.validate(tool_result)

        assert not result.is_valid
        assert len(result.issues) == 1
        assert result.issues[0].rule == ValidationRule.TYPE_CHECK
        assert "字段类型错误" in result.issues[0].message

    def test_validate_enum_violation(self):
        """测试验证枚举值违规。"""
        tool_result = ToolResult.ok(
            call_id="test-222",
            output=json.dumps({"status": "unknown"})  # 不在允许范围内
        )

        validator = ToolOutputValidator("test_tool")
        validator.add_rule("status", ValidationRule.ENUM_CHECK,
                          allowed_values=["active", "inactive"])

        result = validator.validate(tool_result)

        assert not result.is_valid
        assert len(result.issues) == 1
        assert result.issues[0].rule == ValidationRule.ENUM_CHECK
        assert "字段值不在允许范围内" in result.issues[0].message

    def test_validate_range_check(self):
        """测试验证范围检查。"""
        tool_result = ToolResult.ok(
            call_id="test-333",
            output=json.dumps({"score": 150})  # 超过最大值
        )

        validator = ToolOutputValidator("test_tool")
        validator.add_rule("score", ValidationRule.RANGE_CHECK, min=0, max=100)

        result = validator.validate(tool_result)

        assert result.is_valid  # 范围检查是警告，不是错误
        assert len(result.issues) == 1
        assert result.issues[0].severity == ValidationSeverity.WARNING
        assert "字段值过大" in result.issues[0].message

    def test_validate_pattern_match(self):
        """测试验证正则匹配。"""
        tool_result = ToolResult.ok(
            call_id="test-444",
            output=json.dumps({"email": "invalid-email"})  # 无效邮箱格式
        )

        validator = ToolOutputValidator("test_tool")
        validator.add_rule("email", ValidationRule.PATTERN_MATCH,
                          pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

        result = validator.validate(tool_result)

        assert not result.is_valid
        assert len(result.issues) == 1
        assert result.issues[0].rule == ValidationRule.PATTERN_MATCH
        assert "字段格式错误" in result.issues[0].message

    def test_validate_non_json_output(self):
        """测试验证非 JSON 输出。"""
        tool_result = ToolResult.ok(
            call_id="test-555",
            output="This is a plain text response"
        )

        validator = ToolOutputValidator("test_tool")
        result = validator.validate(tool_result)

        assert result.is_valid
        assert result.normalized_output == {"text": "This is a plain text response"}

    def test_validate_invalid_json(self):
        """测试验证无效 JSON。"""
        tool_result = ToolResult.ok(
            call_id="test-666",
            output="{invalid json"
        )

        validator = ToolOutputValidator("test_tool")
        result = validator.validate(tool_result)

        assert result.is_valid  # 非 JSON 会尝试其他解析方式
        assert result.normalized_output == {"text": "{invalid json"}


class TestToolErrorClassifier:
    """测试工具错误分类器。"""

    def test_classify_auth_error(self):
        """测试分类认证错误。"""
        tool_result = ToolResult.fail(
            call_id="test-auth",
            error="Permission denied: cannot write to /etc/config"
        )

        category = ToolErrorClassifier.classify(tool_result)
        assert category == ErrorCategory.AUTH

        suggestions = ToolErrorClassifier.get_recovery_suggestions(category, "write_tool")
        assert len(suggestions) > 0
        assert any("权限" in s or "Permission" in s for s in suggestions)

    def test_classify_timeout_error(self):
        """测试分类超时错误。"""
        tool_result = ToolResult.fail(
            call_id="test-timeout",
            error="Request timed out after 30 seconds"
        )

        category = ToolErrorClassifier.classify(tool_result)
        assert category == ErrorCategory.TIMEOUT

        suggestions = ToolErrorClassifier.get_recovery_suggestions(category, "api_tool")
        assert any("超时" in s or "timeout" in s for s in suggestions)

    def test_classify_network_error(self):
        """测试分类网络错误。"""
        tool_result = ToolResult.fail(
            call_id="test-network",
            error="Network unreachable: failed to connect to api.example.com"
        )

        category = ToolErrorClassifier.classify(tool_result)
        assert category == ErrorCategory.NETWORK

        suggestions = ToolErrorClassifier.get_recovery_suggestions(category, "http_tool")
        assert any("网络" in s or "network" in s for s in suggestions)

    def test_classify_validation_error(self):
        """测试分类验证错误。"""
        tool_result = ToolResult.fail(
            call_id="test-validation",
            error="File not found: /path/to/nonexistent/file.txt"
        )

        category = ToolErrorClassifier.classify(tool_result)
        assert category == ErrorCategory.VALIDATION

        suggestions = ToolErrorClassifier.get_recovery_suggestions(category, "file_tool")
        assert any("检查" in s or "check" in s for s in suggestions)

    def test_classify_resource_error(self):
        """测试分类资源错误。"""
        tool_result = ToolResult.fail(
            call_id="test-resource",
            error="Out of memory: cannot allocate 4GB buffer"
        )

        category = ToolErrorClassifier.classify(tool_result)
        assert category == ErrorCategory.RESOURCE

        suggestions = ToolErrorClassifier.get_recovery_suggestions(category, "memory_tool")
        assert any("内存" in s or "memory" in s for s in suggestions)

    def test_classify_rate_limit_error(self):
        """测试分类限流错误。"""
        tool_result = ToolResult.fail(
            call_id="test-rate-limit",
            error="Rate limit exceeded: 100 requests per minute"
        )

        category = ToolErrorClassifier.classify(tool_result)
        assert category == ErrorCategory.RATE_LIMIT

        suggestions = ToolErrorClassifier.get_recovery_suggestions(category, "api_tool")
        assert any("频率" in s or "rate" in s for s in suggestions)

    def test_classify_unknown_error(self):
        """测试分类未知错误。"""
        tool_result = ToolResult.fail(
            call_id="test-unknown",
            error="Some weird error that doesn't match any pattern"
        )

        category = ToolErrorClassifier.classify(tool_result)
        assert category == ErrorCategory.UNKNOWN

        suggestions = ToolErrorClassifier.get_recovery_suggestions(category, "mystery_tool")
        assert len(suggestions) > 0


class TestConvenienceFunctions:
    """测试便捷函数。"""

    def test_validate_tool_output_with_schema(self):
        """测试带模式的验证函数。"""
        tool_result = ToolResult.ok(
            call_id="test-schema",
            output=json.dumps({"id": 123, "name": "test", "active": True})
        )

        expected_schema = {
            "id": {"type": int, "required": True},
            "name": {"type": str, "required": True},
            "active": {"type": bool, "required": False},
            "score": {"type": float, "required": False},  # 缺失，但非必需
        }

        result = validate_tool_output("test_tool", tool_result, expected_schema)

        assert result.is_valid
        assert result.normalized_output["id"] == 123
        assert result.normalized_output["name"] == "test"
        assert result.normalized_output["active"] is True

    def test_classify_tool_error_function(self):
        """测试分类工具错误函数。"""
        tool_result = ToolResult.fail(
            call_id="test-classify",
            error="Authentication failed: invalid API key"
        )

        error_info = classify_tool_error(tool_result)

        assert "category" in error_info
        assert "error_message" in error_info
        assert "suggestions" in error_info
        assert "severity" in error_info
        assert error_info["category"] == "AUTH"
        assert error_info["severity"] == "error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
