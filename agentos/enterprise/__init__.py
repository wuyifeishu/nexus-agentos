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
    APIKey,
    APIKeyManager,
    KeyCreateRequest,
    KeyCreateResult,
    KeyScope,
)
from agentos.enterprise.audit import (
    AuditCategory,
    AuditEvent,
    AuditLogger,
    AuditSeverity,
    RetentionPolicy,
)
from agentos.enterprise.auth import (
    ROLE_PERMISSIONS,
    JWTManager,
    OIDCConfig,
    Permission,
    RBACEngine,
    Role,
    SAMLConfig,
    Session,
    SessionStore,
    SSOProvider,
    SSOUser,
    User,
)
from agentos.enterprise.tenants import (
    TIER_QUOTAS,
    Tenant,
    TenantConfig,
    TenantManager,
    TenantStatus,
    TenantTier,
    TenantUsage,
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
