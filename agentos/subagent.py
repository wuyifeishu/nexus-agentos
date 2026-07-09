from dataclasses import dataclass
from enum import Enum


class SubAgentMode(Enum):
    SYNC = "sync"


@dataclass
class SubAgentSpec:
    name: str = ""


@dataclass
class SubAgentResult:
    ok: bool = True


class ChildStatus(Enum):
    RUNNING = "running"


@dataclass
class ChildHeartbeat:
    ts: float = 0.0


@dataclass
class ChildInfo:
    name: str = ""


@dataclass
class SharedState:
    pass


@dataclass
class ChildContext:
    pass


class ChildHandle:
    pass


class SubAgentManager:
    pass
