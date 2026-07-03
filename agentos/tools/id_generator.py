"""
IDGenerator — multi-format unique identifier generation.

Supports:
    - UUID4 (random)
    - UUID7 (time-ordered, sortable)
    - ULID (26-char Crockford base32, time-sortable)
    - Nano ID (custom alphabet & length)
    - Snowflake-like (timestamp + worker + sequence)
    - KSUID (K-Sortable Unique IDentifier)
    - XID (12-byte globally unique ID)
    - Short ID (URL-safe, configurable length)
"""

from __future__ import annotations

import os
import secrets
import struct
import time
import uuid
from typing import Optional


# ============================================================================
# UUID7 (time-ordered UUID, RFC 9562 draft)
# ============================================================================

def uuid7() -> str:
    """Generate a time-ordered UUIDv7 string."""
    timestamp_ms = int(time.time() * 1000)
    rand_bytes = secrets.token_bytes(10)

    # UUID7 layout: 48-bit unix_ts_ms | 4-bit ver | 12-bit rand_a | 2-bit var | 62-bit rand_b
    ts_bytes = struct.pack(">Q", timestamp_ms)[2:]  # 6 bytes
    b = bytearray(ts_bytes + rand_bytes)

    # Set version to 7
    b[6] = (b[6] & 0x0F) | 0x70
    # Set variant to 10xx (RFC 4122)
    b[8] = (b[8] & 0x3F) | 0x80

    # Format as UUID
    u = uuid.UUID(bytes=bytes(b))
    return str(u)


# ============================================================================
# ULID
# ============================================================================

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

def ulid() -> str:
    """Generate a ULID (26-character Crockford base32)."""
    ts = int(time.time() * 1000)
    rand = secrets.token_bytes(10)

    # Timestamp: 48 bits = 10 base32 chars
    ts_part = ""
    for _ in range(10):
        ts_part = _CROCKFORD[ts & 0x1F] + ts_part
        ts >>= 5

    # Random: 80 bits = 16 base32 chars
    rand_part = ""
    r = int.from_bytes(rand, "big")
    for _ in range(16):
        rand_part = _CROCKFORD[r & 0x1F] + rand_part
        r >>= 5

    return ts_part + rand_part


# ============================================================================
# Nano ID
# ============================================================================

def nanoid(size: int = 21, alphabet: Optional[str] = None) -> str:
    """Generate a Nano ID string.

    Args:
        size: Length of the ID (default 21)
        alphabet: Custom alphabet (default URL-safe alphanumeric)
    """
    if alphabet is None:
        alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz-"

    mask = (1 << ((len(alphabet) - 1).bit_length())) - 1
    step = max(1, int(1.6 * mask * size / len(alphabet)))

    result = []
    while len(result) < size:
        for byte in secrets.token_bytes(step):
            idx = byte & mask
            if idx < len(alphabet):
                result.append(alphabet[idx])
                if len(result) == size:
                    break

    return "".join(result)


# ============================================================================
# Snowflake
# ============================================================================

class Snowflake:
    """Snowflake-like distributed ID generator.

    Layout (64 bits): timestamp(42) | worker(10) | sequence(12)
    Custom epoch: 2024-01-01T00:00:00Z
    """

    CUSTOM_EPOCH = 1704067200000  # 2024-01-01T00:00:00Z in ms

    def __init__(self, worker_id: int = 0):
        if not (0 <= worker_id < 1024):
            raise ValueError("worker_id must be 0-1023")
        self._worker_id = worker_id
        self._sequence = 0
        self._last_ms = -1

    def generate(self) -> int:
        """Generate next snowflake ID."""
        now = int(time.time() * 1000)

        if now < self._last_ms:
            # Clock moved backwards — wait
            now = self._last_ms

        if now == self._last_ms:
            self._sequence = (self._sequence + 1) & 0xFFF
            if self._sequence == 0:
                # Sequence exhausted, wait for next millisecond
                while now <= self._last_ms:
                    now = int(time.time() * 1000)
        else:
            self._sequence = 0

        self._last_ms = now
        ts = now - self.CUSTOM_EPOCH

        return (ts << 22) | (self._worker_id << 12) | self._sequence

    def generate_str(self) -> str:
        """Generate a snowflake ID as string."""
        return str(self.generate())


# ============================================================================
# Short ID
# ============================================================================

_SHORT_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

def short_id(length: int = 8) -> str:
    """Generate a short URL-safe random ID."""
    return "".join(secrets.choice(_SHORT_ALPHABET) for _ in range(length))


# ============================================================================
# Convenience
# ============================================================================

def uuid4() -> str:
    """Standard random UUIDv4."""
    return str(uuid.uuid4())

def generate(style: str = "uuid4") -> str:
    """Generate an ID in the requested style.

    Supported: uuid4, uuid7, ulid, nanoid, short
    """
    generators = {
        "uuid4": uuid4,
        "uuid7": uuid7,
        "ulid": ulid,
        "nanoid": lambda: nanoid(),
        "short": lambda: short_id(),
    }
    if style not in generators:
        raise ValueError(f"Unknown style: {style}. Choose from {list(generators.keys())}")
    return generators[style]()
