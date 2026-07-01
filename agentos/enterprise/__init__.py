"""
AgentOS Enterprise — 企业级特性套件。

包含:
  - APIKeyManager  — API Key 全生命周期管理
  - TenantManager  — 多租户管理
  - RBACEngine     — 基于角色的访问控制
  - SessionStore   — 会话管理
  - JWTManager     — JWT 签发与验证
  - SSOProvider    — SSO 集成（OIDC/SAML）
  - AuditLogger    — 审计日志引擎
"""

from agentos.enterprise.api_keys import (
    APIKeyManager,
    APIKey,
    KeyScope,
    KeyCreateRequest,
    KeyCreateResult,
)
from agentos.enterprise.tenants import (
    TenantManager,
    Tenant,
    TenantConfig,
    TenantUsage,
    TenantTier,
    TenantStatus,
    TIER_QUOTAS,
)
from agentos.enterprise.auth import (
    User,
    Role,
    Permission,
    ROLE_PERMISSIONS,
    RBACEngine,
    Session,
    SessionStore,
    JWTManager,
    SSOProvider,
    OIDCConfig,
    SAMLConfig,
    SSOUser,
)
from agentos.enterprise.audit import (
    AuditLogger,
    AuditEvent,
    AuditCategory,
    AuditSeverity,
    RetentionPolicy,
)

__all__ = [
    # API Keys
    "APIKeyManager",
    "APIKey",
    "KeyScope",
    "KeyCreateRequest",
    "KeyCreateResult",
    # Tenants
    "TenantManager",
    "Tenant",
    "TenantConfig",
    "TenantUsage",
    "TenantTier",
    "TenantStatus",
    "TIER_QUOTAS",
    # Auth / RBAC
    "User",
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "RBACEngine",
    "Session",
    "SessionStore",
    "JWTManager",
    "SSOProvider",
    "OIDCConfig",
    "SAMLConfig",
    "SSOUser",
    # Audit
    "AuditLogger",
    "AuditEvent",
    "AuditCategory",
    "AuditSeverity",
    "RetentionPolicy",
]
