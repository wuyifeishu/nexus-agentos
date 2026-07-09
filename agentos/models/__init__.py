"""AgentOS v1.2.8 — Models module: routing, resilience, and API contracts."""

from agentos.models.agent import (
    AgentInfo,
    AgentListResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentStatus,
)
from agentos.models.error import (
    AgentOSError,
    AuthenticationError,
    AuthorizationError,
    ErrorCode,
    InternalError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)
from agentos.models.resilience import (
    CancellationSource,
    CancelledError,
    CircuitBreaker,
    CircuitBreakerConfig,
    ResilienceConfig,
    ResilientCall,
    RetryConfig,
    retry_with_backoff,
    with_fallback,
    with_timeout,
)

# v1.17.0: API contract models
from agentos.models.response import (
    APIErrorDetail,
    APIResponse,
    APIResponseMeta,
    HealthComponent,
    HealthResponse,
    PaginatedResponse,
    PaginationMeta,
    VersionResponse,
)
from agentos.models.router import ModelRouter
from agentos.models.routing_strategy import (
    Budget,
    Complexity,
    RoutingStrategy,
)

__all__ = [
    # Routing & Resilience
    "ModelRouter",
    "CancellationSource",
    "CancelledError",
    "RetryConfig",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "ResilienceConfig",
    "ResilientCall",
    "retry_with_backoff",
    "with_timeout",
    "with_fallback",
    "RoutingStrategy",
    "Complexity",
    "Budget",
    # API Contracts
    "APIResponse",
    "APIResponseMeta",
    "APIErrorDetail",
    "PaginationMeta",
    "PaginatedResponse",
    "HealthResponse",
    "HealthComponent",
    "VersionResponse",
    # Errors
    "ErrorCode",
    "AgentOSError",
    "ValidationError",
    "NotFoundError",
    "AuthenticationError",
    "AuthorizationError",
    "RateLimitError",
    "InternalError",
    "ServiceUnavailableError",
    # Agent
    "AgentRunRequest",
    "AgentRunResponse",
    "AgentStatus",
    "AgentInfo",
    "AgentListResponse",
]
