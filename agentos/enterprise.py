from dataclasses import dataclass
from enum import Enum


class KeyScope(Enum):
    READ = "read"
    WRITE = "write"


@dataclass
class APIKey:
    id: str = ""


@dataclass
class KeyCreateRequest:
    name: str = ""


@dataclass
class KeyCreateResult:
    ok: bool = True


class APIKeyManager:
    pass


class TenantTier(Enum):
    FREE = "free"


class TenantStatus(Enum):
    ACTIVE = "active"


@dataclass
class TenantConfig:
    max_agents: int = 5


@dataclass
class TenantUsage:
    agents: int = 0


@dataclass
class Tenant:
    id: str = ""


class TenantManager:
    pass


TIER_QUOTAS = {}


class Permission(Enum):
    READ = "read"


class ROLE_PERMISSIONS:  # noqa: N801
    pass


@dataclass
class Role:
    name: str = ""


@dataclass
class User:
    id: str = ""


class RBACEngine:
    pass


class Session:
    pass


class SessionStore:
    pass


class JWTManager:
    pass


class SSOProvider:
    pass


@dataclass
class OIDCConfig:
    issuer: str = ""


@dataclass
class SAMLConfig:
    idp_url: str = ""


@dataclass
class SSOUser:
    id: str = ""


class AuditCategory(Enum):
    SECURITY = "security"


class AuditSeverity(Enum):
    INFO = "info"


@dataclass
class AuditEvent:
    pass


class AuditLogger:
    pass


class RetentionPolicy:
    pass
