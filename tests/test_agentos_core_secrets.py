"""Tests for agentos.core.secrets — secrets lifecycle management."""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from agentos.core.secrets import (
    BackendUnavailableError,
    CompositeSecretsBackend,
    EncryptedFileBackend,
    EnvSecretsBackend,
    SecretNotFoundError,
    SecretsConfig,
    SecretsManager,
    create_secrets_manager,
)

# ============================================================================
# EnvSecretsBackend
# ============================================================================

class TestEnvSecretsBackend:
    @pytest.mark.asyncio
    async def test_get_exists(self, monkeypatch):
        monkeypatch.setenv("MYAPP_API_KEY", "sk-12345")
        backend = EnvSecretsBackend(prefix="MYAPP_")
        result = await backend.get("API_KEY")
        assert result == "sk-12345"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, monkeypatch):
        backend = EnvSecretsBackend()
        result = await backend.get("NONEXISTENT_KEY")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_filter(self, monkeypatch):
        monkeypatch.setenv("PREFIX_A", "1")
        monkeypatch.setenv("PREFIX_B", "2")
        monkeypatch.setenv("OTHER_VAR", "3")
        backend = EnvSecretsBackend(prefix="PREFIX_")
        all_secrets = await backend.get_all()
        assert "A" in all_secrets
        assert "B" in all_secrets
        assert "OTHER_VAR" not in all_secrets

    @pytest.mark.asyncio
    async def test_get_all_sub_prefix(self, monkeypatch):
        monkeypatch.setenv("APP_DB_HOST", "localhost")
        monkeypatch.setenv("APP_DB_PORT", "5432")
        monkeypatch.setenv("APP_REDIS_HOST", "redis1")
        backend = EnvSecretsBackend(prefix="APP_")
        db = await backend.get_all(prefix="DB_")
        assert len(db) == 2
        assert "DB_HOST" in db or "db_host" in [k.upper() for k in db]

    @pytest.mark.asyncio
    async def test_health_check(self):
        backend = EnvSecretsBackend()
        assert await backend.health_check() is True


# ============================================================================
# EncryptedFileBackend
# ============================================================================

class TestEncryptedFileBackend:
    @pytest.fixture
    def fernet_key(self):
        return Fernet.generate_key()

    @pytest.fixture
    def encrypted_file(self, fernet_key, tmp_path):
        """Create a Fernet-encrypted JSON file with test secrets."""
        data = {"api_key": "sk-encrypted-test", "db_password": "p@ssw0rd"}
        fernet = Fernet(fernet_key)
        plain = json.dumps(data).encode()
        encrypted = fernet.encrypt(plain)
        file_path = tmp_path / "secrets.enc"
        file_path.write_bytes(encrypted)
        return str(file_path)

    @pytest.mark.asyncio
    async def test_get_existing_key(self, encrypted_file, fernet_key):
        backend = EncryptedFileBackend(encrypted_file, fernet_key.decode())
        result = await backend.get("api_key")
        assert result == "sk-encrypted-test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, encrypted_file, fernet_key):
        backend = EncryptedFileBackend(encrypted_file, fernet_key.decode())
        result = await backend.get("missing_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all(self, encrypted_file, fernet_key):
        backend = EncryptedFileBackend(encrypted_file, fernet_key.decode())
        all_secrets = await backend.get_all()
        assert all_secrets["api_key"] == "sk-encrypted-test"
        assert all_secrets["db_password"] == "p@ssw0rd"

    @pytest.mark.asyncio
    async def test_get_all_with_prefix(self, encrypted_file, fernet_key):
        backend = EncryptedFileBackend(encrypted_file, fernet_key.decode())
        result = await backend.get_all(prefix="db_")
        assert "db_password" in result
        assert "api_key" not in result

    @pytest.mark.asyncio
    async def test_health_check_ok(self, encrypted_file, fernet_key):
        backend = EncryptedFileBackend(encrypted_file, fernet_key.decode())
        assert await backend.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_bad_key(self, encrypted_file):
        bad_key = Fernet.generate_key().decode()
        backend = EncryptedFileBackend(encrypted_file, bad_key)
        assert await backend.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_no_file(self, fernet_key, tmp_path):
        """No encrypted file returns {} in _decrypt (no exception), so backend is healthy."""
        nonexistent = str(tmp_path / "nonexistent.enc")
        backend = EncryptedFileBackend(nonexistent, fernet_key.decode())
        assert await backend.health_check() is True  # File missing is treated as empty vault (healthy)

    @pytest.mark.asyncio
    async def test_bad_encryption_raises(self, fernet_key, tmp_path):
        """File with garbage content raises BackendUnavailableError."""
        file_path = str(tmp_path / "garbage.enc")
        with open(file_path, "wb") as f:
            f.write(b"not-encrypted-garbage")
        backend = EncryptedFileBackend(file_path, fernet_key.decode())
        with pytest.raises(BackendUnavailableError):
            await backend.get("api_key")


# ============================================================================
# SecretsConfig
# ============================================================================

class TestSecretsConfig:
    def test_defaults(self):
        cfg = SecretsConfig()
        assert cfg.cache_ttl == 300.0
        assert cfg.max_cache_size == 1000
        assert cfg.fail_open is False
        assert cfg.allow_environment_fallback is True

    def test_custom_values(self):
        cfg = SecretsConfig(cache_ttl=60.0, max_cache_size=100, fail_open=True)
        assert cfg.cache_ttl == 60.0
        assert cfg.max_cache_size == 100
        assert cfg.fail_open is True


# ============================================================================
# SecretsManager
# ============================================================================

@pytest.fixture
def env_secrets_manager(monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-env-key")
    monkeypatch.setenv("DB_PASSWORD", "db-secret-123")
    monkeypatch.setenv("EMPTY_KEY", "")
    return SecretsManager(EnvSecretsBackend())


class TestSecretsManager:
    @pytest.mark.asyncio
    async def test_get_existing(self, env_secrets_manager):
        result = await env_secrets_manager.get("API_KEY")
        assert result == "sk-env-key"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, env_secrets_manager):
        result = await env_secrets_manager.get("TOTALLY_MISSING")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_empty_env_var(self, env_secrets_manager):
        result = await env_secrets_manager.get("EMPTY_KEY")
        assert result == ""  # Empty string is not None

    @pytest.mark.asyncio
    async def test_require_existing(self, env_secrets_manager):
        result = await env_secrets_manager.require("API_KEY")
        assert result == "sk-env-key"

    @pytest.mark.asyncio
    async def test_require_missing_raises(self, env_secrets_manager):
        with pytest.raises(SecretNotFoundError):
            await env_secrets_manager.require("MISSING_KEY")

    @pytest.mark.asyncio
    async def test_get_all(self, env_secrets_manager):
        all_secrets = await env_secrets_manager.get_all()
        assert "API_KEY" in all_secrets
        assert all_secrets["API_KEY"] == "sk-env-key"

    @pytest.mark.asyncio
    async def test_health_check(self, env_secrets_manager):
        assert await env_secrets_manager.health_check() is True

    @pytest.mark.asyncio
    async def test_cache_returns_cached_value(self, monkeypatch):
        monkeypatch.setenv("SECRET", "initial")
        sm = SecretsManager(EnvSecretsBackend(), SecretsConfig(cache_ttl=9999.0))
        first = await sm.get("SECRET")
        monkeypatch.setenv("SECRET", "changed")
        second = await sm.get("SECRET")
        assert first == "initial"
        assert second == "initial"  # Cached, not "changed"

    @pytest.mark.asyncio
    async def test_invalidate_cache_single(self, monkeypatch):
        monkeypatch.setenv("SECRET", "initial")
        sm = SecretsManager(EnvSecretsBackend(), SecretsConfig(cache_ttl=9999.0))
        await sm.get("SECRET")
        sm.invalidate_cache("SECRET")
        monkeypatch.setenv("SECRET", "changed")
        result = await sm.get("SECRET")
        assert result == "changed"

    @pytest.mark.asyncio
    async def test_invalidate_cache_all(self, monkeypatch):
        monkeypatch.setenv("SECRET", "initial")
        sm = SecretsManager(EnvSecretsBackend(), SecretsConfig(cache_ttl=9999.0))
        await sm.get("SECRET")
        sm.invalidate_cache()
        monkeypatch.setenv("SECRET", "changed")
        result = await sm.get("SECRET")
        assert result == "changed"

    @pytest.mark.asyncio
    async def test_fail_open_returns_none_on_backend_error(self):
        class FailingBackend(EnvSecretsBackend):
            async def get(self, key):
                raise BackendUnavailableError("simulated failure")

        sm = SecretsManager(FailingBackend(), SecretsConfig(fail_open=True))
        result = await sm.get("ANY_KEY")
        assert result is None

    @pytest.mark.asyncio
    async def test_fail_open_get_all_returns_empty(self):
        class FailingBackend(EnvSecretsBackend):
            async def get_all(self, prefix=""):
                raise BackendUnavailableError("simulated failure")

        sm = SecretsManager(FailingBackend(), SecretsConfig(fail_open=True))
        result = await sm.get_all()
        assert result == {}

    @pytest.mark.asyncio
    async def test_fail_closed_raises(self):
        class FailingBackend(EnvSecretsBackend):
            async def get(self, key):
                raise BackendUnavailableError("simulated failure")

        sm = SecretsManager(FailingBackend(), SecretsConfig(fail_open=False))
        with pytest.raises(BackendUnavailableError):
            await sm.get("ANY_KEY")

    @pytest.mark.asyncio
    async def test_environment_fallback(self, monkeypatch):
        """When allow_environment_fallback=True, env vars override backend."""
        monkeypatch.setenv("API_KEY", "env-fallback-value")

        class EmptyBackend(EnvSecretsBackend):
            async def get(self, key):
                return None

        sm = SecretsManager(EmptyBackend(), SecretsConfig(allow_environment_fallback=True))
        result = await sm.get("API_KEY")
        assert result == "env-fallback-value"

    @pytest.mark.asyncio
    async def test_no_environment_fallback(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "env-value")

        class EmptyBackend(EnvSecretsBackend):
            async def get(self, key):
                return None

        sm = SecretsManager(EmptyBackend(), SecretsConfig(allow_environment_fallback=False))
        result = await sm.get("API_KEY")
        assert result is None


# ============================================================================
# CompositeSecretsBackend
# ============================================================================

class TestCompositeSecretsBackend:
    @pytest.mark.asyncio
    async def test_first_backend_wins(self, monkeypatch):
        monkeypatch.setenv("PRIORITY_SECRET", "from-env")
        env = EnvSecretsBackend()
        composite = CompositeSecretsBackend([env])
        result = await composite.get("PRIORITY_SECRET")
        assert result == "from-env"

    @pytest.mark.asyncio
    async def test_falls_through_to_next(self, monkeypatch):
        monkeypatch.setenv("SECRET_B", "from-env")

        class EmptyBackend(EnvSecretsBackend):
            async def get(self, key):
                return None

        class ValueBackend(EnvSecretsBackend):
            async def get(self, key):
                return "from-value-backend"

        composite = CompositeSecretsBackend([EmptyBackend(), ValueBackend()])
        result = await composite.get("any_key")
        assert result == "from-value-backend"

    @pytest.mark.asyncio
    async def test_get_all_merges(self, monkeypatch):
        monkeypatch.setenv("A", "a-val")
        monkeypatch.setenv("B", "b-val")

        composite = CompositeSecretsBackend([EnvSecretsBackend()])
        result = await composite.get_all()
        assert result.get("A") == "a-val"
        assert result.get("B") == "b-val"

    @pytest.mark.asyncio
    async def test_health_check_any_true(self):
        env = EnvSecretsBackend()
        composite = CompositeSecretsBackend([env])
        assert await composite.health_check() is True


# ============================================================================
# create_secrets_manager
# ============================================================================

class TestCreateSecretsManager:
    def test_env_backend(self):
        sm = create_secrets_manager(backend_type="env", prefix="TEST_")
        assert isinstance(sm, SecretsManager)

    def test_encrypted_file_backend(self, tmp_path):
        data = {"secret": "test"}
        fernet_key = Fernet.generate_key()
        fernet = Fernet(fernet_key)
        enc_path = tmp_path / "enc.sec"
        enc_path.write_bytes(fernet.encrypt(json.dumps(data).encode()))

        sm = create_secrets_manager(
            backend_type="encrypted_file",
            file_path=str(enc_path),
            encryption_key=fernet_key.decode(),
        )
        assert isinstance(sm, SecretsManager)

    def test_composite_backend(self):
        sm = create_secrets_manager(
            backend_type="composite",
            backends=[EnvSecretsBackend()],
        )
        assert isinstance(sm, SecretsManager)

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown backend type"):
            create_secrets_manager(backend_type="magic_backend")
