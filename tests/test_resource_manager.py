"""Tests for agentos.core.resource_manager — 24 test cases."""

import asyncio

import pytest

from agentos.core.resource_manager import (
    ManagedResource,
    ResourceManager,
    ResourcePool,
    ResourceState,
    ResourceType,
    get_resource_manager,
)

# ============================================================================
# ManagedResource
# ============================================================================

class TestManagedResource:
    """Test ManagedResource wrapper."""

    @pytest.mark.asyncio
    async def test_wrap_with_close_fn(self):
        closed_flag = False

        class FakeConn:
            async def close(self):
                nonlocal closed_flag
                closed_flag = True

        conn = FakeConn()
        resource = ManagedResource(
            conn,
            close_fn=conn.close,
            name="test_conn",
            resource_type=ResourceType.CONNECTION,
        )
        assert resource.info.state == ResourceState.ACTIVE
        assert resource.info.name == "test_conn"

        await resource.close()
        assert closed_flag is True
        assert resource.info.state == ResourceState.CLOSED

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        close_count = 0

        class FakeConn:
            async def close(self):
                nonlocal close_count
                close_count += 1

        resource = ManagedResource(FakeConn())
        await resource.close()
        await resource.close()
        assert close_count == 1

    @pytest.mark.asyncio
    async def test_close_sync_fn(self):
        closed = False

        class FileResource:
            def close(self):
                nonlocal closed
                closed = True

        resource = ManagedResource(FileResource())
        await resource.close()
        assert closed is True

    @pytest.mark.asyncio
    async def test_health_check_via_ping(self):
        class Pool:
            async def ping(self):
                return True

        resource = ManagedResource(Pool())
        healthy = await resource.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        class DeadPool:
            async def health_check(self):
                return False

        resource = ManagedResource(DeadPool())
        healthy = await resource.health_check()
        assert healthy is False

    @pytest.mark.asyncio
    async def test_raw_access(self):
        obj = object()
        resource = ManagedResource(obj)
        assert resource.raw is obj

    @pytest.mark.asyncio
    async def test_health_check_closed_resource(self):
        resource = ManagedResource(object())
        await resource.close()
        healthy = await resource.health_check()
        assert healthy is False


# ============================================================================
# ResourcePool
# ============================================================================

class TestResourcePool:
    """Test ResourcePool."""

    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        created_count = 0

        def factory():
            nonlocal created_count
            created_count += 1
            return {"id": created_count}

        pool = ResourcePool(factory, max_size=5)
        await pool.start()

        async with pool.acquire() as resource:
            assert isinstance(resource, dict)
            assert "id" in resource

        assert created_count == 1

    @pytest.mark.asyncio
    async def test_max_size_limit(self):
        created = 0

        def factory():
            nonlocal created
            created += 1
            return {"id": created}

        pool = ResourcePool(factory, max_size=2)
        await pool.start()

        # Acquire 2, hold them
        r1_cm = pool.acquire()
        r2_cm = pool.acquire()
        r1 = await r1_cm.__aenter__()
        r2 = await r2_cm.__aenter__()

        # 3rd should block (we won't wait — just check count)
        assert created == 2

        await r1_cm.__aexit__(None, None, None)
        await r2_cm.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_min_size_prefill(self):
        created = 0

        def factory():
            nonlocal created
            created += 1
            return {"id": created}

        pool = ResourcePool(factory, max_size=10, min_size=3)
        await pool.start()
        assert created == 3

    @pytest.mark.asyncio
    async def test_close_pool(self):
        closed_objects = []

        class PoolObj:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True
                closed_objects.append(self)

        def factory():
            return PoolObj()

        pool = ResourcePool(factory, max_size=5, min_size=2)
        await pool.start()
        await asyncio.sleep(0.05)  # let close tasks run
        await pool.close()
        await asyncio.sleep(0.05)
        assert len(closed_objects) >= 2

    @pytest.mark.asyncio
    async def test_acquire_after_close(self):
        pool = ResourcePool(lambda: {"data": 1}, max_size=5)
        await pool.start()
        await pool.close()

        with pytest.raises(RuntimeError, match="closed"):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_stats(self):
        pool = ResourcePool(lambda: {"x": 1}, max_size=5, min_size=2)
        await pool.start()
        stats = pool.stats
        assert stats["total"] == 2
        assert stats["available"] == 2
        assert stats["max_size"] == 5
        assert stats["closed"] is False

    @pytest.mark.asyncio
    async def test_health_check(self):
        pool = ResourcePool(lambda: {"x": 1}, max_size=5)
        await pool.start()
        healthy = await pool.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_closed_health_check(self):
        pool = ResourcePool(lambda: {"x": 1}, max_size=5)
        await pool.start()
        await pool.close()
        healthy = await pool.health_check()
        assert healthy is False


# ============================================================================
# ResourceManager
# ============================================================================

class TestResourceManager:
    """Test ResourceManager central registry."""

    @pytest.mark.asyncio
    async def test_register_and_get(self):
        rm = ResourceManager()
        res = ManagedResource(object(), name="db")
        await rm.register("db", res)
        found = await rm.get("db")
        assert found is res

    @pytest.mark.asyncio
    async def test_get_missing(self):
        rm = ResourceManager()
        found = await rm.get("nonexistent")
        assert found is None

    @pytest.mark.asyncio
    async def test_unregister(self):
        rm = ResourceManager()
        res = ManagedResource(object(), name="tmp")
        await rm.register("tmp", res)
        removed = await rm.unregister("tmp")
        assert removed is res
        assert await rm.get("tmp") is None

    @pytest.mark.asyncio
    async def test_shutdown_order_lifo(self):
        rm = ResourceManager()
        close_order = []

        class OrderedResource:
            def __init__(self, name):
                self.name = name
                self.closed = False

            async def close(self):
                close_order.append(self.name)
                self.closed = True

        r1 = ManagedResource(OrderedResource("first"))
        r2 = ManagedResource(OrderedResource("second"))

        await rm.register("first", r1)
        await rm.register("second", r2)

        failures = await rm.shutdown()
        assert close_order == ["second", "first"]  # LIFO
        assert failures == []

    @pytest.mark.asyncio
    async def test_shutdown_with_failures(self):
        rm = ResourceManager()

        class FailingResource:
            async def close(self):
                raise RuntimeError("close error")

        await rm.register("failing", ManagedResource(FailingResource()))
        failures = await rm.shutdown()
        assert len(failures) == 1
        assert "failing" in failures[0]

    @pytest.mark.asyncio
    async def test_register_after_shutdown(self):
        rm = ResourceManager()
        await rm.shutdown()

        with pytest.raises(RuntimeError, match="shutting down"):
            await rm.register("late", ManagedResource(object()))

    @pytest.mark.asyncio
    async def test_health_report(self):
        rm = ResourceManager()

        class Healthy:
            async def health_check(self):
                return True
            async def close(self):
                pass

        class Unhealthy:
            async def health_check(self):
                return False
            async def close(self):
                pass

        await rm.register("good", ManagedResource(Healthy()))
        await rm.register("bad", ManagedResource(Unhealthy()))

        report = await rm.health_report()
        assert report["good"] is True
        assert report["bad"] is False

    @pytest.mark.asyncio
    async def test_finalizer(self):
        rm = ResourceManager()
        finalizer_ran = False

        def my_finalizer():
            nonlocal finalizer_ran
            finalizer_ran = True

        rm.add_finalizer(my_finalizer)
        failures = await rm.shutdown()
        assert finalizer_ran is True

    @pytest.mark.asyncio
    async def test_size(self):
        rm = ResourceManager()
        assert rm.size == 0
        await rm.register("a", ManagedResource(object()))
        assert rm.size == 1


# ============================================================================
# Global singleton
# ============================================================================

class TestGlobalSingleton:
    """Test get_resource_manager singleton."""

    def test_singleton_same_instance(self):
        rm1 = get_resource_manager()
        rm2 = get_resource_manager()
        assert rm1 is rm2
