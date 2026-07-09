"""Tests for agentos.core.auth — Authentication & Authorization."""

import asyncio
import time

import pytest

from agentos.core.auth import (
    DEFAULT_ROLES,
    ApiKeyEntry,
    AuthContext,
    Authenticator,
    AuthMethod,
    HS256TokenProvider,
    InMemoryCredentialStore,
    InMemoryTokenBlacklist,
    Permission,
    RBACEngine,
    Role,
    TokenClaims,
    require_auth,
)

# ═════════════════════════════════════════════════════════════════════════
# TokenClaims
# ═════════════════════════════════════════════════════════════════════════

class TestTokenClaims:
    def test_create_default_claims(self):
        claims = TokenClaims(sub="user-1")
        assert claims.sub == "user-1"
        assert claims.iss == "agentos"
        assert claims.jti
        assert claims.iat > 0
        assert claims.roles == []
        assert claims.permissions == []

    def test_to_dict(self):
        claims = TokenClaims(
            sub="user-1", exp=time.time() + 3600,
            aud="api", jti="abc123", roles=["admin"],
            permissions=["agent:*", "model:read"],
            extra={"team": "engineering"},
        )
        d = claims.to_dict()
        assert d["sub"] == "user-1"
        assert d["exp"] > 0
        assert d["aud"] == "api"
        assert d["jti"] == "abc123"
        assert d["roles"] == ["admin"]
        assert d["permissions"] == ["agent:*", "model:read"]
        assert d["team"] == "engineering"

    def test_from_dict(self):
        d = {
            "sub": "user-2", "iat": 100, "exp": 200,
            "iss": "custom", "jti": "xyz", "roles": ["viewer"],
            "permissions": ["model:read"], "team": "data",
        }
        claims = TokenClaims.from_dict(d)
        assert claims.sub == "user-2"
        assert claims.iat == 100.0
        assert claims.exp == 200.0
        assert claims.iss == "custom"
        assert claims.jti == "xyz"
        assert claims.roles == ["viewer"]
        assert claims.extra == {"team": "data"}

    def test_from_dict_minimal(self):
        claims = TokenClaims.from_dict({"sub": "minimal"})
        assert claims.sub == "minimal"
        assert claims.iss == "agentos"


# ═════════════════════════════════════════════════════════════════════════
# HS256TokenProvider
# ═════════════════════════════════════════════════════════════════════════

class TestHS256TokenProvider:
    @pytest.fixture
    def provider(self):
        return HS256TokenProvider(secret="test-secret-key-12345")

    @pytest.mark.asyncio
    async def test_create_and_validate(self, provider):
        claims = TokenClaims(sub="user-1", roles=["admin"])
        token = await provider.create_token(claims)
        assert token.count(".") == 2  # JWT format

        validated = await provider.validate_token(token)
        assert validated is not None
        assert validated.sub == "user-1"
        assert validated.roles == ["admin"]

    @pytest.mark.asyncio
    async def test_expired_token(self, provider):
        claims = TokenClaims(sub="user-1", exp=time.time() - 3600)
        token = await provider.create_token(claims)
        validated = await provider.validate_token(token)
        assert validated is None

    @pytest.mark.asyncio
    async def test_invalid_signature(self, provider):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.badsig"
        validated = await provider.validate_token(token)
        assert validated is None

    @pytest.mark.asyncio
    async def test_malformed_token(self, provider):
        validated = await provider.validate_token("not.a.jwt.token.at.all")
        assert validated is None

    @pytest.mark.asyncio
    async def test_key_rotation(self, provider):
        claims = TokenClaims(sub="user-1")
        token_old = await provider.create_token(claims)

        provider.rotate_secret("new-secret-key-67890")
        token_new = await provider.create_token(claims)

        # Both should validate (old secret still in grace)
        assert await provider.validate_token(token_old) is not None
        assert await provider.validate_token(token_new) is not None

    @pytest.mark.asyncio
    async def test_default_expiry(self, provider):
        claims = TokenClaims(sub="user-1")  # no exp
        token = await provider.create_token(claims)
        validated = await provider.validate_token(token)
        assert validated is not None
        assert validated.exp is not None
        assert validated.exp > time.time()


# ═════════════════════════════════════════════════════════════════════════
# InMemoryTokenBlacklist
# ═════════════════════════════════════════════════════════════════════════

class TestTokenBlacklist:
    @pytest.mark.asyncio
    async def test_add_and_check(self):
        bl = InMemoryTokenBlacklist()
        await bl.add("jti-123", ttl=60.0)
        assert await bl.is_blacklisted("jti-123") is True

    @pytest.mark.asyncio
    async def test_not_blacklisted(self):
        bl = InMemoryTokenBlacklist()
        assert await bl.is_blacklisted("unknown") is False

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        bl = InMemoryTokenBlacklist()
        await bl.add("jti-exp", ttl=0.01)
        await asyncio.sleep(0.02)
        assert await bl.is_blacklisted("jti-exp") is False

    @pytest.mark.asyncio
    async def test_cleanup(self):
        bl = InMemoryTokenBlacklist()
        await bl.add("jti-old", ttl=0.01)
        await asyncio.sleep(0.02)
        bl._cleanup()
        assert "jti-old" not in bl._store


# ═════════════════════════════════════════════════════════════════════════
# InMemoryCredentialStore
# ═════════════════════════════════════════════════════════════════════════

class TestCredentialStore:
    @pytest.mark.asyncio
    async def test_lookup_by_key(self):
        store = InMemoryCredentialStore()
        entry = ApiKeyEntry(
            key_hash="", subject="user-1", name="MyKey",
            scopes=["read"], roles=["viewer"], permissions=["model:read"],
        )
        store.add_key("sk-abcdef123456", entry)
        found = await store.lookup_by_key("sk-abcdef123456")
        assert found is not None
        assert found["subject"] == "user-1"
        assert found["roles"] == ["viewer"]

    @pytest.mark.asyncio
    async def test_lookup_invalid_key(self):
        store = InMemoryCredentialStore()
        assert await store.lookup_by_key("bad-key") is None

    @pytest.mark.asyncio
    async def test_revoke(self):
        store = InMemoryCredentialStore()
        store.add_key("sk-test", ApiKeyEntry(
            key_hash="", subject="u1", name="K1",
            scopes=[], roles=[], permissions=[],
        ))
        assert await store.lookup_by_key("sk-test") is not None
        assert await store.revoke("sk-test") is True
        assert await store.lookup_by_key("sk-test") is None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent(self):
        store = InMemoryCredentialStore()
        assert await store.revoke("no-such-key") is False


# ═════════════════════════════════════════════════════════════════════════
# RBACEngine
# ═════════════════════════════════════════════════════════════════════════

class TestRBACEngine:
    @pytest.fixture
    def rbac(self):
        engine = RBACEngine()
        engine.register_roles(DEFAULT_ROLES)
        return engine

    def test_admin_has_all(self, rbac):
        assert rbac.check({"admin"}, Permission("anything", "everything"))
        assert rbac.check({"admin"}, Permission("*", "*", "*"))

    def test_viewer_read_only(self, rbac):
        assert rbac.check({"viewer"}, Permission("agent", "read"))
        assert rbac.check({"viewer"}, Permission("model", "read"))
        assert not rbac.check({"viewer"}, Permission("agent", "write"))
        assert not rbac.check({"viewer"}, Permission("agent", "execute"))

    def test_developer_execute(self, rbac):
        assert rbac.check({"developer"}, Permission("model", "execute"))
        assert rbac.check({"developer"}, Permission("tool", "read"))
        assert not rbac.check({"developer"}, Permission("metric", "read"))

    def test_check_any(self, rbac):
        perms = [Permission("agent", "delete"), Permission("model", "read")]
        assert rbac.check_any({"viewer"}, perms) is True  # model:read
        assert rbac.check_any({"viewer"}, [Permission("agent", "delete")]) is False

    def test_check_all(self, rbac):
        perms = [Permission("agent", "read"), Permission("model", "read")]
        assert rbac.check_all({"viewer"}, perms) is True
        assert rbac.check_all({"viewer"}, [Permission("agent", "write"), Permission("model", "read")]) is False

    def test_hierarchical_scope(self, rbac):
        engine = RBACEngine()
        engine.register_role(Role("org_member", (
            Permission("agent", "read", "org:engineering"),
        )))
        assert engine.check({"org_member"}, Permission("agent", "read", "org:engineering"))
        assert not engine.check({"org_member"}, Permission("agent", "read", "org:sales"))

    def test_unregistered_role(self, rbac):
        assert not rbac.check({"non_existent"}, Permission("agent", "read"))


# ═════════════════════════════════════════════════════════════════════════
# Authenticator
# ═════════════════════════════════════════════════════════════════════════

class TestAuthenticator:
    @pytest.fixture
    def provider(self):
        return HS256TokenProvider(secret="auth-secret")

    @pytest.fixture
    def store(self):
        store = InMemoryCredentialStore()
        store.add_key("sk-test-key", ApiKeyEntry(
            key_hash="", subject="apikey-user", name="TestKey",
            scopes=["read"], roles=["viewer"], permissions=["model:read"],
        ))
        return store

    @pytest.fixture
    def auth(self, provider, store):
        return Authenticator(
            token_provider=provider,
            credential_store=store,
        )

    @pytest.mark.asyncio
    async def test_authenticate_jwt(self, auth, provider):
        claims = TokenClaims(sub="jwt-user", roles=["admin"])
        token = await provider.create_token(claims)
        ctx = await auth.authenticate({"authorization": f"Bearer {token}"})
        assert ctx.authenticated is True
        assert ctx.method == AuthMethod.JWT
        assert ctx.subject == "jwt-user"
        assert "admin" in ctx.roles

    @pytest.mark.asyncio
    async def test_authenticate_api_key(self, auth):
        ctx = await auth.authenticate({"X-API-Key": "sk-test-key"})
        assert ctx.authenticated is True
        assert ctx.method == AuthMethod.API_KEY
        assert ctx.subject == "apikey-user"
        assert "viewer" in ctx.roles

    @pytest.mark.asyncio
    async def test_authenticate_no_credentials(self, auth):
        ctx = await auth.authenticate({})
        assert ctx.authenticated is False
        assert ctx.method == AuthMethod.NONE

    @pytest.mark.asyncio
    async def test_authenticate_bad_token(self, auth):
        ctx = await auth.authenticate({"authorization": "Bearer garbage.token.here"})
        assert ctx.authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_bad_api_key(self, auth):
        ctx = await auth.authenticate({"X-API-Key": "wrong-key"})
        assert ctx.authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_query_param(self, auth):
        ctx = await auth.authenticate(
            {}, query_params={"api_key": "sk-test-key"}
        )
        assert ctx.authenticated is True
        assert ctx.subject == "apikey-user"

    @pytest.mark.asyncio
    async def test_blacklisted_token(self, auth, provider):
        blacklist = InMemoryTokenBlacklist()
        auth2 = Authenticator(
            token_provider=provider, blacklist=blacklist,
        )
        claims = TokenClaims(sub="temp-user")
        token = await provider.create_token(claims)
        await blacklist.add(claims.jti, ttl=3600.0)

        ctx = await auth2.authenticate({"authorization": f"Bearer {token}"})
        assert ctx.authenticated is False


# ═════════════════════════════════════════════════════════════════════════
# require_auth decorator
# ═════════════════════════════════════════════════════════════════════════

class TestRequireAuthDecorator:
    @pytest.mark.asyncio
    async def test_authenticated_passes(self):
        @require_auth()
        async def handler(auth_context=None):
            return "ok"

        ctx = AuthContext(authenticated=True)
        result = await handler(auth_context=ctx)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_unauthenticated_raises(self):
        @require_auth()
        async def handler(auth_context=None):
            return "ok"

        ctx = AuthContext(authenticated=False)
        with pytest.raises(PermissionError, match="authentication required"):
            await handler(auth_context=ctx)

    @pytest.mark.asyncio
    async def test_permission_check_passes(self):
        rbac = RBACEngine()
        rbac.register_role(Role("admin", (Permission("*", "*"),)))

        @require_auth(permission=Permission("agent", "execute"))
        async def handler(auth_context=None, _rbac=None):
            return "executed"

        ctx = AuthContext(authenticated=True, roles={"admin"})
        result = await handler(auth_context=ctx, _rbac=rbac)
        assert result == "executed"

    @pytest.mark.asyncio
    async def test_permission_check_fails(self):
        rbac = RBACEngine()
        rbac.register_role(Role("viewer", (Permission("agent", "read"),)))

        @require_auth(permission=Permission("agent", "delete"))
        async def handler(auth_context=None, _rbac=None):
            return "never"

        ctx = AuthContext(authenticated=True, roles={"viewer"})
        with pytest.raises(PermissionError):
            await handler(auth_context=ctx, _rbac=rbac)
