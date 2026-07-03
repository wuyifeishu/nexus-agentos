"""
PasswordHasher — bcrypt-like password hashing with pure stdlib.

Supports:
    - Hash password (pbkdf2_hmac with SHA256, 100k iterations)
    - Verify password against hash
    - Needs-upgrade detection (for rehashing with stronger params)
    - Self-contained format: $pbkdf2-sha256$iterations$salt$hash
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Tuple


# ============================================================================
# Hash format: $pbkdf2-sha256$iterations$salt$hash
# ============================================================================

DEFAULT_ITERATIONS = 100_000
SALT_LENGTH = 16
HASH_LENGTH = 32


class PasswordHasher:
    """Secure password hashing using PBKDF2-HMAC-SHA256.

    Usage:
        ph = PasswordHasher()

        # Hash a password
        hashed = ph.hash("my-password")

        # Verify
        ok = ph.verify("my-password", hashed)  # True

        # Check if rehash is needed
        if ph.needs_upgrade(hashed):
            new_hashed = ph.hash("my-password")
    """

    def __init__(self, iterations: int = DEFAULT_ITERATIONS):
        self._iterations = iterations

    def hash(self, password: str) -> str:
        """Hash a password and return the formatted hash string."""
        salt = secrets.token_bytes(SALT_LENGTH)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, self._iterations, dklen=HASH_LENGTH)
        salt_b64 = _b64_encode(salt)
        hash_b64 = _b64_encode(dk)
        return f"$pbkdf2-sha256${self._iterations}${salt_b64}${hash_b64}"

    def verify(self, password: str, hashed: str) -> Tuple[bool, bool]:
        """Verify password against hash. Returns (valid, needs_upgrade).

        needs_upgrade is True when hash uses weaker parameters.
        """
        params = self._parse(hashed)
        if not params:
            return False, False

        iterations, salt, stored_hash, algorithm = params

        if algorithm != "pbkdf2-sha256":
            return False, False

        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=HASH_LENGTH)
        valid = hmac.compare_digest(dk, stored_hash)
        needs_upgrade = valid and iterations < self._iterations
        return valid, needs_upgrade

    def needs_upgrade(self, hashed: str) -> bool:
        """Check if a hash needs to be upgraded to current params."""
        params = self._parse(hashed)
        if not params:
            return True
        iterations, _, _, algorithm = params
        return algorithm != "pbkdf2-sha256" or iterations < self._iterations

    # ---------- Internal ----------

    @staticmethod
    def _parse(hashed: str) -> Tuple[int, bytes, bytes, str] | None:
        """Parse hash string into (iterations, salt_bytes, hash_bytes, algorithm)."""
        try:
            parts = hashed.split("$")
            if len(parts) != 5 or parts[0] != "":
                return None
            algorithm = parts[1]
            iterations = int(parts[2])
            salt = _b64_decode(parts[3])
            h = _b64_decode(parts[4])
            return iterations, salt, h, algorithm
        except (ValueError, IndexError):
            return None


def _b64_encode(data: bytes) -> str:
    """Base64 encode without padding (URL-safe style for hash storage)."""
    import base64
    return base64.b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(s: str) -> bytes:
    import base64
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.b64decode(s)
