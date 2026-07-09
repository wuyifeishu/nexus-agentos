from dataclasses import dataclass
from enum import Enum


class SwarmPatterns:
    pass


class Topology(Enum):
    STAR = "star"
    MESH = "mesh"


@dataclass
class CollaborationConfig:
    pass


@dataclass
class CollaborationResult:
    pass
