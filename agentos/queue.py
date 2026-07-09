from dataclasses import dataclass
from enum import Enum


class TaskState(Enum):
    PENDING = "pending"


class TaskPriority(Enum):
    HIGH = 1
    MEDIUM = 5
    LOW = 10


@dataclass
class TaskQueue:
    def submit(self, fn, priority=TaskPriority.MEDIUM):
        pass


class RateLimitStrategy(Enum):
    SLIDING_WINDOW = "sliding_window"


@dataclass
class RateLimitConfig:
    max_rps: float = 10.0


class RateLimiter:
    def __init__(self, config=None):
        pass
