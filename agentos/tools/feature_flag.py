"""
FeatureFlag — runtime feature toggle system with percentage rollout.

Supports:
    - Boolean flags
    - Percentage-based rollouts
    - Target rules (by user ID, group, environment)
    - Flag dependencies (flag A requires flag B enabled)
    - Overrides (force-on / force-off per context)
    - Thread-safe reads/writes
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any, Callable, Dict, List, Optional, Set


class FeatureFlag:
    """Runtime feature toggle engine.

    Usage:
        ff = FeatureFlag()

        # Define flags
        ff.define("dark_mode", default=False)
        ff.define("new_checkout", default=False, rollout=10)  # 10% users
        ff.define("beta_search", default=False, targets=["beta-users"])
        ff.define("analytics_v2", default=True, depends_on=["new_checkout"])

        # Evaluate
        ff.is_enabled("dark_mode", context={"user_id": "user123"})
        ff.is_enabled("new_checkout", context={"user_id": "user123"})
    """

    def __init__(self):
        self._flags: Dict[str, _FlagDef] = {}
        self._lock = threading.RLock()

    # ---------- Define ----------

    def define(
        self,
        name: str,
        default: bool = False,
        rollout: int = 0,
        targets: Optional[List[str]] = None,
        depends_on: Optional[List[str]] = None,
    ):
        """Register a feature flag.

        Args:
            name: Flag name
            default: Default value when no rules match
            rollout: Percentage (0-100) of users who get the flag
            targets: User groups that get this flag
            depends_on: Other flags that must be enabled first
        """
        if not (0 <= rollout <= 100):
            raise ValueError("rollout must be 0-100")

        with self._lock:
            self._flags[name] = _FlagDef(
                name=name,
                default=default,
                rollout=rollout,
                targets=set(targets or []),
                depends_on=set(depends_on or []),
                overrides={},
            )

    # ---------- Evaluate ----------

    def is_enabled(self, name: str, context: Optional[dict] = None) -> bool:
        """Check whether a feature flag is enabled for the given context.

        Context may include:
            user_id: str
            groups: List[str]
        """
        context = context or {}

        with self._lock:
            if name not in self._flags:
                return False

            flag = self._flags[name]
            user_id = context.get("user_id", "")
            groups = set(context.get("groups", []))

            # Check overrides
            override_key = user_id
            if override_key and override_key in flag.overrides:
                return flag.overrides[override_key]

            # Check group targets
            if flag.targets and flag.targets & groups:
                return True

            # Check percentage rollout
            if flag.rollout > 0 and user_id:
                if self._in_rollout(user_id, name, flag.rollout):
                    return True

            # Check dependencies
            if flag.depends_on:
                if not all(self.is_enabled(d, context) for d in flag.depends_on):
                    return False

            return flag.default

    # ---------- Override ----------

    def set_override(self, name: str, user_id: str, value: bool):
        """Force a flag on/off for a specific user."""
        with self._lock:
            if name not in self._flags:
                raise KeyError(f"Unknown flag: {name}")
            self._flags[name].overrides[user_id] = value

    def clear_override(self, name: str, user_id: str):
        """Remove override for a user."""
        with self._lock:
            if name in self._flags:
                self._flags[name].overrides.pop(user_id, None)

    def clear_all_overrides(self, name: Optional[str] = None):
        """Clear all overrides, optionally for a specific flag."""
        with self._lock:
            if name:
                if name in self._flags:
                    self._flags[name].overrides.clear()
            else:
                for flag in self._flags.values():
                    flag.overrides.clear()

    # ---------- Query ----------

    def list_flags(self) -> List[str]:
        with self._lock:
            return list(self._flags.keys())

    def get_definition(self, name: str) -> Optional[dict]:
        with self._lock:
            flag = self._flags.get(name)
            if not flag:
                return None
            return {
                "name": flag.name,
                "default": flag.default,
                "rollout": flag.rollout,
                "targets": list(flag.targets),
                "depends_on": list(flag.depends_on),
            }

    def remove(self, name: str):
        with self._lock:
            self._flags.pop(name, None)

    # ---------- Internal ----------

    @staticmethod
    def _in_rollout(user_id: str, flag_name: str, percentage: int) -> bool:
        """Deterministic percentage-based rollout.

        Uses MD5 hash of (user_id + flag_name) to produce stable grouping.
        """
        key = f"{user_id}:{flag_name}"
        h = hashlib.md5(key.encode()).hexdigest()
        bucket = int(h[:8], 16) % 100
        return bucket < percentage


class _FlagDef:
    __slots__ = ("name", "default", "rollout", "targets", "depends_on", "overrides")

    def __init__(self, name, default, rollout, targets, depends_on, overrides):
        self.name = name
        self.default = default
        self.rollout = rollout
        self.targets: Set[str] = targets
        self.depends_on: Set[str] = depends_on
        self.overrides: Dict[str, bool] = overrides or {}
