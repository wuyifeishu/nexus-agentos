from dataclasses import dataclass
from enum import Enum


class ErrorCategory(Enum):
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    ctx: dict = None


@dataclass
class ErrorFormatter:
    pass


class HumanError(Exception):
    pass
