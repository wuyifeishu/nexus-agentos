"""
AgentOS Protocols — Standardized agent communication interfaces.

Modules:
- registry.py: Agent Registry with service discovery, heartbeat, load balancing
- grpc.py: gRPC-based A2A protocol with streaming and TLS/mTLS
"""

from agentos.protocols.registry import AgentRegistry, AgentInfo
from agentos.protocols.grpc import (
    GrpcTaskRequest,
    GrpcTaskResponse,
    GrpcHeartbeat,
    GrpcStreamChunk,
    TaskStatus,
    GrpcStatusCode,
    GrpcAgentService,
    DefaultAgentService,
    GrpcServer,
    GrpcServerConfig,
    GrpcClient,
    GrpcClientConfig,
    GrpcFrameCodec,
    SERVICE_NAME,
    create_self_signed_cert,
)

__all__ = [
    # Registry
    "AgentRegistry",
    "AgentInfo",
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
