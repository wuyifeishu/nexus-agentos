"""
v1.15.0 — 工具输出验证层：结构化结果验证 + 错误分类 + 自动修复建议。

核心功能：
1. 验证工具返回结果是否符合预期格式
2. 自动分类工具执行错误
3. 提供可操作的修复建议
4. 集成到 ToolExecutor 中，提升 Agent 鲁棒性
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..errors.handler import ErrorCategory
from .base import ToolResult


class ValidationSeverity(StrEnum):
    """验证结果严重性等级。"""

    INFO = "info"  # 信息性提示
    WARNING = "warning"  # 警告，可能有问题但可继续
    ERROR = "error"  # 错误，需要修复
    CRITICAL = "critical"  # 严重错误，必须修复


class ValidationRule(StrEnum):
    """验证规则类型。"""

    JSON_FORMAT = "json_format"  # JSON 格式验证
    REQUIRED_FIELD = "required_field"  # 必需字段检查
    TYPE_CHECK = "type_check"  # 类型检查
    RANGE_CHECK = "range_check"  # 范围检查
    PATTERN_MATCH = "pattern_match"  # 正则匹配
    LENGTH_CHECK = "length_check"  # 长度检查
    ENUM_CHECK = "enum_check"  # 枚举值检查
    STRUCTURE_CHECK = "structure_check"  # 结构检查


@dataclass
class ValidationIssue:
    """验证问题。"""

    rule: ValidationRule
    severity: ValidationSeverity
    message: str
    field: str | None = None
    expected: Any | None = None
    actual: Any | None = None
    suggestion: str = ""


@dataclass
class ValidationResult:
    """验证结果。"""

    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    normalized_output: Any | None = None

    @property
    def has_errors(self) -> bool:
        return any(
            issue.severity in (ValidationSeverity.ERROR, ValidationSeverity.CRITICAL)
            for issue in self.issues
        )

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity == ValidationSeverity.WARNING for issue in self.issues)

    def add_issue(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)
        if issue.severity in (ValidationSeverity.ERROR, ValidationSeverity.CRITICAL):
            self.is_valid = False


class ToolOutputValidator:
    """工具输出验证器。"""

    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        self._rules: dict[str, list[ValidationRule]] = {}
        self._field_schemas: dict[str, dict] = {}

    def add_rule(self, field: str, rule: ValidationRule, **kwargs) -> ToolOutputValidator:
        """为指定字段添加验证规则。"""
        if field not in self._rules:
            self._rules[field] = []
        self._rules[field].append(rule)

        if rule == ValidationRule.TYPE_CHECK:
            self._field_schemas.setdefault(field, {})["type"] = kwargs.get("expected_type")
        elif rule == ValidationRule.RANGE_CHECK:
            entry = self._field_schemas.setdefault(field, {})
            if kwargs.get("min") is not None:
                entry["min"] = kwargs["min"]
            if kwargs.get("max") is not None:
                entry["max"] = kwargs["max"]
        elif rule == ValidationRule.PATTERN_MATCH:
            self._field_schemas.setdefault(field, {})["pattern"] = kwargs.get("pattern")
        elif rule == ValidationRule.ENUM_CHECK:
            self._field_schemas.setdefault(field, {})["allowed_values"] = kwargs.get("allowed_values")

        return self

    def validate(self, tool_result: ToolResult) -> ValidationResult:
        """验证工具结果。"""
        result = ValidationResult(is_valid=True)

        # 检查工具执行是否成功
        if tool_result.error:
            result.add_issue(
                ValidationIssue(
                    rule=ValidationRule.REQUIRED_FIELD,
                    severity=ValidationSeverity.ERROR,
                    message=f"工具执行失败: {tool_result.error}",
                    suggestion="请检查工具参数和依赖环境",
                )
            )
            return result

        if not tool_result.output:
            result.add_issue(
                ValidationIssue(
                    rule=ValidationRule.REQUIRED_FIELD,
                    severity=ValidationSeverity.WARNING,
                    message="工具返回空输出",
                    suggestion="检查工具是否按预期工作",
                )
            )
            return result

        # 尝试解析输出
        parsed_output = self._parse_output(tool_result.output)
        if isinstance(parsed_output, ValidationIssue):
            result.add_issue(parsed_output)
            return result

        result.normalized_output = parsed_output

        # 应用验证规则
        self._apply_rules(result, parsed_output)

        return result

    def _parse_output(self, output: str) -> Any | ValidationIssue:
        """解析工具输出。"""
        # 尝试解析为 JSON
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass

        # 尝试解析为 Python 字典格式（如 "{'key': 'value'}"）
        try:
            # 安全地使用 eval 但限制为字面量
            import ast

            return ast.literal_eval(output)
        except (SyntaxError, ValueError):
            pass

        # 检查是否为纯文本
        if output.strip():
            return {"text": output.strip()}

        return ValidationIssue(
            rule=ValidationRule.JSON_FORMAT,
            severity=ValidationSeverity.ERROR,
            message="无法解析工具输出",
            actual=output[:100] if output else "空字符串",
            suggestion="工具应返回 JSON 或结构化文本",
        )

    def _apply_rules(self, result: ValidationResult, data: Any) -> None:
        """应用验证规则到数据。"""
        if not isinstance(data, dict):
            return

        for fname, rules in self._rules.items():
            if fname not in data:
                if ValidationRule.REQUIRED_FIELD in rules:
                    result.add_issue(
                        ValidationIssue(
                            rule=ValidationRule.REQUIRED_FIELD,
                            severity=ValidationSeverity.ERROR,
                            message=f"缺少必需字段: {fname}",
                            field=fname,
                            suggestion=f"工具应返回字段 '{fname}'",
                        )
                    )
                continue

            value = data[fname]

            for rule in rules:
                if rule == ValidationRule.TYPE_CHECK:
                    expected_type = self._field_schemas[fname]["type"]
                    if not isinstance(value, expected_type):
                        result.add_issue(
                            ValidationIssue(
                                rule=ValidationRule.TYPE_CHECK,
                                severity=ValidationSeverity.ERROR,
                                message=f"字段类型错误: {fname}",
                                field=fname,
                                expected=expected_type.__name__,
                                actual=type(value).__name__,
                                suggestion=f"字段 '{fname}' 应为 {expected_type.__name__} 类型",
                            )
                        )

                elif rule == ValidationRule.RANGE_CHECK:
                    schema = self._field_schemas[fname]
                    if "min" in schema and schema["min"] is not None and value < schema["min"]:
                        result.add_issue(
                            ValidationIssue(
                                rule=ValidationRule.RANGE_CHECK,
                                severity=ValidationSeverity.WARNING,
                                message=f"字段值过小: {fname}",
                                field=fname,
                                expected=f">= {schema['min']}",
                                actual=value,
                                suggestion=f"字段 '{fname}' 应大于等于 {schema['min']}",
                            )
                        )
                    if "max" in schema and schema["max"] is not None and value > schema["max"]:
                        result.add_issue(
                            ValidationIssue(
                                rule=ValidationRule.RANGE_CHECK,
                                severity=ValidationSeverity.WARNING,
                                message=f"字段值过大: {fname}",
                                field=fname,
                                expected=f"<= {schema['max']}",
                                actual=value,
                                suggestion=f"字段 '{fname}' 应小于等于 {schema['max']}",
                            )
                        )

                elif rule == ValidationRule.PATTERN_MATCH:
                    pattern = self._field_schemas[fname]["pattern"]
                    if not re.match(pattern, str(value)):
                        result.add_issue(
                            ValidationIssue(
                                rule=ValidationRule.PATTERN_MATCH,
                                severity=ValidationSeverity.ERROR,
                                message=f"字段格式错误: {fname}",
                                field=fname,
                                expected=f"匹配模式: {pattern}",
                                actual=value,
                                suggestion=f"字段 '{fname}' 应符合正则表达式: {pattern}",
                            )
                        )

                elif rule == ValidationRule.ENUM_CHECK:
                    allowed = self._field_schemas[fname]["allowed_values"]
                    if value not in allowed:
                        result.add_issue(
                            ValidationIssue(
                                rule=ValidationRule.ENUM_CHECK,
                                severity=ValidationSeverity.ERROR,
                                message=f"字段值不在允许范围内: {fname}",
                                field=fname,
                                expected=allowed,
                                actual=value,
                                suggestion=f"字段 '{fname}' 应为以下值之一: {allowed}",
                            )
                        )


class ToolErrorClassifier:
    """工具错误分类器。"""

    @staticmethod
    def classify(tool_result: ToolResult) -> ErrorCategory:
        """根据工具结果分类错误。"""
        if tool_result.error:
            error_msg = tool_result.error.lower()

            if any(kw in error_msg for kw in ["permission", "access denied", "forbidden"]):
                return ErrorCategory.AUTH
            elif any(kw in error_msg for kw in ["timeout", "timed out"]):
                return ErrorCategory.TIMEOUT
            elif any(kw in error_msg for kw in ["network", "connection", "dns"]):
                return ErrorCategory.NETWORK
            elif any(kw in error_msg for kw in ["not found", "file not found", "no such file"]):
                return ErrorCategory.VALIDATION
            elif any(
                kw in error_msg
                for kw in ["authentication", "auth", "api key", "invalid key", "unauthorized"]
            ):
                return ErrorCategory.AUTH
            elif any(kw in error_msg for kw in ["memory", "disk", "resource"]):
                return ErrorCategory.RESOURCE
            elif any(kw in error_msg for kw in ["syntax", "invalid", "malformed"]):
                return ErrorCategory.VALIDATION
            elif any(kw in error_msg for kw in ["rate limit", "too many", "quota"]):
                return ErrorCategory.RATE_LIMIT

        return ErrorCategory.UNKNOWN

    @staticmethod
    def get_recovery_suggestions(category: ErrorCategory, tool_name: str) -> list[str]:
        """获取针对特定工具的错误恢复建议。"""
        base_suggestions = {
            ErrorCategory.AUTH: [
                f"检查 {tool_name} 工具所需的权限",
                "确认当前用户有足够的访问权限",
                "检查 API Key 或认证令牌是否有效",
            ],
            ErrorCategory.TIMEOUT: [
                f"增加 {tool_name} 工具的超时时间",
                "检查目标服务是否正常运行",
                "考虑使用更轻量的查询参数",
            ],
            ErrorCategory.NETWORK: [
                "检查网络连接",
                "确认目标服务地址是否正确",
                "尝试使用代理或 VPN",
            ],
            ErrorCategory.VALIDATION: [
                f"检查 {tool_name} 工具的输入参数",
                "确认文件路径或资源是否存在",
                "验证输入数据的格式和类型",
            ],
            ErrorCategory.RESOURCE: ["清理磁盘空间", "增加系统内存", "减少并发请求数量"],
            ErrorCategory.RATE_LIMIT: ["降低请求频率", "使用指数退避重试", "检查 API 配额限制"],
            ErrorCategory.UNKNOWN: [
                f"查看 {tool_name} 工具的详细日志",
                "检查工具依赖是否完整",
                "尝试重启相关服务",
            ],
        }

        return base_suggestions.get(category, ["请查看详细错误信息"])


def validate_tool_output(
    tool_name: str, tool_result: ToolResult, expected_schema: dict | None = None
) -> ValidationResult:
    """
    验证工具输出的便捷函数。

    Args:
        tool_name: 工具名称
        tool_result: 工具执行结果
        expected_schema: 期望的输出模式（可选）

    Returns:
        ValidationResult: 验证结果
    """
    validator = ToolOutputValidator(tool_name)

    if expected_schema:
        for field, schema in expected_schema.items():
            if "type" in schema:
                validator.add_rule(field, ValidationRule.TYPE_CHECK, expected_type=schema["type"])
            if "required" in schema and schema["required"]:
                validator.add_rule(field, ValidationRule.REQUIRED_FIELD)
            if "pattern" in schema:
                validator.add_rule(field, ValidationRule.PATTERN_MATCH, pattern=schema["pattern"])
            if "enum" in schema:
                validator.add_rule(field, ValidationRule.ENUM_CHECK, allowed_values=schema["enum"])
            if "min" in schema or "max" in schema:
                validator.add_rule(
                    field, ValidationRule.RANGE_CHECK, min=schema.get("min"), max=schema.get("max")
                )

    return validator.validate(tool_result)


def classify_tool_error(tool_result: ToolResult) -> dict[str, Any]:
    """
    分类工具错误并返回结构化信息。

    Args:
        tool_result: 工具执行结果

    Returns:
        Dict: 包含错误分类和恢复建议的字典
    """
    category = ToolErrorClassifier.classify(tool_result)
    suggestions = ToolErrorClassifier.get_recovery_suggestions(category, "unknown")

    return {
        "category": category.name,
        "error_message": tool_result.error,
        "suggestions": suggestions,
        "severity": "error" if category != ErrorCategory.UNKNOWN else "warning",
    }
