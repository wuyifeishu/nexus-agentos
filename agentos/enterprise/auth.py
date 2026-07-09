"""
AgentOS Enterprise — SSO & RBAC.

功能：
  - RBAC 角色模型（admin / developer / viewer / agent）
  - 权限定义与校验
  - SSO 集成接口（OIDC / SAML 抽象）
  - JWT Token 签发与验证
  - 会话管理
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from enum import StrEnum

# ── 权限系统 ──


class Permission(StrEnum):
    """细粒度权限定义。"""

    # Agent
    AGENT_CREATE = "agent:create"
    AGENT_READ = "agent:read"
    AGENT_UPDATE = "agent:update"
    AGENT_DELETE = "agent:delete"
    AGENT_RUN = "agent:run"
    # Tools
    TOOLS_LIST = "tools:list"
    TOOLS_EXECUTE = "tools:execute"
    TOOLS_MANAGE = "tools:manage"
    # API Keys
    KEYS_CREATE = "keys:create"
    KEYS_READ = "keys:read"
    KEYS_REVOKE = "keys:revoke"
    # Tenants
    TENANT_READ = "tenant:read"
    TENANT_MANAGE = "tenant:manage"
    # Audit
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    # Admin
    ADMIN_ALL = "admin:*"
    SYSTEM_CONFIG = "system:config"


class Role(StrEnum):
    """预定义角色。"""

    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"
    AGENT = "agent"


# 角色权限映射
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),  # 全部权限
    Role.DEVELOPER: {
        Permission.AGENT_CREATE,
        Permission.AGENT_READ,
        Permission.AGENT_UPDATE,
        Permission.AGENT_RUN,
        Permission.TOOLS_LIST,
        Permission.TOOLS_EXECUTE,
        Permission.KEYS_CREATE,
        Permission.KEYS_READ,
        Permission.AUDIT_READ,
    },
    Role.VIEWER: {
        Permission.AGENT_READ,
        Permission.TOOLS_LIST,
        Permission.KEYS_READ,
        Permission.AUDIT_READ,
        Permission.TENANT_READ,
    },
    Role.AGENT: {
        Permission.AGENT_RUN,
        Permission.TOOLS_EXECUTE,
    },
}


@dataclass
class User:
    """用户实体。"""

    user_id: str
    username: str
    email: str
    roles: list[Role]
    tenant_id: str
    custom_permissions: set[Permission] = field(default_factory=set)
    disabled: bool = False
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class RBACEngine:
    """RBAC 权限引擎。

    特性：
      - 角色 + 自定义权限叠加
      - 权限继承（admin 拥有全部）
      - 批量权限检查
      - 权限审计日志
    """

    def __init__(self):
        self._custom_roles: dict[str, set[Permission]] = {}

    def get_permissions(self, user: User) -> set[Permission]:
        """获取用户的所有有效权限。"""
        if user.disabled:
            return set()

        perms: set[Permission] = set(user.custom_permissions)

        for role in user.roles:
            perms |= ROLE_PERMISSIONS.get(role, set())

        # Admin 自动获得全部
        if Role.ADMIN in user.roles:
            perms = set(Permission)

        return perms

    def check_permission(self, user: User, permission: Permission) -> bool:
        """检查用户是否有某权限。"""
        return permission in self.get_permissions(user)

    def check_permissions(
        self, user: User, permissions: list[Permission]
    ) -> dict[Permission, bool]:
        """批量权限检查。"""
        user_perms = self.get_permissions(user)
        return {p: p in user_perms for p in permissions}

    def has_any(self, user: User, permissions: list[Permission]) -> bool:
        """用户是否拥有任一权限。"""
        user_perms = self.get_permissions(user)
        return bool(user_perms & set(permissions))

    def has_all(self, user: User, permissions: list[Permission]) -> bool:
        """用户是否拥有全部权限。"""
        user_perms = self.get_permissions(user)
        return set(permissions).issubset(user_perms)

    def register_custom_role(self, name: str, permissions: set[Permission]):
        """注册自定义角色。"""
        self._custom_roles[name] = permissions

    def get_role_permissions(self, role: Role) -> set[Permission]:
        return ROLE_PERMISSIONS.get(role, set())


# ── SSO 集成 ──


@dataclass
class OIDCConfig:
    """OIDC 提供商配置。"""

    issuer: str  # 如 "https://accounts.google.com"
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str] = field(default_factory=lambda: ["openid", "email", "profile"])
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    jwks_uri: str = ""


@dataclass
class SAMLConfig:
    """SAML 提供商配置。"""

    idp_entity_id: str
    idp_sso_url: str
    idp_certificate: str
    sp_entity_id: str
    sp_acs_url: str
    name_id_format: str = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"


@dataclass
class SSOUser:
    """SSO 返回的用户信息。"""

    external_id: str
    email: str
    display_name: str
    provider: str  # "oidc" / "saml"
    raw_claims: dict = field(default_factory=dict)


class SSOProvider:
    """SSO 抽象层 — OIDC / SAML 统一接口。"""

    @staticmethod
    def build_oidc_login_url(config: OIDCConfig, state: str = "", nonce: str = "") -> str:
        """构建 OIDC 登录 URL。"""
        import urllib.parse

        params = {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state or _rand_str(16),
            "nonce": nonce or _rand_str(16),
        }
        ep = config.authorization_endpoint or f"{config.issuer.rstrip('/')}/authorize"
        return f"{ep}?{urllib.parse.urlencode(params)}"

    @staticmethod
    def build_saml_login_url(config: SAMLConfig, relay_state: str = "") -> str:
        """构建 SAML 登录 URL（SAMLRequest Base64）。"""
        import base64
        import uuid

        saml_request = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
            f' ID="_{uuid.uuid4().hex}" Version="2.0"'
            f' IssueInstant="{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}"'
            f' Destination="{config.idp_sso_url}"'
            f' AssertionConsumerServiceURL="{config.sp_acs_url}">'
            f'<saml:Issuer xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
            f"{config.sp_entity_id}</saml:Issuer>"
            f"</samlp:AuthnRequest>"
        )
        encoded = base64.b64encode(saml_request.encode()).decode()
        import urllib.parse

        params = {"SAMLRequest": encoded}
        if relay_state:
            params["RelayState"] = relay_state
        return f"{config.idp_sso_url}?{urllib.parse.urlencode(params)}"

    @staticmethod
    async def exchange_oidc_code(config: OIDCConfig, code: str) -> SSOUser | None:
        """用 OIDC authorization_code 交换 token 并获取用户信息。（需要 httpx）"""
        try:
            import httpx
        except ImportError:
            return None

        token_ep = config.token_endpoint or f"{config.issuer.rstrip('/')}/token"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_ep,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                },
            )
            if resp.status_code != 200:
                return None
            token_data = resp.json()
            access_token = token_data.get("access_token")

            userinfo_ep = config.userinfo_endpoint or f"{config.issuer.rstrip('/')}/userinfo"
            resp2 = await client.get(
                userinfo_ep,
                headers={
                    "Authorization": f"Bearer {access_token}",
                },
            )
            if resp2.status_code != 200:
                return None
            info = resp2.json()
            return SSOUser(
                external_id=info.get("sub", ""),
                email=info.get("email", ""),
                display_name=info.get("name", info.get("preferred_username", "")),
                provider="oidc",
                raw_claims=info,
            )
        return None


# ── 会话管理 ──


@dataclass
class Session:
    """用户会话。"""

    session_id: str
    user_id: str
    tenant_id: str
    roles: list[Role]
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 3600)  # 1 小时
    ip_address: str = ""
    user_agent: str = ""

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class SessionStore:
    """内存会话存储（生产环境应替换为 Redis）。"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, user: User, ip: str = "", ua: str = "", ttl: int = 3600) -> Session:
        import uuid

        session = Session(
            session_id=f"sess_{uuid.uuid4().hex[:16]}",
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            roles=user.roles,
            expires_at=time.time() + ttl,
            ip_address=ip,
            user_agent=ua,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        s = self._sessions.get(session_id)
        if s and s.is_expired():
            del self._sessions[session_id]
            return None
        return s

    def revoke(self, session_id: str):
        self._sessions.pop(session_id, None)

    def revoke_user_sessions(self, user_id: str):
        to_remove = [sid for sid, s in self._sessions.items() if s.user_id == user_id]
        for sid in to_remove:
            del self._sessions[sid]

    def stats(self) -> dict:
        active = sum(1 for s in self._sessions.values() if not s.is_expired())
        return {"total": len(self._sessions), "active": active}


# ── JWT ──


class JWTManager:
    """简易 JWT 签发/验证（无外部依赖）。

    生产环境建议使用 PyJWT / jwcrypto。
    """

    def __init__(self, secret: str):
        self.secret = secret

    def encode(self, payload: dict, ttl: int = 3600) -> str:
        """签发 JWT。"""
        import base64

        header = {"alg": "HS256", "typ": "JWT"}
        claims = {
            **payload,
            "iat": int(time.time()),
            "exp": int(time.time()) + ttl,
        }
        segments = [
            base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode(),
            base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode(),
        ]
        signing_input = ".".join(segments)
        sig = hmac.new(self.secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        segments.append(base64.urlsafe_b64encode(sig).rstrip(b"=").decode())
        return ".".join(segments)

    def decode(self, token: str) -> dict | None:
        """验证并解码 JWT。"""
        import base64

        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header_b64, payload_b64, sig_b64 = parts
            signing_input = f"{header_b64}.{payload_b64}"

            # Verify signature
            expected_sig = (
                base64.urlsafe_b64encode(
                    hmac.new(self.secret.encode(), signing_input.encode(), hashlib.sha256).digest()
                )
                .rstrip(b"=")
                .decode()
            )

            if not hmac.compare_digest(sig_b64, expected_sig):
                return None

            # Decode payload
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "==").decode())

            # Check expiration
            if payload.get("exp", 0) < time.time():
                return None

            return payload
        except Exception:
            return None


# ── 工具函数 ──


def _rand_str(n: int) -> str:
    import secrets

    return secrets.token_hex(n // 2 + 1)[:n]


def require_permission(permission: Permission):
    """装饰器：要求调用者拥有指定权限。（示例用途）"""

    def decorator(func):
        def wrapper(*args, **kwargs):
            # 实际使用时会从上下文获取当前用户
            raise NotImplementedError("权限检查需在框架中间件中实现")

        return wrapper

    return decorator
