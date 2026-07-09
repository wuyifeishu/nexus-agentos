"""AgentOS Secrets Manager — production-grade secrets lifecycle.

Backends:
- EnvSecretsBackend: os.environ (12-factor)
- VaultSecretsBackend: HashiCorp Vault (kv-v2)
- EncryptedFileBackend: Fernet-encrypted JSON file
- CompositeSecretsBackend: layered resolution (most specific first)

Design: ~350 lines, thread-safe, lazy loading with caching.
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Data types
# ============================================================================


class SecretNotFoundError(Exception):
    """Requested secret key does not exist."""


class BackendUnavailableError(Exception):
    """Secrets backend is unreachable or misconfigured."""


@dataclass
class SecretsConfig:
    """Global secrets manager configuration."""

    cache_ttl: float = 300.0  # Seconds to cache fetched secrets
    max_cache_size: int = 1000  # Max cached entries
    fail_open: bool = False  # If True, return None on backend error instead of raising
    allow_environment_fallback: bool = True  # Try env vars before backend


# ============================================================================
# Abstract backend
# ============================================================================


class AbstractSecretsBackend(ABC):
    """Interface for secrets backends."""

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """Retrieve a single secret value."""

    @abstractmethod
    async def get_all(self, prefix: str = "") -> dict[str, str]:
        """Retrieve all secrets matching prefix."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify backend connectivity."""


# ============================================================================
# Env backend
# ============================================================================


class EnvSecretsBackend(AbstractSecretsBackend):
    """OS environment variable backend — no deps, always available."""

    def __init__(self, prefix: str = ""):
        self._prefix = prefix

    async def get(self, key: str) -> str | None:
        return os.environ.get(f"{self._prefix}{key}")

    async def get_all(self, prefix: str = "") -> dict[str, str]:
        full_prefix = f"{self._prefix}{prefix}"
        return {
            k[len(self._prefix) :] if k.startswith(self._prefix) else k: v
            for k, v in os.environ.items()
            if k.startswith(full_prefix)
        }

    async def health_check(self) -> bool:
        return True


# ============================================================================
# Encrypted file backend
# ============================================================================


class EncryptedFileBackend(AbstractSecretsBackend):
    """Fernet-encrypted JSON file backend.

    Secrets file encrypted at rest. Use `cryptography` for encryption.
    """

    def __init__(self, file_path: str, encryption_key: str):
        self._path = Path(file_path)
        self._key = encryption_key
        self._cache: dict[str, str] | None = None
        self._cache_time: float = 0.0
        self._lock = RLock()

    def _decrypt(self) -> dict[str, str]:
        """Decrypt and load secrets file."""
        from cryptography.fernet import Fernet

        if not self._path.exists():
            return {}

        fernet = Fernet(self._key.encode() if isinstance(self._key, str) else self._key)
        with open(self._path, "rb") as f:
            encrypted = f.read()
        decrypted = fernet.decrypt(encrypted)
        return json.loads(decrypted)

    async def get(self, key: str) -> str | None:
        with self._lock:
            if self._cache is None or (time.monotonic() - self._cache_time) > 300:
                try:
                    self._cache = self._decrypt()
                    self._cache_time = time.monotonic()
                except Exception as exc:
                    logger.error("Failed to decrypt secrets file: %s", exc)
                    raise BackendUnavailableError(f"Decryption failed: {exc}")
        return self._cache.get(key) if self._cache else None

    async def get_all(self, prefix: str = "") -> dict[str, str]:
        await self.get("")  # Refresh cache
        if self._cache is None:
            return {}
        if not prefix:
            return dict(self._cache)
        return {k: v for k, v in self._cache.items() if k.startswith(prefix)}

    async def health_check(self) -> bool:
        try:
            self._decrypt()
            return True
        except Exception:
            return False


# ============================================================================
# Vault backend (HashiCorp Vault kv-v2)
# ============================================================================


class VaultSecretsBackend(AbstractSecretsBackend):
    """HashiCorp Vault backend (kv-v2).

    Requires hvac library or httpx for REST calls.
    """

    def __init__(
        self,
        url: str,
        token: str,
        mount_point: str = "secret",
        path_prefix: str = "",
        verify_ssl: bool = True,
    ):
        self._url = url.rstrip("/")
        self._token = token
        self._mount_point = mount_point
        self._path_prefix = path_prefix
        self._verify_ssl = verify_ssl
        self._cache: dict[str, str | None] = {}
        self._lock = RLock()

    async def _call(self, method: str, path: str) -> Any:
        """Make authenticated Vault API call."""
        import httpx

        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=10.0) as client:
            headers = {"X-Vault-Token": self._token}
            url = f"{self._url}/v1/{path}"
            resp = await client.request(method, url, headers=headers)
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                raise BackendUnavailableError(
                    f"Vault API error {resp.status_code}: {resp.text[:200]}"
                )
            return resp.json()

    async def get(self, key: str) -> str | None:
        full_path = f"{self._path_prefix}/{key}" if self._path_prefix else key
        vault_path = f"{self._mount_point}/data/{full_path}"

        with self._lock:
            if key in self._cache:
                return self._cache[key]

        try:
            data = await self._call("GET", vault_path)
            if data is None:
                return None
            value = data.get("data", {}).get("data", {}).get("value")
            if value is None:
                value = data.get("data", {}).get("data", {})
            with self._lock:
                self._cache[key] = str(value) if not isinstance(value, dict) else json.dumps(value)
            return self._cache[key]
        except BackendUnavailableError:
            raise

    async def get_all(self, prefix: str = "") -> dict[str, str]:
        list_path = f"{self._mount_point}/metadata/{self._path_prefix}"
        result: dict[str, str] = {}

        try:
            data = await self._call("LIST", list_path)
            if data and "data" in data and "keys" in data["data"]:
                for key in data["data"]["keys"]:
                    if not prefix or key.startswith(prefix):
                        value = await self.get(key)
                        if value is not None:
                            result[key] = value
        except BackendUnavailableError:
            raise

        return result

    async def health_check(self) -> bool:
        try:
            resp = await self._call("GET", "sys/health")
            return resp is not None and resp.get("initialized", False)
        except Exception:
            return False


# ============================================================================
# Composite backend (layered)
# ============================================================================


class CompositeSecretsBackend(AbstractSecretsBackend):
    """Resolve secrets from multiple backends in priority order.

    First backend that returns a non-None value wins.
    """

    def __init__(self, backends: list[AbstractSecretsBackend]):
        self._backends = backends

    async def get(self, key: str) -> str | None:
        for backend in self._backends:
            try:
                value = await backend.get(key)
                if value is not None:
                    return value
            except Exception as exc:
                logger.debug("Backend %s failed for key=%s: %s", type(backend).__name__, key, exc)
        return None

    async def get_all(self, prefix: str = "") -> dict[str, str]:
        result: dict[str, str] = {}
        for backend in reversed(self._backends):  # Low-priority first
            try:
                batch = await backend.get_all(prefix)
                result.update(batch)
            except Exception as exc:
                logger.debug("Backend %s get_all failed: %s", type(backend).__name__, exc)
        return result

    async def health_check(self) -> bool:
        for backend in self._backends:
            if await backend.health_check():
                return True
        return False


# ============================================================================
# Secrets Manager (high-level)
# ============================================================================


class SecretsManager:
    """High-level secrets manager with caching and fail-open support.

    Usage:
        sm = SecretsManager(EnvSecretsBackend("MYAPP_"))
        api_key = await sm.get("API_KEY")
        # or
        api_key = await sm.require("API_KEY")  # raises if missing
    """

    def __init__(self, backend: AbstractSecretsBackend, config: SecretsConfig = SecretsConfig()):
        self._backend = backend
        self._config = config
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._lock = RLock()

    async def _cache_put(self, key: str, value: str | None):
        """Store value in cache with eviction."""
        with self._lock:
            if len(self._cache) >= self._config.max_cache_size:
                sorted_keys = sorted(self._cache, key=lambda k: self._cache[k][0])
                for old_key in sorted_keys[: len(self._cache) // 4]:
                    del self._cache[old_key]
            self._cache[key] = (time.monotonic(), value)

    async def get(self, key: str) -> str | None:
        """Get secret value. Returns None if not found."""
        # Check cache
        with self._lock:
            if key in self._cache:
                ts, val = self._cache[key]
                if time.monotonic() - ts < self._config.cache_ttl:
                    return val

        # Fallback to environment
        if self._config.allow_environment_fallback:
            env_val = os.environ.get(key)
            if env_val is not None:
                await self._cache_put(key, env_val)
                return env_val

        # Query backend
        try:
            value = await self._backend.get(key)
        except Exception as exc:
            if self._config.fail_open:
                logger.warning("Secrets backend error for key=%s (fail_open): %s", key, exc)
                return None
            raise BackendUnavailableError(f"Failed to fetch '{key}': {exc}") from exc

        # Update cache
        await self._cache_put(key, value)

        return value

    async def require(self, key: str) -> str:
        """Get secret value. Raises SecretNotFoundError if missing."""
        value = await self.get(key)
        if value is None:
            raise SecretNotFoundError(f"Required secret '{key}' not found")
        return value

    async def get_all(self, prefix: str = "") -> dict[str, str]:
        """Get all secrets with given prefix."""
        try:
            return await self._backend.get_all(prefix)
        except Exception as exc:
            if self._config.fail_open:
                logger.warning("Secrets get_all error (fail_open): %s", exc)
                return {}
            raise

    async def health_check(self) -> bool:
        """Check backend health."""
        return await self._backend.health_check()

    def invalidate_cache(self, key: str | None = None):
        """Invalidate cache entries."""
        with self._lock:
            if key is None:
                self._cache.clear()
            elif key in self._cache:
                del self._cache[key]


# ============================================================================
# Convenience factory
# ============================================================================


def create_secrets_manager(
    backend_type: str = "env",
    **kwargs: Any,
) -> SecretsManager:
    """Factory: create SecretsManager with common backends.

    backend_type: 'env' | 'vault' | 'encrypted_file' | 'composite'
    """
    if backend_type == "env":
        backend = EnvSecretsBackend(prefix=kwargs.get("prefix", ""))
    elif backend_type == "vault":
        backend = VaultSecretsBackend(
            url=kwargs["url"],
            token=kwargs["token"],
            mount_point=kwargs.get("mount_point", "secret"),
            path_prefix=kwargs.get("path_prefix", ""),
            verify_ssl=kwargs.get("verify_ssl", True),
        )
    elif backend_type == "encrypted_file":
        backend = EncryptedFileBackend(
            file_path=kwargs["file_path"],
            encryption_key=kwargs["encryption_key"],
        )
    elif backend_type == "composite":
        backends = kwargs["backends"]
        backend = CompositeSecretsBackend(backends)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")

    return SecretsManager(backend, SecretsConfig(**kwargs.get("config", {})))
