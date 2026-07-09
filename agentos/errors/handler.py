"""v0.80 — 用户友好错误处理：分类 + 格式化 + 建议。"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass, field
from enum import Enum, auto


class ErrorCategory(Enum):
    """错误分类枚举。"""

    NETWORK = auto()  # 网络/API 调用失败
    AUTH = auto()  # 认证/API Key 问题
    CONFIG = auto()  # 配置错误
    RATE_LIMIT = auto()  # 限流/配额
    VALIDATION = auto()  # 输入验证
    TIMEOUT = auto()  # 超时
    RESOURCE = auto()  # 资源不足（内存/磁盘）
    MODEL = auto()  # 模型相关
    PLUGIN = auto()  # 插件错误
    INTERNAL = auto()  # 内部错误
    UNKNOWN = auto()  # 未分类


CATEGORY_HINTS = {
    ErrorCategory.NETWORK: "请检查网络连接或 API 端点地址。",
    ErrorCategory.AUTH: "请确认 API Key 是否正确设置（环境变量或配置文件）。",
    ErrorCategory.CONFIG: "请检查 agentos.yaml 配置文件，确保字段拼写正确。",
    ErrorCategory.RATE_LIMIT: "请求频率过高，请稍后重试。可调整 RateLimitCfg.max_rps。",
    ErrorCategory.VALIDATION: "输入参数不符合预期格式，请参考文档修正。",
    ErrorCategory.TIMEOUT: "操作超时。可增大 LoopCfg.step_timeout 或 ModelConfig.timeout。",
    ErrorCategory.RESOURCE: "系统资源不足，请检查内存/磁盘或降低并发。",
    ErrorCategory.MODEL: "模型返回异常或调用失败，可尝试切换备用 Provider。",
    ErrorCategory.PLUGIN: "插件加载失败，请检查插件路径和依赖。",
    ErrorCategory.INTERNAL: "内部错误，请联系开发者并提供 trace_id。",
    ErrorCategory.UNKNOWN: "未知错误，请查看详细日志。",
}


@dataclass
class ErrorContext:
    """错误上下文信息。"""

    trace_id: str = ""
    category: ErrorCategory = ErrorCategory.UNKNOWN
    message: str = ""
    suggestion: str = ""
    detail: str = ""
    recovery_actions: list[str] = field(default_factory=list)


class HumanError(Exception):
    """包装原始异常，附带用户友好的上下文。"""

    def __init__(self, original: Exception, context: ErrorContext):
        super().__init__(str(original))
        self.original = original
        self.context = context

    def __str__(self) -> str:
        return self.context.message or super().__str__()


class ErrorFormatter:
    """将 Python 异常转换为用户友好的格式化输出。"""

    @staticmethod
    def categorize(exc: Exception) -> ErrorCategory:
        """根据异常类型和消息自动分类。"""
        msg = str(exc).lower()
        type_name = type(exc).__name__.lower()

        if any(kw in msg for kw in ["timeout", "timed out", "connect timeout"]):
            return ErrorCategory.TIMEOUT
        if any(kw in msg for kw in ["rate limit", "too many requests", "429"]):
            return ErrorCategory.RATE_LIMIT
        if any(
            kw in msg
            for kw in ["unauthorized", "forbidden", "401", "403", "api key", "invalid key"]
        ):
            return ErrorCategory.AUTH
        if any(kw in msg for kw in ["connection", "network", "dns", "refused", "unreachable"]):
            return ErrorCategory.NETWORK
        if any(
            kw in msg for kw in ["validation", "invalid", "expected", "type error", "value error"]
        ):
            return ErrorCategory.VALIDATION
        if any(kw in msg for kw in ["memory", "disk", "quota", "out of"]):
            return ErrorCategory.RESOURCE
        if any(kw in type_name for kw in ["plugin", "load"]):
            return ErrorCategory.PLUGIN
        if any(kw in msg for kw in ["config", "cfg", "yaml"]):
            return ErrorCategory.CONFIG
        if any(kw in type_name for kw in ["model", "llm", "provider"]):
            return ErrorCategory.MODEL
        return ErrorCategory.UNKNOWN

    @staticmethod
    def extract_recovery(original: Exception, category: ErrorCategory) -> list[str]:
        """根据异常给出可操作的恢复建议。"""
        actions = [CATEGORY_HINTS.get(category, "")]
        msg = str(original)

        if ErrorFormatter._has_retry(category):
            actions.append("框架已自动重试，若持续失败请检查上游服务状态。")
        if "api key" in msg.lower() or "key" in msg.lower():
            actions.append("运行 `agentos config set api_key <your-key>` 或设置环境变量。")
        if "model" in msg.lower() and "not found" in msg.lower():
            actions.append("请确认 ModelConfig.model_name 拼写正确，或使用 RECOMMENDED_CONFIG。")
        return [a for a in actions if a]

    @staticmethod
    def _has_retry(category: ErrorCategory) -> bool:
        return category in (ErrorCategory.NETWORK, ErrorCategory.TIMEOUT, ErrorCategory.RATE_LIMIT)

    @classmethod
    def format(cls, exc: Exception, trace_id: str = "") -> ErrorContext:
        """将异常格式化为 ErrorContext。"""
        category = cls.categorize(exc)
        return ErrorContext(
            trace_id=trace_id,
            category=category,
            message=cls._friendly_message(exc, category),
            suggestion=CATEGORY_HINTS.get(category, ""),
            detail=cls._extract_key_detail(exc),
            recovery_actions=cls.extract_recovery(exc, category),
        )

    @staticmethod
    def _friendly_message(exc: Exception, category: ErrorCategory) -> str:
        type_msg = str(exc)
        prefix = {
            ErrorCategory.NETWORK: "网络连接失败",
            ErrorCategory.AUTH: "认证失败",
            ErrorCategory.CONFIG: "配置错误",
            ErrorCategory.RATE_LIMIT: "请求被限流",
            ErrorCategory.VALIDATION: "输入校验失败",
            ErrorCategory.TIMEOUT: "操作超时",
            ErrorCategory.RESOURCE: "资源不足",
            ErrorCategory.MODEL: "模型调用异常",
            ErrorCategory.PLUGIN: "插件错误",
            ErrorCategory.INTERNAL: "内部错误",
            ErrorCategory.UNKNOWN: "发生错误",
        }.get(category, "错误")
        return f"{prefix}: {type_msg[:120]}"

    @staticmethod
    def _extract_key_detail(exc: Exception) -> str:
        lines = traceback.format_exception_only(type(exc), exc)
        return "".join(lines[-2:]).strip()


def format_error(exc: Exception, trace_id: str = "") -> str:
    """一行调用：输出用户友好的错误信息。"""
    ctx = ErrorFormatter.format(exc, trace_id)
    parts = [f"[{ctx.category.name}] {ctx.message}"]
    if ctx.suggestion:
        parts.append(f"  建议: {ctx.suggestion}")
    for action in ctx.recovery_actions:
        parts.append(f"  -> {action}")
    return "\n".join(parts)


def friendly_error(func):
    """装饰器：自动捕获异常并输出友好信息。"""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            friendly_msg = format_error(e)
            print(friendly_msg, file=sys.stderr)
            raise

    return wrapper
