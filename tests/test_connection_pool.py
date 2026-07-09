"""Tests for agentos.tools.connection_pool."""

import time

import pytest

from agentos.tools.connection_pool import (
    ConnectionPool,
    RateLimiter,
    ResourceQuota,
    create_connection_pool,
    create_rate_limiter,
    create_resource_quota,
)

# ============================================================================
# ConnectionPool Tests
# ============================================================================

class TestConnectionPool:
    def test_acquire_release(self):
        pool = ConnectionPool(lambda: {}, max_size=5)
        conn = pool.acquire()
        assert isinstance(conn, dict)
        assert pool.stats["active"] == 1
        pool.release(conn)
        assert pool.stats["active"] == 0

    def test_reuse(self):
        pool = ConnectionPool(lambda: {}, max_size=5)
        c1 = pool.acquire()
        pool.release(c1)
        c2 = pool.acquire()
        assert c1 is c2

    def test_warm_up(self):
        pool = ConnectionPool(lambda: {}, min_size=3, max_size=10)
        created = pool.warm_up()
        assert created == 3
        assert pool.stats["idle"] == 3

    def test_max_size_enforced(self):
        pool = ConnectionPool(lambda: {}, min_size=0, max_size=3)
        conns = [pool.acquire() for _ in range(3)]
        with pytest.raises(TimeoutError):
            pool.acquire(timeout=0.5)
        for c in conns:
            pool.release(c)
        pool.close()

    def test_health_check(self):
        def factory():
            return {"healthy": True}
        pool = ConnectionPool(
            factory,
            health_check=lambda c: c["healthy"],
            max_size=5,
        )
        c = pool.acquire()
        c["healthy"] = False
        pool.release(c)
        # Next acquire should create a new connection
        c2 = pool.acquire()
        assert c2 is not c
        assert pool.stats["failed_health_checks"] >= 1
        pool.close()

    def test_closer_called(self):
        closed = []
        def closer(c):
            closed.append(c)
        pool = ConnectionPool(lambda: {}, closer=closer, min_size=0, max_size=5)
        c = pool.acquire()
        pool.release(c)
        pool.close()
        assert len(closed) >= 1

    def test_context_manager(self):
        with ConnectionPool(lambda: {}, max_size=5) as pool:
            c = pool.acquire()
            assert isinstance(c, dict)
        assert pool._closed

    def test_evict_idle(self):
        pool = ConnectionPool(lambda: {}, min_size=0, max_size=5, idle_timeout=0.01)
        c = pool.acquire()
        pool.release(c)
        time.sleep(0.03)
        evicted = pool.evict_idle()
        assert evicted >= 1
        pool.close()

    def test_close_blocks_acquire(self):
        pool = ConnectionPool(lambda: {}, max_size=5)
        pool.close()
        with pytest.raises(RuntimeError):
            pool.acquire()

    def test_timeout(self):
        pool = ConnectionPool(lambda: {}, min_size=0, max_size=1)
        pool.acquire()  # take the only slot
        with pytest.raises(TimeoutError):
            pool.acquire(timeout=0.3)
        pool.close()


# ============================================================================
# RateLimiter Tests
# ============================================================================

class TestRateLimiter:
    def test_acquire_burst(self):
        rl = RateLimiter(rate=10, burst=5)
        assert rl.try_acquire(3) is True
        assert rl.try_acquire(2) is True
        assert rl.try_acquire(1) is False  # burst exhausted

    def test_acquire_blocking(self):
        rl = RateLimiter(rate=100, burst=1)
        start = time.monotonic()
        ok = rl.acquire(count=1, timeout=1.0)
        elapsed = time.monotonic() - start
        assert ok is True
        assert elapsed < 0.5  # rate=100 means 1 token every 0.01s

    def test_try_acquire_non_blocking(self):
        rl = RateLimiter(rate=0.1, burst=0)
        assert rl.try_acquire(1) is False
        assert rl.try_acquire(1) is False

    def test_stats(self):
        rl = RateLimiter(rate=10, burst=10)
        rl.try_acquire(5)
        s = rl.stats
        assert s["total_acquired"] == 5
        assert s["rate"] == 10
        assert s["burst"] == 10

    def test_refill_over_time(self):
        rl = RateLimiter(rate=50, burst=1)
        rl.try_acquire(1)  # drain
        assert rl.try_acquire(1) is False
        time.sleep(0.05)  # wait for ~2.5 tokens
        assert rl.try_acquire(1) is True

    def test_cant_exceed_burst(self):
        rl = RateLimiter(rate=1000, burst=5)
        time.sleep(0.5)  # would generate 500 tokens, capped at burst=5
        assert rl.try_acquire(6) is False
        assert rl.try_acquire(5) is True


# ============================================================================
# ResourceQuota Tests
# ============================================================================

class TestResourceQuota:
    def test_allocate_release(self):
        quota = ResourceQuota(global_limit=100)
        assert quota.allocate("comp_a", 30) is True
        assert quota.allocate("comp_b", 50) is True
        assert quota.allocate("comp_c", 30) is False  # exceeds 100
        quota.release("comp_a", 10)
        assert quota.allocate("comp_c", 20) is True  # now fits

    def test_set_limit(self):
        quota = ResourceQuota(global_limit=100)
        quota.allocate("x", 50)
        quota.set_limit("x", 20)
        assert quota.get_usage("x") == 20

    def test_stats(self):
        quota = ResourceQuota(global_limit=100)
        quota.allocate("a", 40)
        s = quota.stats
        assert s["global_limit"] == 100
        assert s["total_used"] == 40
        assert s["remaining"] == 60

    def test_total_used(self):
        quota = ResourceQuota(global_limit=100)
        assert quota.total_used == 0
        quota.allocate("a", 10)
        quota.allocate("b", 20)
        assert quota.total_used == 30

    def test_remaining(self):
        quota = ResourceQuota(global_limit=50)
        quota.allocate("a", 15)
        assert quota.remaining == 35


# ============================================================================
# Convenience Functions Tests
# ============================================================================

class TestConvenienceFunctions:
    def test_create_connection_pool(self):
        pool = create_connection_pool(lambda: [])
        c = pool.acquire()
        assert isinstance(c, list)
        pool.release(c)
        pool.close()

    def test_create_rate_limiter(self):
        rl = create_rate_limiter(rate=100, burst=10)
        assert rl.try_acquire(5) is True

    def test_create_resource_quota(self):
        q = create_resource_quota(global_limit=500)
        assert q.allocate("test", 100) is True
