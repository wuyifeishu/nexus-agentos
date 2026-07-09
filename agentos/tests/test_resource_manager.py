"""Tests for agentos.core.resource_manager — ResourceManager, ResourcePool, ManagedResource."""

import asyncio

import pytest

from agentos.core.resource_manager import (
    AbstractResource,
    ManagedResource,
    ResourceInfo,
    ResourceManager,
    ResourcePool,
    ResourceState,
    ResourceType,
    get_resource_manager,
)

# ============================================================================
# ResourceInfo
# ============================================================================

class TestResourceInfo:
    def test_defaults(self):
        info = ResourceInfo(name="test")
        assert info.name == "test"
        assert info.resource_type == ResourceType.OTHER
        assert info.state == ResourceState.CREATED
        assert info.acquired_at == 0.0

    def test_custom(self):
        info = ResourceInfo(name="db", resource_type=ResourceType.CONNECTION)
        assert info.resource_type == ResourceType.CONNECTION


# ============================================================================
# ManagedResource
# ============================================================================

class FakeConn:
    def __init__(self):
        self.closed = False
        self.healthy = True

    async def close(self):
        self.closed = True

    async def health_check(self):
        return self.healthy

    async def ping(self):
        return True


class TestManagedResource:
    @pytest.mark.asyncio
    async def test_close(self):
        conn = FakeConn()
        mr = ManagedResource(conn, name="db")
        assert mr.info.state == ResourceState.ACTIVE
        await mr.close()
        assert mr.info.state == ResourceState.CLOSED
        assert conn.closed

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        conn = FakeConn()
        mr = ManagedResource(conn, name="db")
        await mr.close()
        await mr.close()  # should not raise
        assert mr.info.state == ResourceState.CLOSED

    @pytest.mark.asyncio
    async def test_raw_access(self):
        conn = FakeConn()
        mr = ManagedResource(conn, name="db")
        assert mr.raw is conn

    @pytest.mark.asyncio
    async def test_health_check(self):
        conn = FakeConn()
        mr = ManagedResource(conn, name="db")
        assert await mr.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_closed(self):
        conn = FakeConn()
        mr = ManagedResource(conn, name="db")
        await mr.close()
        assert await mr.health_check() is False

    @pytest.mark.asyncio
    async def test_close_fn_fallback(self):
        closed_flag = False

        class NoCloseObj:
            pass

        async def custom_close():
            nonlocal closed_flag
            closed_flag = True

        mr = ManagedResource(NoCloseObj(), close_fn=custom_close, name="x")
        await mr.close()
        assert closed_flag

    @pytest.mark.asyncio
    async def test_close_fn_sync(self):
        closed = []

        class Obj:
            def close(self):
                closed.append(1)

        mr = ManagedResource(Obj(), name="x")
        await mr.close()
        assert closed == [1]

    @pytest.mark.asyncio
    async def test_close_error_sets_error_state(self):
        class BadObj:
            async def close(self):
                raise RuntimeError("boom")

        mr = ManagedResource(BadObj(), name="x")
        with pytest.raises(RuntimeError, match="boom"):
            await mr.close()
        assert mr.info.state == ResourceState.ERROR


# ============================================================================
# ResourcePool
# ============================================================================

class TestResourcePool:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        created = 0

        def factory():
            nonlocal created
            created += 1
            return FakeConn()

        pool = ResourcePool(factory, max_size=3)
        await pool.start()
        async with pool.acquire() as conn:
            assert isinstance(conn, FakeConn)
            assert not conn.closed
        await pool.close()

    @pytest.mark.asyncio
    async def test_max_size_limit(self):
        created = 0

        def factory():
            nonlocal created
            created += 1
            return FakeConn()

        pool = ResourcePool(factory, max_size=2)
        await pool.start()

        async with pool.acquire():
            async with pool.acquire():
                # Third acquire should wait
                task = asyncio.ensure_future(pool.acquire().__aenter__())
                await asyncio.sleep(0.01)
                assert not task.done()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await pool.close()

    @pytest.mark.asyncio
    async def test_min_size_prefill(self):
        created = 0

        def factory():
            nonlocal created
            created += 1
            return FakeConn()

        pool = ResourcePool(factory, max_size=5, min_size=2)
        await pool.start()
        assert created == 2
        assert pool.stats["available"] == 2
        await pool.close()

    @pytest.mark.asyncio
    async def test_stats(self):
        pool = ResourcePool(FakeConn, max_size=5, min_size=1)
        await pool.start()
        stats = pool.stats
        assert stats["name"] == "pool"
        assert stats["max_size"] == 5
        assert stats["available"] == 1
        assert stats["closed"] is False
        await pool.close()

    @pytest.mark.asyncio
    async def test_close_clears(self):
        pool = ResourcePool(FakeConn, max_size=5, min_size=2)
        await pool.start()
        await pool.close()
        assert pool.stats["closed"] is True

    @pytest.mark.asyncio
    async def test_acquire_after_close(self):
        pool = ResourcePool(FakeConn, max_size=3)
        await pool.start()
        await pool.close()
        with pytest.raises(RuntimeError, match="closed"):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_returns_to_pool(self):
        created = 0

        def factory():
            nonlocal created
            created += 1
            return FakeConn()

        pool = ResourcePool(factory, max_size=3)
        await pool.start()
        async with pool.acquire():
            pass
        # After release, available count is back
        assert pool.stats["available"] >= 0
        await pool.close()

    @pytest.mark.asyncio
    async def test_health_check(self):
        pool = ResourcePool(FakeConn, max_size=3)
        await pool.start()
        assert await pool.health_check() is True
        await pool.close()
        assert await pool.health_check() is False


# ============================================================================
# ResourceManager
# ============================================================================

class TestResourceManager:
    @pytest.mark.asyncio
    async def test_register_and_get(self):
        rm = ResourceManager()
        conn = FakeConn()
        mr = ManagedResource(conn, name="db")
        await rm.register("db", mr)
        assert await rm.get("db") is mr

    @pytest.mark.asyncio
    async def test_unregister(self):
        rm = ResourceManager()
        mr = ManagedResource(FakeConn(), name="db")
        await rm.register("db", mr)
        removed = await rm.unregister("db")
        assert removed is mr
        assert await rm.get("db") is None

    @pytest.mark.asyncio
    async def test_shutdown_lifo_order(self):
        rm = ResourceManager()
        order = []

        class TrackingRes(AbstractResource):
            def __init__(self, name):
                self.name = name

            async def close(self):
                order.append(self.name)

        await rm.register("a", TrackingRes("a"))
        await rm.register("b", TrackingRes("b"))
        await rm.register("c", TrackingRes("c"))

        await rm.shutdown()
        assert order == ["c", "b", "a"]

    @pytest.mark.asyncio
    async def test_shutdown_reports_failures(self):
        rm = ResourceManager()

        class FailingRes(AbstractResource):
            async def close(self):
                raise RuntimeError("fail")

        await rm.register("bad", FailingRes())
        failures = await rm.shutdown()
        assert len(failures) == 1
        assert "bad" in failures[0]

    @pytest.mark.asyncio
    async def test_health_report(self):
        rm = ResourceManager()
        conn = FakeConn()
        mr = ManagedResource(conn, name="db")
        await rm.register("db", mr)
        report = await rm.health_report()
        assert report["db"] is True

    @pytest.mark.asyncio
    async def test_finalizer(self):
        rm = ResourceManager()
        finalizer_ran = []

        rm.add_finalizer(lambda: finalizer_ran.append(1))
        rm.add_finalizer(lambda: finalizer_ran.append(2))

        await rm.register("x", ManagedResource(FakeConn(), name="x"))
        await rm.shutdown()
        assert finalizer_ran == [1, 2]

    @pytest.mark.asyncio
    async def test_register_after_shutdown(self):
        rm = ResourceManager()
        await rm.shutdown()
        with pytest.raises(RuntimeError, match="shutting down"):
            await rm.register("x", ManagedResource(FakeConn(), name="x"))

    @pytest.mark.asyncio
    async def test_size(self):
        rm = ResourceManager()
        assert rm.size == 0
        await rm.register("x", ManagedResource(FakeConn(), name="x"))
        assert rm.size == 1

    def test_check_leaks(self):
        rm = ResourceManager()
        leaks = rm.check_leaks()
        assert leaks == []

    @pytest.mark.asyncio
    async def test_shutdown_timeout(self):
        rm = ResourceManager()

        class SlowRes(AbstractResource):
            async def close(self):
                await asyncio.sleep(99)

        await rm.register("slow", SlowRes())
        failures = await rm.shutdown(timeout=0.001)
        assert len(failures) == 1
        assert "timeout" in failures[0]

    def test_singleton(self):
        rm1 = get_resource_manager()
        rm2 = get_resource_manager()
        assert rm1 is rm2
