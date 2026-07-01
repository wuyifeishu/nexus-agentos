"""Error handling: classification, formatting, and human-readable diagnosis."""

from .handler import ErrorCategory, ErrorContext, ErrorFormatter, HumanError

__all__ = ["ErrorCategory", "ErrorContext", "ErrorFormatter", "HumanError"]
