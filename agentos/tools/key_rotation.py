"""
KeyRotation — automated secret key rotation with grace periods and scheduled callbacks.

Supports:
    - Schedule-based rotation (interval in seconds)
    - Manual rotation trigger
    - Grace period (old key still valid for verification)
    - Current / pending / expired key states
    - Rotation hooks (pre_rotate, post_rotate)
    - Thread-safe
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ============================================================================
# Key State
# ============================================================================

class KeyState(Enum):
    CURRENT = "current"
    PENDING = "pending"      # newly rotated, still in grace
    EXPIRED = "expired"


@dataclass
class KeyEntry:
    key: str
    state: KeyState
    created_at: float
    expires_at: Optional[float] = None


# ============================================================================
# KeyRotation
# ============================================================================

class KeyRotation:
    """Automated secret key rotation with grace periods.

    Usage:
        kr = KeyRotation(rotation_interval=3600, grace_period=300, key_length=32)
        kr.start()

        current = kr.current_key      # Use this for signing/encryption
        active_keys = kr.active_keys  # All currently valid keys

        # When a new key is rotated in:
        # - current becomes the new key
        # - old key stays in active_keys during grace period (for validation)
        # - after grace period expires, old key is removed
    """

    def __init__(
        self,
        rotation_interval: float = 3600.0,
        grace_period: float = 300.0,
        key_length: int = 32,
    ):
        if rotation_interval <= 0:
            raise ValueError("rotation_interval must be positive")
        if grace_period < 0:
            raise ValueError("grace_period must be non-negative")
        self._interval = rotation_interval
        self._grace_period = grace_period
        self._key_length = key_length
        self._keys: List[KeyEntry] = []
        self._lock = threading.RLock()
        self._timer: Optional[threading.Timer] = None
        self._running = False

        # Hooks
        self._pre_rotate: List[Callable[[], None]] = []
        self._post_rotate: List[Callable[[str, str], None]] = []  # (old_key, new_key)

        # Seed with initial key
        self._rotate_now()

    # ---------- Lifecycle ----------

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        self._schedule_next()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _schedule_next(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._interval, self._on_timer)
            self._timer.daemon = True
            self._timer.start()

    def _on_timer(self) -> None:
        self._rotate_now()
        self._schedule_next()

    # ---------- Rotation ----------

    def rotate(self) -> str:
        """Manually trigger a rotation. Returns the new key."""
        return self._rotate_now()

    def _rotate_now(self) -> str:
        new_key = secrets.token_hex(self._key_length)
        now = time.time()

        with self._lock:
            old_key = self._keys[0].key if self._keys else None

            # Notify pre-rotation
            self._notify_pre_rotate()

            # Move current → pending (if grace > 0), otherwise expired
            for entry in self._keys:
                if entry.state == KeyState.CURRENT:
                    if self._grace_period > 0:
                        entry.state = KeyState.PENDING
                        entry.expires_at = now + self._grace_period
                    else:
                        entry.state = KeyState.EXPIRED

            # Add new current key
            new_entry = KeyEntry(key=new_key, state=KeyState.CURRENT, created_at=now)
            self._keys.insert(0, new_entry)

            # Clean up expired
            self._keys = [e for e in self._keys if e.state != KeyState.EXPIRED]

            # Notify post-rotation
            self._notify_post_rotate(old_key, new_key)

        return new_key

    # ---------- Key Access ----------

    @property
    def current_key(self) -> Optional[str]:
        with self._lock:
            for entry in self._keys:
                if entry.state == KeyState.CURRENT:
                    return entry.key
        return None

    @property
    def active_keys(self) -> List[str]:
        """All currently valid keys (CURRENT + PENDING)."""
        with self._lock:
            self._cleanup_expired()
            return [e.key for e in self._keys if e.state in (KeyState.CURRENT, KeyState.PENDING)]

    @property
    def pending_keys(self) -> List[str]:
        """Keys in grace period only."""
        with self._lock:
            self._cleanup_expired()
            return [e.key for e in self._keys if e.state == KeyState.PENDING]

    def is_valid(self, key: str) -> bool:
        """Check if a key is currently valid (CURRENT or PENDING)."""
        return key in self.active_keys

    def _cleanup_expired(self) -> None:
        now = time.time()
        self._keys = [
            e for e in self._keys
            if e.state != KeyState.EXPIRED
            and (e.expires_at is None or e.expires_at > now)
        ]

    # ---------- Hooks ----------

    def on_pre_rotate(self, callback: Callable[[], None]) -> None:
        self._pre_rotate.append(callback)

    def on_post_rotate(self, callback: Callable[[str, str], None]) -> None:
        self._post_rotate.append(callback)

    def _notify_pre_rotate(self) -> None:
        for cb in self._pre_rotate:
            try:
                cb()
            except Exception:
                pass

    def _notify_post_rotate(self, old_key: Optional[str], new_key: str) -> None:
        for cb in self._post_rotate:
            try:
                cb(old_key, new_key)
            except Exception:
                pass

    # ---------- Info ----------

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self._cleanup_expired()
            return {
                "total_keys": len(self._keys),
                "current": 1 if any(e.state == KeyState.CURRENT for e in self._keys) else 0,
                "pending": sum(1 for e in self._keys if e.state == KeyState.PENDING),
                "rotation_interval": self._interval,
                "grace_period": self._grace_period,
                "key_length": self._key_length,
                "running": self._running,
            }
