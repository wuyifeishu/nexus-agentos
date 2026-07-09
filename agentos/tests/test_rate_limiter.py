"""Comprehensive tests for agentos/tools/rate_limiter.py."""

import time

import pytest

from agentos.tools.rate_limiter import (
    RateLimitExceeded,
    SlidingWindow,
    TokenBucket,
)

# ============================================================================
# RateLimitExceeded
# ============================================================================


class TestRateLimitExceeded:
    def test_constructor_and_attributes(self):
        exc = RateLimitExceeded(key="api:test", limit=10.0, window=60.0)
        assert exc.key == "api:test"
        assert exc.limit == 10.0
        assert exc.window == 60.0

    def test_string_message(self):
        exc = RateLimitExceeded(key="user:42", limit=5.0, window=1.0)
        msg = str(exc)
        assert "user:42" in msg
        assert "5.0" in msg
        assert "1.0" in msg


# ============================================================================
# TokenBucket
# ============================================================================


class TestTokenBucketInit:
    def test_default_burst_equals_rate(self):
        tb = TokenBucket(rate=10.0)
        assert tb._rate == 10.0
        assert tb._burst == 10.0

    def test_custom_burst(self):
        tb = TokenBucket(rate=5.0, burst=20.0)
        assert tb._rate == 5.0
        assert tb._burst == 20.0

    def test_rate_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TokenBucket(rate=0)

    def test_rate_negative_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TokenBucket(rate=-1.0)

    def test_rate_property(self):
        tb = TokenBucket(rate=7.5)
        assert tb.rate == 7.5


class TestTokenBucketTryAcquire:
    def test_first_acquire_succeeds(self):
        tb = TokenBucket(rate=10.0, burst=5.0)
        assert tb.try_acquire("key1") is True

    def test_acquire_within_burst(self):
        tb = TokenBucket(rate=10.0, burst=5.0)
        for _ in range(5):
            assert tb.try_acquire("key1") is True
        # 6th should fail
        assert tb.try_acquire("key1") is False

    def test_acquire_multi_tokens(self):
        tb = TokenBucket(rate=10.0, burst=10.0)
        assert tb.try_acquire("key1", tokens=5.0) is True
        assert tb.try_acquire("key1", tokens=5.0) is True
        assert tb.try_acquire("key1", tokens=5.0) is False

    def test_different_keys_independent(self):
        tb = TokenBucket(rate=10.0, burst=2.0)
        assert tb.try_acquire("key1") is True
        assert tb.try_acquire("key1") is True
        assert tb.try_acquire("key1") is False
        # key2 should be unaffected
        assert tb.try_acquire("key2") is True

    def test_refill_after_wait(self):
        tb = TokenBucket(rate=100.0, burst=2.0)  # 100 tokens/sec
        assert tb.try_acquire("key1") is True
        assert tb.try_acquire("key1") is True
        assert tb.try_acquire("key1") is False
        time.sleep(0.02)  # ~2 tokens refilled
        assert tb.try_acquire("key1") is True

    def test_refill_capped_at_burst(self):
        tb = TokenBucket(rate=1000.0, burst=3.0)
        for _ in range(3):
            assert tb.try_acquire("key1") is True
        assert tb.try_acquire("key1") is False
        time.sleep(0.1)  # would refill 100, but burst caps at 3
        # should have exactly 3 tokens, not 100
        for _ in range(3):
            assert tb.try_acquire("key1") is True
        assert tb.try_acquire("key1") is False

    def test_acquire_exact_tokens(self):
        tb = TokenBucket(rate=10.0, burst=10.0)
        assert tb.try_acquire("key1", tokens=10.0) is True
        assert tb.try_acquire("key1") is False


class TestTokenBucketAcquireOrWait:
    def test_immediate_success(self):
        tb = TokenBucket(rate=10.0, burst=5.0)
        assert tb.acquire_or_wait("key1", timeout=1.0) is True

    def test_blocks_and_waits_for_refill(self):
        tb = TokenBucket(rate=200.0, burst=2.0)  # 200 tokens/sec
        for _ in range(2):
            tb.try_acquire("key1")
        # Should block briefly then succeed
        assert tb.acquire_or_wait("key1", timeout=1.0) is True

    def test_timeout_expires(self):
        tb = TokenBucket(rate=0.1, burst=1.0)  # very slow refill
        tb.try_acquire("key1")
        assert tb.acquire_or_wait("key1", timeout=0.01) is False

    def test_no_timeout_blocks_indefinitely(self):
        tb = TokenBucket(rate=500.0, burst=1.0)
        tb.try_acquire("key1")
        # Should succeed within a very short time without explicit timeout
        assert tb.acquire_or_wait("key1", timeout=None) is True

    def test_multi_token_acquire_or_wait(self):
        tb = TokenBucket(rate=500.0, burst=5.0)
        assert tb.acquire_or_wait("key1", timeout=1.0, tokens=5.0) is True
        assert tb.try_acquire("key1") is False


class TestTokenBucketReset:
    def test_reset_removes_key(self):
        tb = TokenBucket(rate=10.0, burst=3.0)
        for _ in range(3):
            tb.try_acquire("key1")
        assert tb.try_acquire("key1") is False
        tb.reset("key1")
        assert tb.try_acquire("key1") is True

    def test_reset_nonexistent_key_no_error(self):
        tb = TokenBucket(rate=10.0)
        tb.reset("no-such-key")

    def test_reset_all_clears_everything(self):
        tb = TokenBucket(rate=10.0, burst=2.0)
        tb.try_acquire("key1")
        tb.try_acquire("key2")
        tb.reset_all()
        assert len(tb._buckets) == 0
        assert tb.try_acquire("key1") is True


class TestTokenBucketStats:
    def test_initial_stats(self):
        tb = TokenBucket(rate=10.0, burst=20.0)
        s = tb.stats()
        assert s["rate"] == 10.0
        assert s["burst"] == 20.0
        assert s["active_keys"] == 0
        assert s["total_acquired"] == 0
        assert s["total_rejected"] == 0

    def test_stats_after_acquire(self):
        tb = TokenBucket(rate=10.0, burst=5.0)
        for _ in range(3):
            tb.try_acquire("key1")
        s = tb.stats()
        assert s["total_acquired"] == 3
        assert s["active_keys"] == 1

    def test_stats_after_reject(self):
        tb = TokenBucket(rate=10.0, burst=1.0)
        tb.try_acquire("key1")
        tb.try_acquire("key1")  # rejected — same key, bucket exhausted
        s = tb.stats()
        assert s["total_acquired"] == 1
        assert s["total_rejected"] == 1


# ============================================================================
# SlidingWindow
# ============================================================================


class TestSlidingWindowInit:
    def test_default_window(self):
        sw = SlidingWindow(limit=100)
        assert sw._limit == 100
        assert sw._window == 60.0

    def test_custom_window(self):
        sw = SlidingWindow(limit=50, window=30.0)
        assert sw._limit == 50
        assert sw._window == 30.0

    def test_limit_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            SlidingWindow(limit=0)

    def test_limit_negative_raises(self):
        with pytest.raises(ValueError, match="positive"):
            SlidingWindow(limit=-5)

    def test_limit_property(self):
        sw = SlidingWindow(limit=42)
        assert sw.limit == 42


class TestSlidingWindowTryAcquire:
    def test_within_limit(self):
        sw = SlidingWindow(limit=5, window=60.0)
        for _ in range(5):
            assert sw.try_acquire("key1") is True

    def test_exceeds_limit(self):
        sw = SlidingWindow(limit=3, window=60.0)
        for _ in range(3):
            assert sw.try_acquire("key1") is True
        assert sw.try_acquire("key1") is False

    def test_different_keys_independent(self):
        sw = SlidingWindow(limit=2, window=60.0)
        assert sw.try_acquire("key1") is True
        assert sw.try_acquire("key1") is True
        assert sw.try_acquire("key1") is False
        assert sw.try_acquire("key2") is True

    def test_eviction_of_old_entries(self):
        sw = SlidingWindow(limit=2, window=0.05)  # 50ms window
        assert sw.try_acquire("key1") is True
        assert sw.try_acquire("key1") is True
        assert sw.try_acquire("key1") is False
        time.sleep(0.06)
        assert sw.try_acquire("key1") is True


class TestSlidingWindowAcquireOrWait:
    def test_immediate_success(self):
        sw = SlidingWindow(limit=5, window=60.0)
        assert sw.acquire_or_wait("key1", timeout=1.0) is True

    def test_blocks_and_waits(self):
        sw = SlidingWindow(limit=2, window=0.05)
        for _ in range(2):
            sw.try_acquire("key1")
        assert sw.acquire_or_wait("key1", timeout=1.0) is True

    def test_timeout_expires(self):
        sw = SlidingWindow(limit=1, window=60.0)
        sw.try_acquire("key1")
        assert sw.acquire_or_wait("key1", timeout=0.01) is False

    def test_no_timeout_succeeds(self):
        sw = SlidingWindow(limit=1, window=0.02)
        sw.try_acquire("key1")
        assert sw.acquire_or_wait("key1", timeout=None) is True


class TestSlidingWindowReset:
    def test_reset_removes_key(self):
        sw = SlidingWindow(limit=1, window=60.0)
        sw.try_acquire("key1")
        assert sw.try_acquire("key1") is False
        sw.reset("key1")
        assert sw.try_acquire("key1") is True

    def test_reset_nonexistent_no_error(self):
        sw = SlidingWindow(limit=10)
        sw.reset("ghost")

    def test_reset_all(self):
        sw = SlidingWindow(limit=2, window=60.0)
        sw.try_acquire("key1")
        sw.try_acquire("key2")
        sw.reset_all()
        assert len(sw._windows) == 0
        assert sw.try_acquire("key1") is True


class TestSlidingWindowStats:
    def test_initial_stats(self):
        sw = SlidingWindow(limit=100, window=60.0)
        s = sw.stats()
        assert s["limit"] == 100
        assert s["window"] == 60.0
        assert s["active_keys"] == 0
        assert s["total_acquired"] == 0
        assert s["total_rejected"] == 0

    def test_stats_after_use(self):
        sw = SlidingWindow(limit=5, window=60.0)
        for _ in range(3):
            sw.try_acquire("key1")
        sw.try_acquire("key2")
        s = sw.stats()
        assert s["total_acquired"] == 4
        assert s["active_keys"] >= 1

    def test_stats_after_reject(self):
        sw = SlidingWindow(limit=2, window=60.0)
        for _ in range(2):
            sw.try_acquire("key1")
        sw.try_acquire("key1")  # rejected
        sw.try_acquire("key1")  # rejected
        s = sw.stats()
        assert s["total_acquired"] == 2
        assert s["total_rejected"] == 2
