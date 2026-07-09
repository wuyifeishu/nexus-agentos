"""Tests for agentos.tools.key_rotation."""

import time

import pytest

from agentos.tools.key_rotation import KeyRotation


class TestKeyRotation:
    def test_initial_key_created(self):
        kr = KeyRotation()
        assert kr.current_key is not None
        assert len(kr.current_key) == 64  # 32 bytes hex

    def test_rotate_generates_new_key(self):
        kr = KeyRotation()
        old = kr.current_key
        kr.rotate()
        new = kr.current_key
        assert old != new

    def test_old_key_in_active_during_grace(self):
        kr = KeyRotation(grace_period=10.0)
        old = kr.current_key
        kr.rotate()
        assert old in kr.active_keys
        assert old in kr.pending_keys

    def test_grace_period_zero(self):
        kr = KeyRotation(grace_period=0.0)
        old = kr.current_key
        kr.rotate()
        assert old not in kr.active_keys

    def test_is_valid(self):
        kr = KeyRotation()
        current = kr.current_key
        assert kr.is_valid(current)
        assert not kr.is_valid("nonexistent")

    def test_is_valid_includes_pending(self):
        kr = KeyRotation(grace_period=10.0)
        old = kr.current_key
        kr.rotate()
        assert kr.is_valid(old)

    def test_multiple_rotations(self):
        kr = KeyRotation(grace_period=5.0)
        k1 = kr.current_key
        kr.rotate()
        k2 = kr.current_key
        kr.rotate()
        k3 = kr.current_key

        assert k1 in kr.active_keys   # still in grace
        assert k2 in kr.active_keys   # still in grace
        assert k3 == kr.current_key

    def test_grace_expiry(self):
        kr = KeyRotation(grace_period=0.05)
        old = kr.current_key
        kr.rotate()
        assert old in kr.active_keys
        time.sleep(0.1)
        assert old not in kr.active_keys

    def test_pre_rotate_hook(self):
        events = []
        kr = KeyRotation()
        kr.on_pre_rotate(lambda: events.append("pre"))
        kr.rotate()
        assert "pre" in events

    def test_post_rotate_hook(self):
        events = []
        kr = KeyRotation()
        kr.on_post_rotate(lambda old, new: events.append((old, new)))
        kr.rotate()
        assert len(events) == 1
        old, new = events[0]
        assert old != new

    def test_hook_exception_does_not_block(self):
        kr = KeyRotation()
        events = []

        def bad():
            raise RuntimeError("boom")

        def good():
            events.append("ok")

        kr.on_pre_rotate(bad)
        kr.on_pre_rotate(good)
        kr.rotate()
        assert "ok" in events

    def test_stop(self):
        kr = KeyRotation(rotation_interval=0.05)
        kr.start()
        kr.stop()
        assert kr.stats["running"] is False

    def test_key_length(self):
        kr = KeyRotation(key_length=16)
        assert len(kr.current_key) == 32  # 16 bytes hex

    def test_stats(self):
        kr = KeyRotation()
        s = kr.stats
        assert s["current"] == 1
        assert s["total_keys"] == 1
        assert s["key_length"] == 32

    def test_invalid_interval(self):
        with pytest.raises(ValueError):
            KeyRotation(rotation_interval=0)

    def test_invalid_grace(self):
        with pytest.raises(ValueError):
            KeyRotation(grace_period=-1)

    def test_active_keys_sorted_current_first(self):
        kr = KeyRotation(grace_period=5.0)
        k1 = kr.current_key
        kr.rotate()
        k2 = kr.current_key
        active = kr.active_keys
        assert active[0] == k2
