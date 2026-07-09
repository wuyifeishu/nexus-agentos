"""Tests for agentos.core.rate_limiter — TokenBucket, SlidingWindow, ConcurrentLimiter, etc."""

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

# ============================================================================
# TokenBucket
# ============================================================================

class TestTokenBucket:
    def test_init_defaults(self):
        tb = TokenBucket(rate=10.0, capacity=100)
        assert tb.rate == 10.0
        assert tb.capacity == 100

    def test_invalid_rate(self):
        with pytest.raises(ValueError, match="rate"):
            TokenBucket(rate=0, capacity=10)
        with pytest.raises(ValueError, match="rate"):
            TokenBucket(rate=-1, capacity=10)

    def test_invalid_capacity(self):
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(rate=10, capacity=0)
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(rate=10, capacity=-5)

    @pytest.mark.asyncio
    async def test_acquire_initial_tokens(self):
        tb = TokenBucket(rate=1.0, capacity=5)
        assert await tb.acquire() is True
        assert await tb.acquire() is True
        assert await tb.acquire() is True

    @pytest.mark.asyncio
    async def test_acquire_exhausted(self):
        tb = TokenBucket(rate=0.001, capacity=2)
        await tb.acquire()
        await tb.acquire()
        assert await tb.acquire() is False

    @pytest.mark.asyncio
    async def test_refill_over_time(self):
        tb = TokenBucket(rate=100.0, capacity=10)
        # Use all tokens
        for _ in range(10):
            assert await tb.acquire()
        assert await tb.acquire() is False

        # Wait for refill
        await asyncio.sleep(0.05)
        assert await tb.acquire() is True

    @pytest.mark.asyncio
    async def test_wait_and_acquire(self):
        tb = TokenBucket(rate=200.0, capacity=2)
        for _ in range(2):
            await tb.acquire()

        # Should wait briefly and succeed
        result = await tb.wait_and_acquire(timeout=2.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_and_acquire_timeout(self):
        tb = TokenBucket(rate=0.1, capacity=1)
        await tb.acquire()

        result = await tb.wait_and_acquire(timeout=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_available_tokens(self):
        tb = TokenBucket(rate=1.0, capacity=100)
        assert tb.available_tokens == 100.0
        await tb.acquire(tokens=30)
        assert tb.available_tokens == 70.0

    def test_fill_level(self):
        tb = TokenBucket(rate=1.0, capacity=100)
        assert tb.fill_level == 1.0


# ============================================================================
# SlidingWindow
# ============================================================================

class TestSlidingWindow:
    def test_init(self):
        sw = SlidingWindow(max_requests=5, window_seconds=10.0)
        assert sw.max_requests == 5
        assert sw.window_seconds == 10.0

    def test_invalid_max_requests(self):
        with pytest.raises(ValueError):
            SlidingWindow(max_requests=0, window_seconds=1)

    def test_invalid_window(self):
        with pytest.raises(ValueError):
            SlidingWindow(max_requests=5, window_seconds=0)

    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        sw = SlidingWindow(max_requests=3, window_seconds=60)
        assert await sw.acquire() is True
        assert await sw.acquire() is True
        assert await sw.acquire() is True

    @pytest.mark.asyncio
    async def test_acquire_exceeds_limit(self):
        sw = SlidingWindow(max_requests=2, window_seconds=60)
        await sw.acquire()
        await sw.acquire()
        assert await sw.acquire() is False

    @pytest.mark.asyncio
    async def test_current_count(self):
        sw = SlidingWindow(max_requests=10, window_seconds=60)
        await sw.acquire()
        await sw.acquire()
        assert sw.current_count == 2

    def test_remaining(self):
        sw = SlidingWindow(max_requests=10, window_seconds=60)
        assert sw.remaining == 10


# ============================================================================
# ConcurrentLimiter
# ============================================================================

class TestConcurrentLimiter:
    def test_init(self):
        cl = ConcurrentLimiter(max_concurrent=5)
        assert cl.available == 5

    def test_invalid_max(self):
        with pytest.raises(ValueError):
            ConcurrentLimiter(max_concurrent=0)

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        cl = ConcurrentLimiter(max_concurrent=2)
        assert await cl.acquire() is True
        assert await cl.acquire() is True
        assert cl.available == 0
        cl.release()
        assert cl.available == 1

    @pytest.mark.asyncio
    async def test_acquire_blocking(self):
        cl = ConcurrentLimiter(max_concurrent=1)
        await cl.acquire()

        # Acquire in task that will block
        async def blocked():
            return await cl.acquire()

        task = asyncio.create_task(blocked())
        await asyncio.sleep(0.1)
        assert not task.done()

        cl.release()
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is True


# ============================================================================
# CompositeLimiter
# ============================================================================

class TestCompositeLimiter:
    @pytest.mark.asyncio
    async def test_all_pass(self):
        tb = TokenBucket(rate=100, capacity=10)
        sw = SlidingWindow(max_requests=10, window_seconds=60)
        cl = ConcurrentLimiter(max_concurrent=5)
        composite = CompositeLimiter([tb, sw, cl])
        assert await composite.acquire() is True

    @pytest.mark.asyncio
    async def test_one_fails(self):
        tb = TokenBucket(rate=0.001, capacity=1)
        sw = SlidingWindow(max_requests=10, window_seconds=60)
        await tb.acquire()  # exhaust token bucket
        composite = CompositeLimiter([tb, sw])
        assert await composite.acquire() is False


# ============================================================================
# RateLimitError
# ============================================================================

class TestRateLimitError:
    def test_message(self):
        err = RateLimitError("Limit exceeded: api")
        assert "api" in str(err)


# ============================================================================
# RateLimiter — context manager
# ============================================================================

class TestRateLimiterCM:
    @pytest.mark.asyncio
    async def test_async_context_manager_success(self):
        rl = RateLimiter(name="test", strategy=TokenBucket(rate=10, capacity=10))
        async with rl:
            pass

    @pytest.mark.asyncio
    async def test_async_context_manager_rejected(self):
        tb = TokenBucket(rate=0.001, capacity=1)
        await tb.acquire()
        rl = RateLimiter(name="test", strategy=tb)
        with pytest.raises(RateLimitError):
            async with rl:
                pass

    @pytest.mark.asyncio
    async def test_concurrent_releases_on_exit(self):
        cl = ConcurrentLimiter(max_concurrent=2)
        rl = RateLimiter(name="test", strategy=cl)
        async with rl:
            assert cl.available == 1
        assert cl.available == 2  # released on exit


# ============================================================================
# RateLimiter — factory methods
# ============================================================================

class TestRateLimiterFactories:
    def test_token_bucket_factory(self):
        rl = RateLimiter.token_bucket("api", rate=5.0, capacity=20)
        assert rl.name == "api"
        assert isinstance(rl.strategy, TokenBucket)
        assert rl.strategy.rate == 5.0
        assert rl.strategy.capacity == 20

    def test_sliding_window_factory(self):
        rl = RateLimiter.sliding_window("api", max_requests=100, window_seconds=60)
        assert rl.name == "api"
        assert isinstance(rl.strategy, SlidingWindow)
        assert rl.strategy.max_requests == 100

    def test_concurrent_factory(self):
        rl = RateLimiter.concurrent("api", max_concurrent=10)
        assert rl.name == "api"
        assert isinstance(rl.strategy, ConcurrentLimiter)


# ============================================================================
# EndpointRateLimit
# ============================================================================

class TestEndpointRateLimit:
    def test_defaults(self):
        erl = EndpointRateLimit(endpoint="/api/v1")
        assert erl.endpoint == "/api/v1"
        assert erl.requests_per_second is None
        assert erl.concurrent is None
        assert erl.burst == 1

    def test_full_spec(self):
        erl = EndpointRateLimit(
            endpoint="/api/v1",
            requests_per_second=10.0,
            requests_per_minute=600,
            concurrent=5,
            burst=20,
        )
        assert erl.requests_per_second == 10.0
        assert erl.requests_per_minute == 600
        assert erl.concurrent == 5
        assert erl.burst == 20


# ============================================================================
# RateLimitRegistry
# ============================================================================

class TestRateLimitRegistry:
    @pytest.mark.asyncio
    async def test_configure_single_limiter(self):
        reg = RateLimitRegistry()
        spec = EndpointRateLimit(endpoint="/api", requests_per_second=10.0, burst=5)
        limiter = await reg.configure(spec)
        assert limiter.name == "/api"
        assert isinstance(limiter.strategy, TokenBucket)

    @pytest.mark.asyncio
    async def test_configure_composite(self):
        reg = RateLimitRegistry()
        spec = EndpointRateLimit(
            endpoint="/api",
            requests_per_second=10.0,
            requests_per_minute=600,
            concurrent=5,
        )
        limiter = await reg.configure(spec)
        assert limiter.name == "/api"
        assert isinstance(limiter.strategy, CompositeLimiter)

    @pytest.mark.asyncio
    async def test_get_existing(self):
        reg = RateLimitRegistry()
        await reg.configure(EndpointRateLimit(endpoint="/api", requests_per_second=1.0))
        limiter = await reg.get("/api")
        assert limiter is not None
        assert limiter.name == "/api"

    @pytest.mark.asyncio
    async def test_get_missing(self):
        reg = RateLimitRegistry()
        assert await reg.get("/nonexistent") is None

    @pytest.mark.asyncio
    async def test_acquire_existing(self):
        reg = RateLimitRegistry()
        await reg.configure(EndpointRateLimit(endpoint="/api", requests_per_second=100.0, burst=100))
        result = await reg.acquire("/api")
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_missing(self):
        reg = RateLimitRegistry()
        result = await reg.acquire("/nonexistent")
        assert result is True

    @pytest.mark.asyncio
    async def test_configure_with_burst_one(self):
        reg = RateLimitRegistry()
        spec = EndpointRateLimit(endpoint="/api", requests_per_second=5.0)
        limiter = await reg.configure(spec)
        assert isinstance(limiter.strategy, TokenBucket)
        assert limiter.strategy.capacity == 1  # burst=1 default
