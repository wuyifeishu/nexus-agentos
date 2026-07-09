"""Tests for agentos.core.rate_limiter — ~20 test cases."""

import asyncio

import pytest

from agentos.core.rate_limiter import (
    CompositeLimiter,
    ConcurrentLimiter,
    EndpointRateLimit,
    RateLimiter,
    RateLimitError,
    RateLimitRegistry,
    SlidingWindow,
    TokenBucket,
)


class TestTokenBucket:
    """Token bucket rate limiter."""

    def test_init_rejects_bad_params(self):
        with pytest.raises(ValueError):
            TokenBucket(rate=0, capacity=5)
        with pytest.raises(ValueError):
            TokenBucket(rate=1, capacity=0)

    @pytest.mark.asyncio
    async def test_acquire_with_tokens_available(self):
        tb = TokenBucket(rate=100, capacity=10)
        assert await tb.acquire() is True
        assert await tb.acquire(5) is True

    @pytest.mark.asyncio
    async def test_acquire_fails_when_insufficient(self):
        tb = TokenBucket(rate=1, capacity=1)
        assert await tb.acquire()  # consume the 1 token
        assert await tb.acquire() is False  # empty

    @pytest.mark.asyncio
    async def test_refill_over_time(self):
        tb = TokenBucket(rate=500, capacity=3)
        assert await tb.acquire(3)  # drain
        assert await tb.acquire() is False
        await asyncio.sleep(0.01)
        assert await tb.acquire() is True

    @pytest.mark.asyncio
    async def test_wait_and_acquire_with_timeout(self):
        tb = TokenBucket(rate=500, capacity=1)
        assert await tb.acquire()  # drain
        result = await tb.wait_and_acquire(timeout=0.02)
        assert result is True

    def test_fill_level(self):
        tb = TokenBucket(rate=100, capacity=10)
        assert tb.fill_level == 1.0

    @pytest.mark.asyncio
    async def test_available_tokens(self):
        tb = TokenBucket(rate=1, capacity=10)
        initial = tb.available_tokens
        await tb.acquire(3)
        assert tb.available_tokens == pytest.approx(initial - 3)


class TestSlidingWindow:
    """Sliding window rate limiter."""

    def test_init_rejects_bad_params(self):
        with pytest.raises(ValueError):
            SlidingWindow(max_requests=0, window_seconds=1)
        with pytest.raises(ValueError):
            SlidingWindow(max_requests=5, window_seconds=0)

    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        sw = SlidingWindow(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert await sw.acquire() is True
        assert await sw.acquire() is False

    @pytest.mark.asyncio
    async def test_current_count_and_remaining(self):
        sw = SlidingWindow(max_requests=10, window_seconds=60)
        for _ in range(3):
            await sw.acquire()
        assert sw.current_count == 3
        assert sw.remaining == 7

    @pytest.mark.asyncio
    async def test_window_expiry(self):
        sw = SlidingWindow(max_requests=3, window_seconds=0.01)
        for _ in range(3):
            await sw.acquire()
        assert await sw.acquire() is False
        await asyncio.sleep(0.02)
        assert await sw.acquire() is True


class TestConcurrentLimiter:
    """Concurrent execution limiter."""

    @pytest.mark.asyncio
    async def test_available_reflects_slots(self):
        cl = ConcurrentLimiter(max_concurrent=3)
        assert cl.available == 3
        await cl.acquire()
        assert cl.available == 2

    @pytest.mark.asyncio
    async def test_release_restores_slot(self):
        cl = ConcurrentLimiter(max_concurrent=2)
        await cl.acquire()
        await cl.acquire()
        assert cl.available == 0
        cl.release()
        assert cl.available == 1


class TestCompositeLimiter:
    """Composite limiter chains."""

    @pytest.mark.asyncio
    async def test_all_must_pass(self):
        sw = SlidingWindow(max_requests=2, window_seconds=60)
        comp = CompositeLimiter([sw])

        assert await comp.acquire() is True
        assert await comp.acquire() is True
        assert await comp.acquire() is False


class TestRateLimiter:
    """Unified rate limiter."""

    @pytest.mark.asyncio
    async def test_context_manager_releases(self):
        rl = RateLimiter.concurrent("test", max_concurrent=1)
        async with rl:
            assert rl.strategy.available == 0
        assert rl.strategy.available == 1

    @pytest.mark.asyncio
    async def test_rate_limit_error_on_sliding_window(self):
        sw = SlidingWindow(max_requests=1, window_seconds=60)
        rl = RateLimiter("test", strategy=sw)
        await sw.acquire()  # exhaust
        with pytest.raises(RateLimitError):
            async with rl:
                pass

    def test_factory_methods(self):
        rl = RateLimiter.token_bucket("api", rate=10, capacity=20)
        assert rl.name == "api"
        assert isinstance(rl.strategy, TokenBucket)

        rl2 = RateLimiter.concurrent("db", max_concurrent=5)
        assert isinstance(rl2.strategy, ConcurrentLimiter)


class TestRateLimitRegistry:
    """Per-endpoint registry."""

    @pytest.mark.asyncio
    async def test_configure_endpoint(self):
        reg = RateLimitRegistry()
        spec = EndpointRateLimit(
            endpoint="/api/chat",
            requests_per_second=10,
            concurrent=5,
        )
        limiter = await reg.configure(spec)
        assert limiter.name == "/api/chat"

    @pytest.mark.asyncio
    async def test_unknown_endpoint_passes(self):
        reg = RateLimitRegistry()
        assert await reg.acquire("/nonexistent") is True
