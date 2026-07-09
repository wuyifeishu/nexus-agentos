"""Error handling: classification, formatting, and human-readable diagnosis."""

from .handler import (
    CATEGORY_HINTS,
    ErrorCategory,
    ErrorContext,
    ErrorFormatter,
    HumanError,
    format_error,
    friendly_error,
)

__all__ = [
    "CATEGORY_HINTS",
    "ErrorCategory",
    "ErrorContext",
    "ErrorFormatter",
    "HumanError",
    "format_error",
    "friendly_error",
]
