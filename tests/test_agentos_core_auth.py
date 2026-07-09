"""Tests for agentos.core.auth — Auth framework (JWT / API Key / RBAC)."""

from __future__ import annotations

import time

import pytest

from agentos.core.auth import (
    DEFAULT_ROLES,
    Algorithm,
    ApiKeyEntry,
    AuthContext,
    Authenticator,
    AuthenticatorConfig,
    AuthMethod,
    HS256TokenProvider,
    InMemoryCredentialStore,
    InMemoryTokenBlacklist,
    Permission,
    RBACEngine,
    Role,
    TokenClaims,
    _b64url_decode,
    _b64url_encode,
    require_auth,
)

# ============================================================================
# _b64url_encode / _b64url_decode
# ============================================================================

class TestBase64Url:
    def test_encode_decode_roundtrip(self):
        for data in [b"hello", b"", b"\x00\xff", b"a" * 1000]:
            assert _b64url_decode(_b64url_encode(data)) == data

    def test_encode_no_padding(self):
        result = _b64url_encode(b"hello")
        assert "=" not in result

    def test_decode_adds_padding(self):
        encoded = _b64url_encode(b"test")
        # strip padding manually
        stripped = encoded.rstrip("=")
        assert _b64url_decode(stripped) == b"test"


# ============================================================================
# TokenClaims
# ============================================================================

class TestTokenClaims:
    def test_defaults(self):
        claims = TokenClaims(sub="user-1")
        assert claims.sub == "user-1"
        assert claims.iss == "agentos"
        assert claims.roles == []
        assert claims.permissions == []
        assert claims.extra == {}
        assert claims.aud is None
        assert claims.exp is None
        assert isinstance(claims.jti, str)
        assert isinstance(claims.iat, float)

    def test_to_dict_minimal(self):
        claims = TokenClaims(sub="user-1", iat=1000.0)
        d = claims.to_dict()
        assert d["sub"] == "user-1"
        assert d["iat"] == 1000
        assert d["iss"] == "agentos"
        assert "exp" not in d
        assert "aud" not in d  # None fields are skipped in to_dict

    def test_to_dict_full(self):
        claims = TokenClaims(
            sub="user-1",
            iat=1000.0,
            exp=2000.0,
            iss="my-issuer",
            aud="my-app",
            jti="jti-001",
            roles=["admin"],
            permissions=["agent:read"],
            extra={"custom": 42},
        )
        d = claims.to_dict()
        assert d["exp"] == 2000
        assert d["aud"] == "my-app"
        assert d["roles"] == ["admin"]
        assert d["permissions"] == ["agent:read"]
        assert d["custom"] == 42

    def test_from_dict_minimal(self):
        d = {"sub": "user-1"}
        claims = TokenClaims.from_dict(d)
        assert claims.sub == "user-1"
        assert claims.iss == "agentos"
        assert claims.jti is not None

    def test_from_dict_full(self):
        d = {
            "sub": "user-2",
            "iat": 1234,
            "exp": 5678,
            "iss": "issuer-x",
            "aud": "app-x",
            "jti": "jti-x",
            "roles": ["admin"],
            "permissions": ["agent:read"],
            "custom_field": "val",
        }
        claims = TokenClaims.from_dict(d)
        assert claims.sub == "user-2"
        assert claims.exp == 5678.0
        assert claims.aud == "app-x"
        assert claims.roles == ["admin"]
        assert claims.extra == {"custom_field": "val"}


# ============================================================================
# Enums & Dataclasses
# ============================================================================

class TestEnums:
    def test_auth_method_values(self):
        assert AuthMethod.NONE.value == "none"
        assert AuthMethod.JWT.value == "jwt"
        assert AuthMethod.API_KEY.value == "api_key"

    def test_algorithm_values(self):
        assert Algorithm.HS256.value == "HS256"
        assert Algorithm.RS256.value == "RS256"

    def test_permission_frozen(self):
        p = Permission(resource="agent", action="read")
        with pytest.raises(Exception):
            p.resource = "other"

    def test_permission_defaults(self):
        p = Permission(resource="agent", action="read")
        assert p.scope == "*"

    def test_role_creation(self):
        r = Role("admin", (Permission("*", "*"),))
        assert r.name == "admin"
        assert len(r.permissions) == 1


# ============================================================================
# InMemoryTokenBlacklist
# ============================================================================

class TestInMemoryTokenBlacklist:
    @pytest.fixture
    def bl(self):
        return InMemoryTokenBlacklist()

    @pytest.mark.asyncio
    async def test_not_blacklisted_initially(self, bl):
        assert not await bl.is_blacklisted("jti-1")

    @pytest.mark.asyncio
    async def test_add_and_check(self, bl):
        await bl.add("jti-1", 60.0)
        assert await bl.is_blacklisted("jti-1")

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, bl):
        await bl.add("jti-1", 0.01)
        await asyncio_sleep(0.02)
        assert not await bl.is_blacklisted("jti-1")

    @pytest.mark.asyncio
    async def test_multiple_entries(self, bl):
        await bl.add("a", 60)
        await bl.add("b", 60)
        assert await bl.is_blacklisted("a")
        assert await bl.is_blacklisted("b")
        assert not await bl.is_blacklisted("c")

    def test_cleanup(self, bl):
        # add entries: one expired, one fresh
        bl._store["a"] = time.monotonic() - 10  # expired
        bl._store["b"] = time.monotonic() + 100  # fresh
        bl._cleanup()
        assert "a" not in bl._store
        assert "b" in bl._store


# ============================================================================
# InMemoryCredentialStore
# ============================================================================

class TestInMemoryCredentialStore:
    @pytest.fixture
    def store(self):
        return InMemoryCredentialStore()

    def test_add_and_lookup(self, store):
        entry = ApiKeyEntry(
            key_hash="",
            subject="user-1",
            name="my-key",
            scopes=[],
            roles=["admin"],
            permissions=["agent:read"],
        )
        store.add_key("raw-secret-123", entry)
        result = await_sync(store.lookup_by_key("raw-secret-123"))
        assert result is not None
        assert result["subject"] == "user-1"
        assert result["roles"] == ["admin"]

    def test_lookup_missing_key(self, store):
        assert await_sync(store.lookup_by_key("nonexistent")) is None

    def test_revoke(self, store):
        entry = ApiKeyEntry(key_hash="", subject="u1", name="k1", scopes=[], roles=[], permissions=[])
        store.add_key("secret", entry)
        assert await_sync(store.revoke("secret")) is True
        assert await_sync(store.lookup_by_key("secret")) is None

    def test_revoke_nonexistent(self, store):
        assert await_sync(store.revoke("no-such")) is False

    def test_expired_key(self, store):
        entry = ApiKeyEntry(
            key_hash="", subject="u1", name="expired",
            scopes=[], roles=[], permissions=[],
            expires_at=time.time() - 60,
        )
        store.add_key("exp-secret", entry)
        assert await_sync(store.lookup_by_key("exp-secret")) is None

    def test_hash_deterministic(self, store):
        h1 = store._hash_key("secret")
        h2 = store._hash_key("secret")
        assert h1 == h2

    def test_hash_different_keys(self, store):
        h1 = store._hash_key("a")
        h2 = store._hash_key("b")
        assert h1 != h2


# ============================================================================
# HS256TokenProvider
# ============================================================================

class TestHS256TokenProvider:
    @pytest.fixture
    def provider(self):
        return HS256TokenProvider(secret="super-secret-key")

    @pytest.mark.asyncio
    async def test_create_and_validate(self, provider):
        claims = TokenClaims(sub="user-1")
        token = await provider.create_token(claims)
        validated = await provider.validate_token(token)
        assert validated is not None
        assert validated.sub == "user-1"

    @pytest.mark.asyncio
    async def test_default_ttl_applied(self, provider):
        claims = TokenClaims(sub="user-1", exp=None)
        token = await provider.create_token(claims)
        validated = await provider.validate_token(token)
        assert validated is not None
        assert validated.exp is not None

    @pytest.mark.asyncio
    async def test_expired_token(self, provider):
        claims = TokenClaims(sub="user-1", exp=time.time() - 60)
        token = await provider.create_token(claims)
        validated = await provider.validate_token(token)
        assert validated is None

    @pytest.mark.asyncio
    async def test_invalid_token_format(self, provider):
        assert await provider.validate_token("not-a-jwt") is None
        assert await provider.validate_token("a.b") is None
        assert await provider.validate_token("a.b.c.d") is None

    @pytest.mark.asyncio
    async def test_tampered_token(self, provider):
        claims = TokenClaims(sub="user-1")
        token = await provider.create_token(claims)
        parts = token.split(".")
        # tamper with payload
        tampered_payload = _b64url_encode(b'{"sub":"hacker"}')
        tampered = f"{parts[0]}.{tampered_payload}.{parts[2]}"
        assert await provider.validate_token(tampered) is None

    @pytest.mark.asyncio
    async def test_key_rotation(self, provider):
        claims = TokenClaims(sub="user-1")
        old_token = await provider.create_token(claims)

        provider.rotate_secret("new-secret-key")

        # Old token should still validate (previous secret retained)
        assert await provider.validate_token(old_token) is not None

        # New token uses new secret
        new_token = await provider.create_token(claims)
        assert await provider.validate_token(new_token) is not None

    @pytest.mark.asyncio
    async def test_issuer_set_on_create(self, provider):
        provider = HS256TokenProvider(secret="key", issuer="custom-issuer")
        claims = TokenClaims(sub="u1", iss="other")
        token = await provider.create_token(claims)
        validated = await provider.validate_token(token)
        assert validated.iss == "custom-issuer"


# ============================================================================
# RBACEngine
# ============================================================================

class TestRBACEngine:
    @pytest.fixture
    def rbac(self):
        engine = RBACEngine()
        engine.register_roles(DEFAULT_ROLES)
        return engine

    def test_get_permissions(self, rbac):
        perms = rbac.get_permissions({"admin"})
        assert any(p.resource == "*" and p.action == "*" for p in perms)

    def test_check_admin_full_access(self, rbac):
        assert rbac.check({"admin"}, Permission("anything", "do"))

    def test_check_viewer_read(self, rbac):
        assert rbac.check({"viewer"}, Permission("agent", "read"))
        assert not rbac.check({"viewer"}, Permission("agent", "write"))

    def test_check_any(self, rbac):
        assert rbac.check_any({"viewer"}, [
            Permission("agent", "write"),
            Permission("agent", "read"),
        ])

    def test_check_all(self, rbac):
        assert rbac.check_all({"viewer"}, [
            Permission("agent", "read"),
            Permission("log", "read"),
        ])
        assert not rbac.check_all({"viewer"}, [
            Permission("agent", "write"),
            Permission("agent", "read"),
        ])

    def test_check_unknown_role(self, rbac):
        assert not rbac.check({"nonexistent"}, Permission("agent", "read"))

    def test_wildcard_match(self, rbac):
        # admin has "*" for everything
        assert rbac.check({"admin"}, Permission("specific.resource", "specific.action", "specific.scope"))

    def test_hierarchical_scope_match(self, rbac):
        rbac.register_role(Role("org_admin", (
            Permission("agent", "read", "org:engineering"),
        )))
        # "org:engineering" grants access to exactly "org:engineering"
        assert rbac.check({"org_admin"}, Permission("agent", "read", "org:engineering"))
        # Wildcard scope grants access
        assert rbac.check({"admin"}, Permission("agent", "read", "org:engineering"))

    def test_register_single_role(self, rbac):
        rbac.register_role(Role("custom", (Permission("res", "act"),)))
        assert rbac.check({"custom"}, Permission("res", "act"))


# ============================================================================
# Authenticator
# ============================================================================

class TestAuthenticator:
    @pytest.fixture
    def jwt_provider(self):
        return HS256TokenProvider(secret="test-secret", issuer="agentos")

    @pytest.fixture
    def auth(self, jwt_provider):
        return Authenticator(token_provider=jwt_provider)

    @pytest.mark.asyncio
    async def test_jwt_auth_success(self, auth, jwt_provider):
        claims = TokenClaims(sub="user-1", roles=["admin"])
        token = await jwt_provider.create_token(claims)
        headers = {"Authorization": f"Bearer {token}"}
        ctx = await auth.authenticate(headers)
        assert ctx.authenticated
        assert ctx.method == AuthMethod.JWT
        assert ctx.subject == "user-1"
        assert "admin" in ctx.roles

    @pytest.mark.asyncio
    async def test_no_auth_header(self, auth):
        ctx = await auth.authenticate({})
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_invalid_token(self, auth):
        headers = {"Authorization": "Bearer xxx.yyy.zzz"}
        ctx = await auth.authenticate(headers)
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_api_key_auth(self):
        store = InMemoryCredentialStore()
        entry = ApiKeyEntry(
            key_hash="", subject="api-user", name="test",
            scopes=[], roles=["developer"], permissions=["agent:read"],
        )
        store.add_key("my-api-key", entry)
        auth = Authenticator(credential_store=store)
        headers = {"X-API-Key": "my-api-key"}
        ctx = await auth.authenticate(headers)
        assert ctx.authenticated
        assert ctx.method == AuthMethod.API_KEY
        assert ctx.subject == "api-user"
        assert "developer" in ctx.roles

    @pytest.mark.asyncio
    async def test_api_key_from_query_params(self):
        store = InMemoryCredentialStore()
        entry = ApiKeyEntry(
            key_hash="", subject="u2", name="t",
            scopes=[], roles=[], permissions=[],
        )
        store.add_key("query-key", entry)
        auth = Authenticator(credential_store=store)
        ctx = await auth.authenticate({}, query_params={"api_key": "query-key"})
        assert ctx.authenticated

    @pytest.mark.asyncio
    async def test_blacklisted_token(self, jwt_provider):
        bl = InMemoryTokenBlacklist()
        claims = TokenClaims(sub="u1", jti="revoked-jti")
        await bl.add("revoked-jti", 3600)
        token = await jwt_provider.create_token(claims)

        auth = Authenticator(token_provider=jwt_provider, blacklist=bl)
        ctx = await auth.authenticate({"Authorization": f"Bearer {token}"})
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_oauth2_stub_returns_unauthenticated(self):
        auth = Authenticator()
        ctx = await auth.authenticate({"Authorization": "Bearer opaque-token"})
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_rbac_property(self, auth):
        assert isinstance(auth.rbac, RBACEngine)

    @pytest.mark.asyncio
    async def test_auth_methods_restricted(self, jwt_provider):
        config = AuthenticatorConfig(allowed_methods=(AuthMethod.NONE,))
        auth = Authenticator(token_provider=jwt_provider, config=config)
        claims = TokenClaims(sub="u1")
        token = await jwt_provider.create_token(claims)
        ctx = await auth.authenticate({"Authorization": f"Bearer {token}"})
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_parse_permission_str(self):
        assert Authenticator._parse_permission_str("agent") == Permission("agent", "*")
        assert Authenticator._parse_permission_str("agent:read") == Permission("agent", "read")
        assert Authenticator._parse_permission_str("agent:read:own") == Permission("agent", "read", "own")


# ============================================================================
# require_auth decorator
# ============================================================================

class TestRequireAuthDecorator:
    async def dummy_handler(self, **kwargs):
        return "ok"

    @pytest.mark.asyncio
    async def test_no_auth_context_raises(self):
        decorated = require_auth()(self.dummy_handler)
        with pytest.raises(PermissionError, match="auth_context required"):
            await decorated()

    @pytest.mark.asyncio
    async def test_unauthenticated_raises(self):
        ctx = AuthContext(authenticated=False)
        decorated = require_auth()(self.dummy_handler)
        with pytest.raises(PermissionError, match="authentication required"):
            await decorated(auth_context=ctx)

    @pytest.mark.asyncio
    async def test_authenticated_success(self):
        ctx = AuthContext(authenticated=True, method=AuthMethod.JWT, subject="u1")
        decorated = require_auth()(self.dummy_handler)
        result = await decorated(auth_context=ctx)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_permission_denied(self):
        ctx = AuthContext(authenticated=True, roles={"viewer"})
        rbac = RBACEngine()
        rbac.register_roles(DEFAULT_ROLES)
        decorated = require_auth(permission=Permission("agent", "write"))(self.dummy_handler)
        with pytest.raises(PermissionError, match="missing permissions"):
            await decorated(auth_context=ctx, _rbac=rbac)

    @pytest.mark.asyncio
    async def test_permission_granted(self):
        ctx = AuthContext(authenticated=True, roles={"developer"})
        rbac = RBACEngine()
        rbac.register_roles(DEFAULT_ROLES)
        decorated = require_auth(permission=Permission("agent", "execute"))(self.dummy_handler)
        result = await decorated(auth_context=ctx, _rbac=rbac)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_multiple_permissions_all_required(self):
        ctx = AuthContext(authenticated=True, roles={"developer"})
        rbac = RBACEngine()
        rbac.register_roles(DEFAULT_ROLES)
        decorated = require_auth(permissions=[
            Permission("agent", "execute"),
            Permission("tool", "execute"),
        ])(self.dummy_handler)
        result = await decorated(auth_context=ctx, _rbac=rbac)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_no_rbac_when_permissions_needed(self):
        ctx = AuthContext(authenticated=True, roles={"admin"})
        decorated = require_auth(permission=Permission("agent", "read"))(self.dummy_handler)
        with pytest.raises(PermissionError, match="RBAC engine required"):
            await decorated(auth_context=ctx)


# ============================================================================
# DEFAULT_ROLES
# ============================================================================

class TestDefaultRoles:
    def test_four_roles(self):
        assert len(DEFAULT_ROLES) == 4

    def test_admin_has_wildcard(self):
        admin = [r for r in DEFAULT_ROLES if r.name == "admin"][0]
        assert Permission("*", "*", "*") in admin.permissions

    def test_viewer_read_only(self):
        viewer = [r for r in DEFAULT_ROLES if r.name == "viewer"][0]
        for p in viewer.permissions:
            assert p.action == "read"


# ============================================================================
# Helpers
# ============================================================================

import asyncio


def await_sync(coro):
    """Run a coroutine synchronously for testing."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    # Already in event loop — use pytest-asyncio
    raise RuntimeError("Use pytest.mark.asyncio instead")


async def asyncio_sleep(secs):
    await asyncio.sleep(secs)
