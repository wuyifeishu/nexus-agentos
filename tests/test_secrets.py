"""Tests for agentos.core.secrets — 26 test cases."""

import os

import pytest

from agentos.core.secrets import (
    BackendUnavailableError,
    CompositeSecretsBackend,
    EnvSecretsBackend,
    SecretNotFoundError,
    SecretsConfig,
    SecretsManager,
    create_secrets_manager,
)

# ============================================================================
# EnvSecretsBackend
# ============================================================================

class TestEnvBackend:
    """Test EnvSecretsBackend."""

    @pytest.mark.asyncio
    async def test_get_existing(self):
        os.environ["TEST_SECRET_GET"] = "myvalue"
        backend = EnvSecretsBackend()
        value = await backend.get("TEST_SECRET_GET")
        assert value == "myvalue"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        backend = EnvSecretsBackend()
        value = await backend.get("NONEXISTENT_VAR_XYZ999")
        assert value is None

    @pytest.mark.asyncio
    async def test_get_with_prefix(self):
        os.environ["MYAPP_API_KEY"] = "abc123"
        os.environ["OTHER_KEY"] = "other"
        backend = EnvSecretsBackend(prefix="MYAPP_")
        assert await backend.get("API_KEY") == "abc123"
        assert await backend.get("OTHER_KEY") is None

    @pytest.mark.asyncio
    async def test_get_all(self):
        os.environ["SEC_A"] = "1"
        os.environ["SEC_B"] = "2"
        os.environ["OTHER_C"] = "3"
        backend = EnvSecretsBackend()
        all_secrets = await backend.get_all()
        assert all_secrets["SEC_A"] == "1"
        assert all_secrets["SEC_B"] == "2"

    @pytest.mark.asyncio
    async def test_get_all_with_prefix(self):
        os.environ["APP_KEY1"] = "v1"
        os.environ["APP_KEY2"] = "v2"
        os.environ["OTHER"] = "x"
        backend = EnvSecretsBackend()
        filtered = await backend.get_all(prefix="APP_")
        assert len(filtered) >= 2
        assert filtered["APP_KEY1"] == "v1"

    @pytest.mark.asyncio
    async def test_health_check(self):
        backend = EnvSecretsBackend()
        assert await backend.health_check() is True


# ============================================================================
# SecretsManager
# ============================================================================

class TestSecretsManager:
    """Test SecretsManager high-level API."""

    @pytest.mark.asyncio
    async def test_get_existing(self):
        os.environ["SM_TEST_KEY"] = "secret_value"
        sm = SecretsManager(EnvSecretsBackend())
        value = await sm.get("SM_TEST_KEY")
        assert value == "secret_value"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        sm = SecretsManager(EnvSecretsBackend())
        value = await sm.get("NONEXISTENT_SM_XYZ")
        assert value is None

    @pytest.mark.asyncio
    async def test_require_existing(self):
        os.environ["REQUIRED_KEY"] = "must_have"
        sm = SecretsManager(EnvSecretsBackend())
        value = await sm.require("REQUIRED_KEY")
        assert value == "must_have"

    @pytest.mark.asyncio
    async def test_require_missing(self):
        sm = SecretsManager(EnvSecretsBackend())
        with pytest.raises(SecretNotFoundError):
            await sm.require("NONEXISTENT_REQUIRED_123")

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        os.environ["CACHE_TEST"] = "cached"
        sm = SecretsManager(EnvSecretsBackend(), SecretsConfig(cache_ttl=60.0))
        v1 = await sm.get("CACHE_TEST")
        # Modify env but cache should still return old
        os.environ["CACHE_TEST"] = "changed"
        v2 = await sm.get("CACHE_TEST")
        assert v1 == "cached"
        assert v2 == "cached"  # cache hit

    @pytest.mark.asyncio
    async def test_cache_invalidation(self):
        os.environ["INV_TEST"] = "original"
        sm = SecretsManager(EnvSecretsBackend(), SecretsConfig(cache_ttl=60.0))
        await sm.get("INV_TEST")
        sm.invalidate_cache("INV_TEST")
        os.environ["INV_TEST"] = "updated"
        value = await sm.get("INV_TEST")
        assert value == "updated"

    @pytest.mark.asyncio
    async def test_cache_full_invalidation(self):
        os.environ["A"] = "1"
        os.environ["B"] = "2"
        sm = SecretsManager(EnvSecretsBackend(), SecretsConfig(cache_ttl=60.0))
        await sm.get("A")
        await sm.get("B")
        sm.invalidate_cache()  # clear all
        os.environ["A"] = "new_a"
        assert await sm.get("A") == "new_a"

    @pytest.mark.asyncio
    async def test_get_all(self):
        os.environ["SM_A"] = "va"
        os.environ["SM_B"] = "vb"
        sm = SecretsManager(EnvSecretsBackend())
        all_secrets = await sm.get_all()
        assert all_secrets["SM_A"] == "va"

    @pytest.mark.asyncio
    async def test_fail_open(self):
        class BrokenBackend(EnvSecretsBackend):
            async def get(self, key):
                raise RuntimeError("backend down")

        sm = SecretsManager(BrokenBackend(), SecretsConfig(fail_open=True))
        value = await sm.get("any_key")
        assert value is None

    @pytest.mark.asyncio
    async def test_fail_closed(self):
        class BrokenBackend(EnvSecretsBackend):
            async def get(self, key):
                raise RuntimeError("backend down")

        sm = SecretsManager(BrokenBackend(), SecretsConfig(fail_open=False))
        with pytest.raises(BackendUnavailableError):
            await sm.get("any_key")

    @pytest.mark.asyncio
    async def test_environment_fallback(self):
        os.environ["FALLBACK_KEY"] = "from_env"
        sm = SecretsManager(EnvSecretsBackend(), SecretsConfig(allow_environment_fallback=True))
        value = await sm.get("FALLBACK_KEY")
        assert value == "from_env"

    @pytest.mark.asyncio
    async def test_health_check(self):
        sm = SecretsManager(EnvSecretsBackend())
        assert await sm.health_check() is True


# ============================================================================
# Composite backend
# ============================================================================

class TestCompositeBackend:
    """Test CompositeSecretsBackend layered resolution."""

    @pytest.mark.asyncio
    async def test_priority_order(self):
        os.environ["PRIORITY_KEY"] = "from_env"

        class HighPriorityBackend(EnvSecretsBackend):
            async def get(self, key):
                if key == "PRIORITY_KEY":
                    return "high_priority"
                return None

        composite = CompositeSecretsBackend([
            HighPriorityBackend(),
            EnvSecretsBackend(),
        ])
        value = await composite.get("PRIORITY_KEY")
        assert value == "high_priority"

    @pytest.mark.asyncio
    async def test_fallback_to_second(self):
        class EmptyBackend(EnvSecretsBackend):
            async def get(self, key):
                return None

        os.environ["FALLBACK_VAL"] = "second_wins"
        composite = CompositeSecretsBackend([
            EmptyBackend(),
            EnvSecretsBackend(),
        ])
        value = await composite.get("FALLBACK_VAL")
        assert value == "second_wins"

    @pytest.mark.asyncio
    async def test_all_none(self):
        class AlwaysNone(EnvSecretsBackend):
            async def get(self, key):
                return None

        composite = CompositeSecretsBackend([AlwaysNone()])
        value = await composite.get("anything")
        assert value is None

    @pytest.mark.asyncio
    async def test_get_all_merge(self):
        os.environ["COMP_A"] = "a"
        os.environ["COMP_B"] = "b"

        composite = CompositeSecretsBackend([EnvSecretsBackend()])
        all_secrets = await composite.get_all()
        assert all_secrets["COMP_A"] == "a"
        assert all_secrets["COMP_B"] == "b"


# ============================================================================
# Factory
# ============================================================================

class TestCreateSecretsManager:
    """Test create_secrets_manager factory."""

    def test_env_factory(self):
        sm = create_secrets_manager("env")
        assert isinstance(sm, SecretsManager)

    def test_composite_factory(self):
        sm = create_secrets_manager("composite", backends=[EnvSecretsBackend()])
        assert isinstance(sm, SecretsManager)

    def test_unknown_backend(self):
        with pytest.raises(ValueError):
            create_secrets_manager("nonexistent_backend")


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_cache_eviction(self):
        """Test that cache doesn't grow unbounded."""
        sm = SecretsManager(EnvSecretsBackend(), SecretsConfig(max_cache_size=10, cache_ttl=60.0))
        for i in range(20):
            os.environ[f"EVICT_{i}"] = str(i)
            await sm.get(f"EVICT_{i}")

        # Should not exceed max_cache_size substantially
        assert len(sm._cache) <= 15  # allow some margin due to eviction strategy

    @pytest.mark.asyncio
    async def test_empty_key(self):
        sm = SecretsManager(EnvSecretsBackend())
        value = await sm.get("")
        assert value is None
