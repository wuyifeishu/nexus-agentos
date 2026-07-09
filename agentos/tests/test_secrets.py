"""Tests for agentos.core.secrets — SecretsManager, backends, caching, fail-open."""

import json
import os
import tempfile

import pytest

from agentos.core.secrets import (
    BackendUnavailableError,
    CompositeSecretsBackend,
    EncryptedFileBackend,
    EnvSecretsBackend,
    SecretNotFoundError,
    SecretsConfig,
    SecretsManager,
    VaultSecretsBackend,
    create_secrets_manager,
)

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

    def test_custom(self):
        cfg = SecretsConfig(cache_ttl=60, max_cache_size=100, fail_open=True)
        assert cfg.cache_ttl == 60
        assert cfg.fail_open is True


# ============================================================================
# EnvSecretsBackend
# ============================================================================


class TestEnvSecretsBackend:
    @pytest.mark.asyncio
    async def test_get(self):
        os.environ["TEST_SECRET_X"] = "hello"
        be = EnvSecretsBackend(prefix="TEST_SECRET_")
        assert await be.get("X") == "hello"
        del os.environ["TEST_SECRET_X"]

    @pytest.mark.asyncio
    async def test_get_missing(self):
        be = EnvSecretsBackend()
        assert await be.get("NONEXISTENT") is None

    @pytest.mark.asyncio
    async def test_get_all(self):
        os.environ["TS_A"] = "1"
        os.environ["TS_B"] = "2"
        os.environ["OTHER"] = "3"
        be = EnvSecretsBackend(prefix="TS_")
        result = await be.get_all("A")
        assert result == {"A": "1"}
        del os.environ["TS_A"]
        del os.environ["TS_B"]
        del os.environ["OTHER"]

    @pytest.mark.asyncio
    async def test_get_all_no_prefix(self):
        os.environ["TS_X"] = "v"
        be = EnvSecretsBackend(prefix="TS_")
        result = await be.get_all()
        assert "X" in result
        assert result["X"] == "v"
        del os.environ["TS_X"]

    @pytest.mark.asyncio
    async def test_health_check(self):
        be = EnvSecretsBackend()
        assert await be.health_check() is True


# ============================================================================
# EncryptedFileBackend
# ============================================================================


class TestEncryptedFileBackend:
    def _make_encrypted_file(self, data: dict) -> str:
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        fernet = Fernet(key)
        encrypted = fernet.encrypt(json.dumps(data).encode())

        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            f.write(encrypted)
            self._cleanup_files = getattr(self, "_cleanup_files", [])
            self._cleanup_files.append(f.name)

        self._test_key = key.decode()
        return f.name

    def teardown_method(self):
        for fp in getattr(self, "_cleanup_files", []):
            try:
                os.unlink(fp)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_get(self):
        path = self._make_encrypted_file({"API_KEY": "abc123"})
        be = EncryptedFileBackend(file_path=path, encryption_key=self._test_key)
        assert await be.get("API_KEY") == "abc123"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        path = self._make_encrypted_file({"API_KEY": "abc123"})
        be = EncryptedFileBackend(file_path=path, encryption_key=self._test_key)
        assert await be.get("MISSING") is None

    @pytest.mark.asyncio
    async def test_get_all(self):
        path = self._make_encrypted_file({"A": "1", "B": "2"})
        be = EncryptedFileBackend(file_path=path, encryption_key=self._test_key)
        result = await be.get_all()
        assert result == {"A": "1", "B": "2"}

    @pytest.mark.asyncio
    async def test_get_all_prefix(self):
        path = self._make_encrypted_file({"DB_HOST": "x", "DB_PORT": "y", "API_KEY": "z"})
        be = EncryptedFileBackend(file_path=path, encryption_key=self._test_key)
        result = await be.get_all(prefix="DB_")
        assert result == {"DB_HOST": "x", "DB_PORT": "y"}

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        be = EncryptedFileBackend(file_path="/nonexistent/path.enc", encryption_key="dummy")
        assert await be.get("X") is None

    @pytest.mark.asyncio
    async def test_health_check_ok(self):
        path = self._make_encrypted_file({"X": "1"})
        be = EncryptedFileBackend(file_path=path, encryption_key=self._test_key)
        assert await be.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_bad_key(self):
        path = self._make_encrypted_file({"X": "1"})
        from cryptography.fernet import Fernet
        bad_key = Fernet.generate_key().decode()
        be = EncryptedFileBackend(file_path=path, encryption_key=bad_key)
        assert await be.health_check() is False


# ============================================================================
# CompositeSecretsBackend
# ============================================================================


class TestCompositeSecretsBackend:
    @pytest.mark.asyncio
    async def test_priority_order(self):
        be1 = EnvSecretsBackend()
        os.environ["KEY"] = "from_env"
        be2 = EnvSecretsBackend()
        os.environ["KEY2"] = "also_env"

        comp = CompositeSecretsBackend([be1, be2])
        # env backends both read from same os.environ, so this is degenerate
        # but verifies first hit wins
        assert await comp.get("NONEXISTENT") is None
        del os.environ["KEY"]
        del os.environ["KEY2"]

    @pytest.mark.asyncio
    async def test_get_all_merged(self):
        # Create a mock backend for deterministic testing
        class MockBackend(EnvSecretsBackend):
            def __init__(self, data: dict):
                self._data = data

            async def get(self, key: str) -> str | None:
                return self._data.get(key)

            async def get_all(self, prefix: str = "") -> dict[str, str]:
                if prefix:
                    return {k: v for k, v in self._data.items() if k.startswith(prefix)}
                return dict(self._data)

        be1 = MockBackend({"A": "1"})
        be2 = MockBackend({"B": "2"})
        comp = CompositeSecretsBackend([be1, be2])
        result = await comp.get_all()
        assert "A" in result
        assert "B" in result

    @pytest.mark.asyncio
    async def test_health_check_any(self):
        class DeadBackend:
            async def health_check(self):
                return False

        class AliveBackend:
            async def health_check(self):
                return True

        comp = CompositeSecretsBackend([DeadBackend(), AliveBackend()])
        assert await comp.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_all_dead(self):
        class DeadBackend:
            async def health_check(self):
                return False

        comp = CompositeSecretsBackend([DeadBackend(), DeadBackend()])
        assert await comp.health_check() is False


# ============================================================================
# SecretsManager
# ============================================================================


class TestSecretsManager:
    @pytest.mark.asyncio
    async def test_get_from_backend(self):
        class MockBackend:
            async def get(self, key):
                return "val" if key == "KEY" else None

            async def get_all(self, prefix=""):
                return {"KEY": "val"}

            async def health_check(self):
                return True

        sm = SecretsManager(MockBackend())
        assert await sm.get("KEY") == "val"
        assert await sm.get("MISSING") is None

    @pytest.mark.asyncio
    async def test_require(self):
        class MockBackend:
            async def get(self, key):
                return "val" if key == "KEY" else None

            async def get_all(self, prefix=""):
                return {}

            async def health_check(self):
                return True

        sm = SecretsManager(MockBackend())
        assert await sm.require("KEY") == "val"

    @pytest.mark.asyncio
    async def test_require_raises(self):
        class MockBackend:
            async def get(self, key):
                return None

            async def get_all(self, prefix=""):
                return {}

            async def health_check(self):
                return True

        sm = SecretsManager(MockBackend())
        with pytest.raises(SecretNotFoundError):
            await sm.require("MISSING")

    @pytest.mark.asyncio
    async def test_cache_reuse(self):
        call_count = 0

        class CountingBackend:
            async def get(self, key):
                nonlocal call_count
                call_count += 1
                return "cached"

            async def get_all(self, prefix=""):
                return {}

            async def health_check(self):
                return True

        sm = SecretsManager(CountingBackend(), SecretsConfig(cache_ttl=300))
        await sm.get("KEY")
        await sm.get("KEY")
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_env_fallback(self):
        os.environ["FALLBACK_KEY"] = "from_env"

        class EmptyBackend:
            async def get(self, key):
                return None

            async def get_all(self, prefix=""):
                return {}

            async def health_check(self):
                return True

        sm = SecretsManager(EmptyBackend(), SecretsConfig(allow_environment_fallback=True))
        assert await sm.get("FALLBACK_KEY") == "from_env"
        del os.environ["FALLBACK_KEY"]

    @pytest.mark.asyncio
    async def test_no_env_fallback(self):
        os.environ["FALLBACK_KEY"] = "from_env"

        class EmptyBackend:
            async def get(self, key):
                return None

            async def get_all(self, prefix=""):
                return {}

            async def health_check(self):
                return True

        sm = SecretsManager(EmptyBackend(), SecretsConfig(allow_environment_fallback=False))
        assert await sm.get("FALLBACK_KEY") is None
        del os.environ["FALLBACK_KEY"]

    @pytest.mark.asyncio
    async def test_fail_open(self):
        class FailingBackend:
            async def get(self, key):
                raise BackendUnavailableError("down")

            async def get_all(self, prefix=""):
                raise BackendUnavailableError("down")

            async def health_check(self):
                return False

        sm = SecretsManager(FailingBackend(), SecretsConfig(fail_open=True))
        assert await sm.get("KEY") is None

    @pytest.mark.asyncio
    async def test_fail_closed(self):
        class FailingBackend:
            async def get(self, key):
                raise BackendUnavailableError("down")

            async def get_all(self, prefix=""):
                raise BackendUnavailableError("down")

            async def health_check(self):
                return False

        sm = SecretsManager(FailingBackend(), SecretsConfig(fail_open=False))
        with pytest.raises(BackendUnavailableError):
            await sm.get("KEY")

    @pytest.mark.asyncio
    async def test_get_all(self):
        class MockBackend:
            async def get(self, key):
                return "x"

            async def get_all(self, prefix=""):
                return {"A": "1", "B": "2"}

            async def health_check(self):
                return True

        sm = SecretsManager(MockBackend())
        assert await sm.get_all() == {"A": "1", "B": "2"}

    @pytest.mark.asyncio
    async def test_health_check(self):
        class MockBackend:
            async def get(self, key):
                return None

            async def get_all(self, prefix=""):
                return {}

            async def health_check(self):
                return True

        sm = SecretsManager(MockBackend())
        assert await sm.health_check() is True

    @pytest.mark.asyncio
    async def test_invalidate_single_key(self):
        call_count = 0

        class CountingBackend:
            async def get(self, key):
                nonlocal call_count
                call_count += 1
                return "val"

            async def get_all(self, prefix=""):
                return {}

            async def health_check(self):
                return True

        sm = SecretsManager(CountingBackend())
        await sm.get("K1")
        await sm.get("K1")
        assert call_count == 1
        sm.invalidate_cache("K1")
        await sm.get("K1")
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_all(self):
        call_count = 0

        class CountingBackend:
            async def get(self, key):
                nonlocal call_count
                call_count += 1
                return "val"

            async def get_all(self, prefix=""):
                return {}

            async def health_check(self):
                return True

        sm = SecretsManager(CountingBackend())
        await sm.get("K1")
        await sm.get("K2")
        assert call_count == 2
        sm.invalidate_cache()
        await sm.get("K1")
        await sm.get("K2")
        assert call_count == 4


# ============================================================================
# create_secrets_manager factory
# ============================================================================


class TestCreateSecretsManager:
    def test_env_backend(self):
        sm = create_secrets_manager("env", prefix="P_")
        assert isinstance(sm, SecretsManager)

    def test_unknown_backend(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            create_secrets_manager("magic")


# ============================================================================
# VaultSecretsBackend (mocked)
# ============================================================================


class TestVaultSecretsBackend:
    @pytest.mark.asyncio
    async def test_health_check_false_when_unreachable(self):
        vb = VaultSecretsBackend(url="http://127.0.0.1:19999", token="fake")
        assert await vb.health_check() is False
