"""Tests for agentos.core.auth — Authenticator, RBACEngine, HS256TokenProvider."""

import time

import pytest

from agentos.core.auth import (
    DEFAULT_ROLES,
    Algorithm,
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
    _b64url_decode,
    _b64url_encode,
    require_auth,
)

# ============================================================================
# Enums & Data classes
# ============================================================================

class TestAuthMethod:
    def test_values(self):
        assert AuthMethod.NONE.value == "none"
        assert AuthMethod.JWT.value == "jwt"
        assert AuthMethod.API_KEY.value == "api_key"


class TestAlgorithm:
    def test_values(self):
        assert Algorithm.HS256.value == "HS256"
        assert Algorithm.RS256.value == "RS256"


class TestPermission:
    def test_create(self):
        p = Permission("agent", "read", "own")
        assert p.resource == "agent"
        assert p.action == "read"
        assert p.scope == "own"

    def test_default_scope(self):
        p = Permission("agent", "read")
        assert p.scope == "*"


class TestRole:
    def test_create(self):
        r = Role("admin", (Permission("*", "*"),))
        assert r.name == "admin"
        assert len(r.permissions) == 1


class TestAuthContext:
    def test_defaults(self):
        ctx = AuthContext()
        assert ctx.authenticated is False
        assert ctx.method == AuthMethod.NONE
        assert ctx.subject is None

    def test_authenticated(self):
        ctx = AuthContext(authenticated=True, method=AuthMethod.JWT, subject="u1", roles={"admin"})
        assert ctx.authenticated
        assert "admin" in ctx.roles


# ============================================================================
# TokenClaims
# ============================================================================

class TestTokenClaims:
    def test_create(self):
        tc = TokenClaims(sub="user1", roles=["admin"])
        assert tc.sub == "user1"
        assert tc.iss == "agentos"
        assert len(tc.jti) == 32

    def test_to_dict(self):
        tc = TokenClaims(sub="u1", exp=1000.0, roles=["r1"])
        d = tc.to_dict()
        assert d["sub"] == "u1"
        assert d["exp"] == 1000
        assert d["roles"] == ["r1"]

    def test_from_dict(self):
        d = {"sub": "u1", "roles": ["admin"], "extra_field": "x"}
        tc = TokenClaims.from_dict(d)
        assert tc.sub == "u1"
        assert tc.roles == ["admin"]
        assert tc.extra == {"extra_field": "x"}

    def test_roundtrip(self):
        tc = TokenClaims(sub="u1", roles=["r1"], permissions=["agent:read"], extra={"key": "val"})
        d = tc.to_dict()
        tc2 = TokenClaims.from_dict(d)
        assert tc2.sub == tc.sub
        assert tc2.roles == tc.roles
        assert tc2.extra == tc.extra

    def test_from_dict_minimal(self):
        d = {"sub": "u1"}
        tc = TokenClaims.from_dict(d)
        assert tc.iat is not None


# ============================================================================
# InMemoryTokenBlacklist
# ============================================================================

class TestInMemoryTokenBlacklist:
    @pytest.mark.asyncio
    async def test_add_and_check(self):
        bl = InMemoryTokenBlacklist()
        await bl.add("jti1", 60)
        assert await bl.is_blacklisted("jti1")

    @pytest.mark.asyncio
    async def test_not_blacklisted(self):
        bl = InMemoryTokenBlacklist()
        assert not await bl.is_blacklisted("missing")

    @pytest.mark.asyncio
    async def test_expired_removed(self):
        bl = InMemoryTokenBlacklist()
        await bl.add("jti1", 0.001)
        import asyncio
        await asyncio.sleep(0.01)
        assert not await bl.is_blacklisted("jti1")

    @pytest.mark.asyncio
    async def test_cleanup(self):
        bl = InMemoryTokenBlacklist()
        await bl.add("old", 0.001)
        await bl.add("new", 60)
        import asyncio
        await asyncio.sleep(0.01)
        bl._cleanup()
        assert "old" not in bl._store
        assert "new" in bl._store


# ============================================================================
# InMemoryCredentialStore
# ============================================================================

class TestInMemoryCredentialStore:
    def test_add_and_lookup(self):
        store = InMemoryCredentialStore()
        store.add_key("raw_key_123", ApiKeyEntry(
            key_hash="", subject="u1", name="my key", scopes=["read"], roles=["viewer"], permissions=[]
        ))
        entry = asyncio_run(store.lookup_by_key("raw_key_123"))
        assert entry["subject"] == "u1"
        assert entry["roles"] == ["viewer"]

    def test_lookup_missing(self):
        store = InMemoryCredentialStore()
        assert asyncio_run(store.lookup_by_key("bad")) is None

    def test_revoke(self):
        store = InMemoryCredentialStore()
        store.add_key("k1", ApiKeyEntry(key_hash="", subject="u1", name="x", scopes=[], roles=[], permissions=[]))
        assert asyncio_run(store.revoke("k1")) is True
        assert asyncio_run(store.lookup_by_key("k1")) is None

    def test_revoke_missing(self):
        store = InMemoryCredentialStore()
        assert asyncio_run(store.revoke("bad")) is False

    def test_expired_key(self):
        store = InMemoryCredentialStore()
        store.add_key("k1", ApiKeyEntry(
            key_hash="", subject="u1", name="x", scopes=[], roles=[], permissions=[],
            expires_at=time.time() - 60,
        ))
        assert asyncio_run(store.lookup_by_key("k1")) is None


# ============================================================================
# HS256TokenProvider
# ============================================================================

class TestHS256TokenProvider:
    @pytest.mark.asyncio
    async def test_create_and_validate(self):
        p = HS256TokenProvider("secret")
        tc = TokenClaims(sub="u1")
        token = await p.create_token(tc)
        claims = await p.validate_token(token)
        assert claims.sub == "u1"

    @pytest.mark.asyncio
    async def test_validate_invalid_token(self):
        p = HS256TokenProvider("secret")
        assert await p.validate_token("bad.token.here") is None

    @pytest.mark.asyncio
    async def test_validate_wrong_secret(self):
        p1 = HS256TokenProvider("s1")
        p2 = HS256TokenProvider("s2")
        token = await p1.create_token(TokenClaims(sub="u1"))
        assert await p2.validate_token(token) is None

    @pytest.mark.asyncio
    async def test_key_rotation_new_token(self):
        p = HS256TokenProvider("old_secret")
        p.rotate_secret("new_secret")
        tc = TokenClaims(sub="u1")
        token = await p.create_token(tc)
        claims = await p.validate_token(token)
        assert claims.sub == "u1"

    @pytest.mark.asyncio
    async def test_expired_token(self):
        p = HS256TokenProvider("s", default_ttl=0.001)
        tc = TokenClaims(sub="u1")
        tc.exp = time.time() - 10
        token = await p.create_token(tc)
        import asyncio
        await asyncio.sleep(0.01)
        assert await p.validate_token(token) is None

    @pytest.mark.asyncio
    async def test_default_expiry_set(self):
        p = HS256TokenProvider("s", default_ttl=3600)
        tc = TokenClaims(sub="u1", exp=None)
        token = await p.create_token(tc)
        claims = await p.validate_token(token)
        assert claims.exp is not None

    @pytest.mark.asyncio
    async def test_key_rotation_grace_period(self):
        p = HS256TokenProvider("secret")
        token_old = await p.create_token(TokenClaims(sub="u1"))
        p.rotate_secret("new_secret")
        assert await p.validate_token(token_old) is not None

    @pytest.mark.asyncio
    async def test_validate_two_part_token(self):
        p = HS256TokenProvider("s")
        assert await p.validate_token("a.b") is None


# ============================================================================
# RBACEngine
# ============================================================================

class TestRBACEngine:
    def test_register_role(self):
        rbac = RBACEngine()
        rbac.register_role(Role("admin", (Permission("*", "*"),)))
        perms = rbac.get_permissions({"admin"})
        assert len(perms) == 1

    def test_register_roles(self):
        rbac = RBACEngine()
        rbac.register_roles([Role("a", (Permission("x", "y"),)), Role("b", (Permission("z", "w"),))])
        assert len(rbac.get_permissions({"a", "b"})) == 2

    def test_check_wildcard(self):
        rbac = RBACEngine()
        rbac.register_role(Role("admin", (Permission("*", "*"),)))
        assert rbac.check({"admin"}, Permission("agent", "execute"))

    def test_check_exact(self):
        rbac = RBACEngine()
        rbac.register_role(Role("dev", (Permission("agent", "read"),)))
        assert rbac.check({"dev"}, Permission("agent", "read"))
        assert not rbac.check({"dev"}, Permission("agent", "write"))

    def test_check_any(self):
        rbac = RBACEngine()
        rbac.register_role(Role("dev", (Permission("agent", "read"),)))
        assert rbac.check_any({"dev"}, [Permission("agent", "write"), Permission("agent", "read")])

    def test_check_all(self):
        rbac = RBACEngine()
        rbac.register_role(Role("dev", (Permission("agent", "read"), Permission("agent", "execute"))))
        assert rbac.check_all({"dev"}, [Permission("agent", "read"), Permission("agent", "execute")])
        assert not rbac.check_all({"dev"}, [Permission("agent", "read"), Permission("agent", "delete")])

    def test_hierarchical_scope(self):
        rbac = RBACEngine()
        rbac.register_role(Role("admin", (Permission("*", "*", "org:engineering"),)))
        assert rbac.check({"admin"}, Permission("agent", "read", "org:engineering"))
        # Narrower doesn't match broader
        assert not rbac.check({"admin"}, Permission("agent", "read", "org"))

    def test_get_permissions_missing_role(self):
        rbac = RBACEngine()
        assert rbac.get_permissions({"missing"}) == set()

    def test_wildcard_action_in_perm(self):
        rbac = RBACEngine()
        rbac.register_role(Role("op", (Permission("agent", "*"),)))
        assert rbac.check({"op"}, Permission("agent", "execute"))


# ============================================================================
# Authenticator
# ============================================================================

class TestAuthenticator:
    @pytest.mark.asyncio
    async def test_no_auth_header(self):
        auth = Authenticator()
        ctx = await auth.authenticate({})
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_jwt_authentication(self):
        jwt = HS256TokenProvider("secret")
        auth = Authenticator(token_provider=jwt)
        token = await jwt.create_token(TokenClaims(sub="u1", roles=["admin"]))
        ctx = await auth.authenticate({"Authorization": f"Bearer {token}"})
        assert ctx.authenticated
        assert ctx.method == AuthMethod.JWT
        assert ctx.subject == "u1"
        assert "admin" in ctx.roles

    @pytest.mark.asyncio
    async def test_jwt_invalid_token(self):
        jwt = HS256TokenProvider("secret")
        auth = Authenticator(token_provider=jwt)
        ctx = await auth.authenticate({"Authorization": "Bearer bad.token.here"})
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_api_key_authentication(self):
        store = InMemoryCredentialStore()
        store.add_key("secret_key", ApiKeyEntry(
            key_hash="", subject="u1", name="test", scopes=[], roles=["viewer"], permissions=["agent:read"]
        ))
        auth = Authenticator(credential_store=store)
        ctx = await auth.authenticate({"X-API-Key": "secret_key"})
        assert ctx.authenticated
        assert ctx.method == AuthMethod.API_KEY
        assert ctx.subject == "u1"
        assert "viewer" in ctx.roles

    @pytest.mark.asyncio
    async def test_api_key_bad(self):
        store = InMemoryCredentialStore()
        auth = Authenticator(credential_store=store)
        ctx = await auth.authenticate({"X-API-Key": "bad"})
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_jwt_blacklisted(self):
        jwt = HS256TokenProvider("secret")
        bl = InMemoryTokenBlacklist()
        token = await jwt.create_token(TokenClaims(sub="u1"))
        tc = await jwt.validate_token(token)
        await bl.add(tc.jti, 60)
        auth = Authenticator(token_provider=jwt, blacklist=bl)
        ctx = await auth.authenticate({"Authorization": f"Bearer {token}"})
        assert not ctx.authenticated

    @pytest.mark.asyncio
    async def test_jwt_with_permissions(self):
        jwt = HS256TokenProvider("secret")
        auth = Authenticator(token_provider=jwt)
        token = await jwt.create_token(TokenClaims(sub="u1", permissions=["agent:read:own"]))
        ctx = await auth.authenticate({"Authorization": f"Bearer {token}"})
        assert ctx.authenticated
        assert len(ctx.permissions) == 1

    @pytest.mark.asyncio
    async def test_oauth2_stub(self):
        auth = Authenticator()
        ctx = await auth.authenticate({"Authorization": "Bearer oauth_token"})
        assert not ctx.authenticated  # Stub returns unauthenticated

    @pytest.mark.asyncio
    async def test_api_key_query_param(self):
        store = InMemoryCredentialStore()
        store.add_key("k1", ApiKeyEntry(key_hash="", subject="u1", name="x", scopes=[], roles=[], permissions=[]))
        auth = Authenticator(credential_store=store)
        ctx = await auth.authenticate({}, {"api_key": "k1"})
        assert ctx.authenticated


# ============================================================================
# require_auth decorator
# ============================================================================

class TestRequireAuth:
    @pytest.mark.asyncio
    async def test_missing_auth_context(self):
        @require_auth()
        async def handler(*args, **kwargs):
            return "ok"

        with pytest.raises(PermissionError, match="auth_context"):
            await handler()

    @pytest.mark.asyncio
    async def test_not_authenticated(self):
        @require_auth()
        async def handler(*args, **kwargs):
            return "ok"

        with pytest.raises(PermissionError, match="authentication"):
            await handler(auth_context=AuthContext())

    @pytest.mark.asyncio
    async def test_authenticated_no_permission(self):
        @require_auth()
        async def handler(*args, **kwargs):
            return "ok"

        ctx = AuthContext(authenticated=True, method=AuthMethod.JWT, subject="u1")
        result = await handler(auth_context=ctx)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_permission_check_pass(self):
        rbac = RBACEngine()
        rbac.register_role(Role("admin", (Permission("*", "*"),)))

        @require_auth(permission=Permission("agent", "execute"))
        async def handler(*args, **kwargs):
            return "ok"

        ctx = AuthContext(authenticated=True, roles={"admin"})
        result = await handler(auth_context=ctx, _rbac=rbac)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_permission_check_fail(self):
        rbac = RBACEngine()
        rbac.register_role(Role("viewer", (Permission("agent", "read"),)))

        @require_auth(permission=Permission("agent", "delete"))
        async def handler(*args, **kwargs):
            return "ok"

        ctx = AuthContext(authenticated=True, roles={"viewer"})
        with pytest.raises(PermissionError, match="missing permissions"):
            await handler(auth_context=ctx, _rbac=rbac)


# ============================================================================
# _b64url helpers
# ============================================================================

class TestB64:
    def test_roundtrip(self):
        data = b"hello world"
        assert _b64url_decode(_b64url_encode(data)) == data

    def test_encode_no_padding(self):
        enc = _b64url_encode(b"test")
        assert "=" not in enc


# ============================================================================
# DEFAULT_ROLES
# ============================================================================

class TestDefaultRoles:
    def test_four_roles(self):
        assert len(DEFAULT_ROLES) == 4
        names = {r.name for r in DEFAULT_ROLES}
        assert names == {"admin", "developer", "viewer", "operator"}

    def test_admin_has_all(self):
        admin = next(r for r in DEFAULT_ROLES if r.name == "admin")
        assert any(p.resource == "*" and p.action == "*" for p in admin.permissions)


# ============================================================================
# helper
# ============================================================================

def asyncio_run(coro):
    import asyncio
    try:
        _ = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as ex:
        return ex.submit(asyncio.run, coro).result()
