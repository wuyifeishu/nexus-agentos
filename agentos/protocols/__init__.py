"""
AgentOS Protocols — Standardized agent communication interfaces.

Modules:
- registry.py: Agent Registry with service discovery, heartbeat, load balancing
- grpc.py: gRPC-based A2A protocol with streaming and TLS/mTLS
"""

from agentos.protocols.grpc import (
    SERVICE_NAME,
    DefaultAgentService,
    GrpcAgentService,
    GrpcClient,
    GrpcClientConfig,
    GrpcFrameCodec,
    GrpcHeartbeat,
    GrpcServer,
    GrpcServerConfig,
    GrpcStatusCode,
    GrpcStreamChunk,
    GrpcTaskRequest,
    GrpcTaskResponse,
    TaskStatus,
    create_self_signed_cert,
)
from agentos.protocols.registry import AgentRegistry

__all__ = [
    # Registry
    "AgentRegistry",
    # gRPC
    "GrpcTaskRequest",
    "GrpcTaskResponse",
    "GrpcHeartbeat",
    "GrpcStreamChunk",
    "TaskStatus",
    "GrpcStatusCode",
    "GrpcAgentService",
    "DefaultAgentService",
    "GrpcServer",
    "GrpcServerConfig",
    "GrpcClient",
    "GrpcClientConfig",
    "GrpcFrameCodec",
    "SERVICE_NAME",
    "create_self_signed_cert",
]


# ── Compatibility exports (required by agentos/__init__.py) ──

from dataclasses import dataclass, field
from enum import StrEnum


class CapabilityDomain(StrEnum):
    TEXT = "text"
    CODE = "code"
    MULTIMODAL = "multimodal"
    TOOL_USE = "tool_use"
    SAFETY = "safety"


class QoSLevel(StrEnum):
    BEST_EFFORT = "best_effort"
    AT_LEAST_ONCE = "at_least_once"
    EXACTLY_ONCE = "exactly_once"


@dataclass
class AgentCapability:
    name: str = ""
    domain: CapabilityDomain = CapabilityDomain.TEXT
    version: str = "1.0"
    description: str = ""
    parameters: dict = field(default_factory=dict)


@dataclass
class AgentContract:
    name: str = ""
    version: str = "1.0"
    capabilities: list = field(default_factory=list)
    qos: QoSLevel = QoSLevel.BEST_EFFORT
    endpoint: str = ""

    def model_dump(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": [c.name if hasattr(c, "name") else str(c) for c in self.capabilities],
            "qos": self.qos.value,
            "endpoint": self.endpoint,
        }


@dataclass
class MatchScore:
    score: float = 0.0
    matches: list = field(default_factory=list)


class CapabilityMatcher:
    """匹配 Agent 能力。"""

    def __init__(self):
        pass

    def match(self, required: list, available: list) -> MatchScore:
        resolved = set()
        for cap in required:
            for avail in available:
                cap_name = cap if isinstance(cap, str) else cap.name
                avail_name = avail if isinstance(avail, str) else avail.name
                if cap_name == avail_name:
                    resolved.add(cap_name)
        score = len(resolved) / max(len(required), 1)
        return MatchScore(score=score, matches=list(resolved))


class ContractRegistry:
    """Agent 合约注册中心。"""

    def __init__(self):
        self._contracts: dict[str, AgentContract] = {}

    def register(self, contract: AgentContract) -> None:
        self._contracts[contract.name] = contract

    def get(self, name: str) -> AgentContract:
        return self._contracts.get(name)

    def list_all(self) -> list[str]:
        return list(self._contracts.keys())


__all__ += [
    "AgentContract",
    "AgentCapability",
    "CapabilityDomain",
    "QoSLevel",
    "CapabilityMatcher",
    "ContractRegistry",
    "MatchScore",
]
