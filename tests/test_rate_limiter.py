"""Tests for agentos.tools.rate_limiter — TokenBucket, SlidingWindow."""

import time

import pytest

from agentos.tools.rate_limiter import (
    RateLimitExceeded,
    SlidingWindow,
    TokenBucket,
)


class TestRateLimitExceeded:
    def test_attrs(self):
        exc = RateLimitExceeded("mykey", 10, 60)
        assert exc.key == "mykey"
        assert exc.limit == 10
        assert exc.window == 60
        assert "mykey" in str(exc)


class TestTokenBucket:
    def test_init_defaults(self):
        tb = TokenBucket(rate=5.0)
        assert tb.rate == 5.0

    def test_init_negative_rate(self):
        with pytest.raises(ValueError):
            TokenBucket(rate=0)

    def test_init_with_burst(self):
        tb = TokenBucket(rate=5.0, burst=20.0)

    def test_acquire_burst(self):
        tb = TokenBucket(rate=10.0, burst=100.0)
        assert tb.try_acquire("key1", tokens=50.0) is True

    def test_acquire_exact_limit(self):
        tb = TokenBucket(rate=10.0, burst=0.5)
        assert tb.try_acquire("key1", tokens=0.5) is True
        assert tb.try_acquire("key1", tokens=0.5) is False

    def test_acquire_refill_over_time(self):
        tb = TokenBucket(rate=100.0, burst=1.0)
        assert tb.try_acquire("key1", tokens=1.0) is True
        assert tb.try_acquire("key1", tokens=1.0) is False
        time.sleep(0.02)
        assert tb.try_acquire("key1", tokens=1.0) is True

    def test_acquire_or_wait_timeout(self):
        tb = TokenBucket(rate=10.0, burst=0.5)
        tb.try_acquire("key1", tokens=0.5)
        result = tb.acquire_or_wait("key1", timeout=0.1, tokens=1.0)
        assert result is False

    def test_acquire_or_wait_success(self):
        tb = TokenBucket(rate=500.0, burst=5.0)
        result = tb.acquire_or_wait("key1", timeout=1.0, tokens=2.0)
        assert result is True

    def test_reset(self):
        tb = TokenBucket(rate=10.0, burst=0.5)
        assert tb.try_acquire("key1", tokens=0.5) is True
        assert tb.try_acquire("key1", tokens=0.5) is False
        tb.reset("key1")
        assert tb.try_acquire("key1", tokens=0.5) is True

    def test_reset_all(self):
        tb = TokenBucket(rate=10.0, burst=0.5)
        tb.try_acquire("a", tokens=0.5)
        tb.try_acquire("b", tokens=0.5)
        tb.reset_all()
        assert tb.try_acquire("a", tokens=0.5) is True
        assert tb.try_acquire("b", tokens=0.5) is True

    def test_stats(self):
        tb = TokenBucket(rate=5.0, burst=10.0)
        tb.try_acquire("k1")
        stats = tb.stats()
        assert stats["rate"] == 5.0
        assert stats["burst"] == 10.0
        assert stats["total_acquired"] >= 1

    def test_acquire_no_wait(self):
        """acquire_or_wait without timeout block."""
        tb = TokenBucket(rate=500.0, burst=10.0)
        assert tb.acquire_or_wait("k", timeout=None) is True

    def test_stats_rejected(self):
        tb = TokenBucket(rate=0.1, burst=0.0)
        tb.try_acquire("k", tokens=1.0)
        stats = tb.stats()
        assert stats["total_rejected"] >= 1


class TestSlidingWindow:
    def test_init(self):
        sw = SlidingWindow(limit=10)
        assert sw.limit == 10

    def test_init_negative(self):
        with pytest.raises(ValueError):
            SlidingWindow(limit=0)

    def test_acquire_within_limit(self):
        sw = SlidingWindow(limit=5)
        for _ in range(5):
            assert sw.try_acquire("k") is True

    def test_acquire_exceeds_limit(self):
        sw = SlidingWindow(limit=2)
        assert sw.try_acquire("k") is True
        assert sw.try_acquire("k") is True
        assert sw.try_acquire("k") is False

    def test_expired_entries_freed(self):
        sw = SlidingWindow(limit=1, window=0.05)
        assert sw.try_acquire("k") is True
        assert sw.try_acquire("k") is False
        time.sleep(0.1)
        assert sw.try_acquire("k") is True

    def test_acquire_or_wait_timeout(self):
        sw = SlidingWindow(limit=1)
        sw.try_acquire("k")
        result = sw.acquire_or_wait("k", timeout=0.1)
        assert result is False

    def test_acquire_or_wait_success(self):
        sw = SlidingWindow(limit=10)
        result = sw.acquire_or_wait("k", timeout=1.0)
        assert result is True

    def test_reset(self):
        sw = SlidingWindow(limit=1)
        sw.try_acquire("k")
        sw.reset("k")
        assert sw.try_acquire("k") is True

    def test_reset_all(self):
        sw = SlidingWindow(limit=1)
        sw.try_acquire("a")
        sw.try_acquire("b")
        sw.reset_all()
        assert sw.try_acquire("a") is True
        assert sw.try_acquire("b") is True

    def test_stats(self):
        sw = SlidingWindow(limit=100, window=60)
        sw.try_acquire("x")
        stats = sw.stats()
        assert stats["limit"] == 100
        assert stats["window"] == 60
        assert stats["total_acquired"] >= 1

    def test_stats_rejected(self):
        sw = SlidingWindow(limit=1)
        sw.try_acquire("k")
        sw.try_acquire("k")
        stats = sw.stats()
        assert stats["total_rejected"] >= 1
