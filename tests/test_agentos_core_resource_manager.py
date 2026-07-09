"""Tests for agentos.core.resource_manager — Resource lifecycle management."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

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
# ResourceInfo / Enums
# ============================================================================

class TestResourceInfo:
    def test_defaults(self):
        info = ResourceInfo(name="test")
        assert info.name == "test"
        assert info.resource_type == ResourceType.OTHER
        assert info.state == ResourceState.CREATED
        assert info.acquired_at == 0.0
        assert info.released_at == 0.0
        assert info.leak_warn_threshold == 300.0


class TestEnums:
    def test_resource_state_values(self):
        assert ResourceState.CREATED.value == "created"
        assert ResourceState.ACTIVE.value == "active"
        assert ResourceState.CLOSED.value == "closed"

    def test_resource_type_values(self):
        assert ResourceType.CONNECTION.value == "connection"
        assert ResourceType.FILE.value == "file"


# ============================================================================
# ManagedResource
# ============================================================================

class TestManagedResource:
    @pytest.fixture
    def close_log(self):
        return []

    @pytest.fixture
    def make_resource(self, close_log):
        def _make(name="test-resource", close_fn=None):
            obj = MagicMock()
            if close_fn:
                obj.close = close_fn
            else:
                obj.close = MagicMock()
            return ManagedResource(obj, name=name, resource_type=ResourceType.CONNECTION)
        return _make

    @pytest.mark.asyncio
    async def test_creation_and_raw_access(self, make_resource):
        mr = make_resource("conn-1")
        assert mr.info.name == "conn-1"
        assert mr.info.state == ResourceState.ACTIVE
        assert mr.info.resource_type == ResourceType.CONNECTION
        assert mr.raw is not None

    @pytest.mark.asyncio
    async def test_close_sets_state(self, make_resource):
        mr = make_resource()
        await mr.close()
        assert mr.info.state == ResourceState.CLOSED

    @pytest.mark.asyncio
    async def test_double_close_is_idempotent(self, make_resource):
        mr = make_resource()
        await mr.close()
        await mr.close()
        assert mr.info.state == ResourceState.CLOSED

    @pytest.mark.asyncio
    async def test_close_calls_underlying_close(self, make_resource):
        obj = MagicMock()
        obj.close = MagicMock()
        mr = ManagedResource(obj, name="test")
        await mr.close()
        obj.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_with_async_close(self, make_resource):
        async def async_close():
            pass
        obj = MagicMock()
        obj.close = AsyncMock()
        mr = ManagedResource(obj, name="test")
        await mr.close()
        obj.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_error_state(self, make_resource):
        obj = MagicMock()
        obj.close = MagicMock(side_effect=RuntimeError("boom"))
        mr = ManagedResource(obj, name="bad")
        with pytest.raises(RuntimeError):
            await mr.close()
        assert mr.info.state == ResourceState.ERROR

    @pytest.mark.asyncio
    async def test_health_check_default(self, make_resource):
        mr = make_resource()
        assert await mr.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_after_close(self, make_resource):
        mr = make_resource()
        await mr.close()
        assert await mr.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_with_health_fn(self):
        obj = MagicMock()
        obj.close = MagicMock()
        obj.health_check = MagicMock(return_value=True)
        mr = ManagedResource(obj, name="test")
        assert await mr.health_check() is True
        obj.health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_with_ping(self):
        obj = MagicMock()
        obj.close = MagicMock()
        obj.ping = MagicMock(return_value=True)
        mr = ManagedResource(obj, name="test")
        assert await mr.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_error(self):
        obj = MagicMock()
        obj.close = MagicMock()
        obj.health_check = MagicMock(side_effect=RuntimeError("boom"))
        mr = ManagedResource(obj, name="test")
        assert await mr.health_check() is False

    @pytest.mark.asyncio
    async def test_on_leak_detected_logs(self, caplog):
        obj = MagicMock()
        obj.close = MagicMock()
        mr = ManagedResource(obj, name="leaky")
        mr.on_leak_detected()
        assert "leak" in caplog.text.lower()


# ============================================================================
# ResourcePool
# ============================================================================

class TestResourcePool:
    @pytest.fixture
    def factory(self):
        class FakeConn:
            _close_calls = 0

            def __init__(self, id_):
                self.id = id_

            async def close(self):
                FakeConn._close_calls += 1

            def ping(self):
                return True

        def _make():
            FakeConn._close_calls = 0
            counter = [0]

            def create():
                counter[0] += 1
                return FakeConn(counter[0])

            return create, FakeConn

        return _make

    @pytest.mark.asyncio
    async def test_acquire_and_return(self, factory):
        create, FakeConn = factory()
        pool = ResourcePool(factory=create, max_size=3)
        await pool.start()

        async with pool.acquire() as conn:
            assert isinstance(conn, FakeConn)
            assert conn.id == 1

        # Should be returned
        async with pool.acquire() as conn:
            assert conn.id == 1  # Reused

        await pool.close()

    @pytest.mark.asyncio
    async def test_max_size_limit(self, factory):
        create, FakeConn = factory()
        pool = ResourcePool(factory=create, max_size=2)
        await pool.start()

        async with pool.acquire() as c1:
            async with pool.acquire() as c2:
                assert c1.id != c2.id
                assert pool.stats["in_use"] == 2

        await pool.close()

    @pytest.mark.asyncio
    async def test_prefill_min_size(self, factory):
        create, FakeConn = factory()
        pool = ResourcePool(factory=create, min_size=3, max_size=5)
        await pool.start()

        # Should have 3 pre-created
        assert pool.stats["available"] == 3
        assert pool.stats["total"] == 3

        await pool.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self, factory):
        create, FakeConn = factory()
        pool = ResourcePool(factory=create, max_size=3)
        await pool.start()
        await pool.close()
        await pool.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_acquire_after_close(self, factory):
        create, FakeConn = factory()
        pool = ResourcePool(factory=create, max_size=3)
        await pool.start()
        await pool.close()

        with pytest.raises(RuntimeError, match="closed"):
            async with pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_stats(self, factory):
        create, FakeConn = factory()
        pool = ResourcePool(factory=create, max_size=5, name="test-pool")
        await pool.start()

        stats = pool.stats
        assert stats["name"] == "test-pool"
        assert stats["max_size"] == 5
        assert not stats["closed"]

        await pool.close()

    @pytest.mark.asyncio
    async def test_health_check(self, factory):
        create, FakeConn = factory()
        pool = ResourcePool(factory=create, max_size=3)
        await pool.start()
        assert await pool.health_check() is True
        await pool.close()
        assert await pool.health_check() is False

    @pytest.mark.asyncio
    async def test_async_factory(self):
        class FakeConn:
            async def close(self):
                pass

        async def create():
            return FakeConn()

        pool = ResourcePool(factory=create, max_size=2)
        await pool.start()
        async with pool.acquire() as conn:
            assert isinstance(conn, FakeConn)
        await pool.close()


# ============================================================================
# ResourceManager
# ============================================================================

class TestResourceManager:
    @pytest.fixture
    def rm(self):
        return ResourceManager()

    @pytest.fixture
    def make_managed(self):
        def _make(name="res"):
            obj = MagicMock()
            obj.close = AsyncMock()
            return ManagedResource(obj, name=name)
        return _make

    @pytest.mark.asyncio
    async def test_register_and_get(self, rm, make_managed):
        mr = make_managed("db")
        await rm.register("db", mr)
        found = await rm.get("db")
        assert found is mr

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, rm):
        assert await rm.get("nope") is None

    @pytest.mark.asyncio
    async def test_size(self, rm, make_managed):
        assert rm.size == 0
        await rm.register("a", make_managed("a"))
        assert rm.size == 1

    @pytest.mark.asyncio
    async def test_unregister(self, rm, make_managed):
        mr = make_managed("temp")
        await rm.register("temp", mr)
        removed = await rm.unregister("temp")
        assert removed is mr
        assert rm.size == 0

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(self, rm):
        assert await rm.unregister("nope") is None

    @pytest.mark.asyncio
    async def test_shutdown_lifo_order(self, rm, make_managed):
        close_order = []

        def make_closable(name):
            obj = MagicMock()

            async def tracked_close():
                close_order.append(name)

            obj.close = tracked_close
            return ManagedResource(obj, name=name)

        await rm.register("first", make_closable("first"))
        await rm.register("second", make_closable("second"))
        await rm.register("third", make_closable("third"))

        await rm.shutdown()
        # LIFO: third, second, first
        assert close_order == ["third", "second", "first"]

    @pytest.mark.asyncio
    async def test_shutdown_timeout(self, rm):
        obj = MagicMock()

        async def slow_close():
            await asyncio.sleep(10)

        obj.close = slow_close
        mr = ManagedResource(obj, name="slow")
        await rm.register("slow", mr)

        failures = await rm.shutdown(timeout=0.1)
        assert len(failures) == 1
        assert "timeout" in failures[0]

    @pytest.mark.asyncio
    async def test_shutdown_error(self, rm):
        obj = MagicMock()
        obj.close = MagicMock(side_effect=RuntimeError("boom"))
        mr = ManagedResource(obj, name="bad")
        await rm.register("bad", mr)

        failures = await rm.shutdown()
        assert len(failures) == 1

    @pytest.mark.asyncio
    async def test_health_report(self, rm, make_managed):
        mr = make_managed("healthy")
        await rm.register("healthy", mr)
        report = await rm.health_report()
        assert report["healthy"] is True

    @pytest.mark.asyncio
    async def test_health_report_error(self, rm):
        obj = MagicMock()
        obj.close = MagicMock()
        obj.health_check = MagicMock(side_effect=RuntimeError("nope"))
        mr = ManagedResource(obj, name="sick")
        await rm.register("sick", mr)
        report = await rm.health_report()
        assert report["sick"] is False

    @pytest.mark.asyncio
    async def test_check_leaks(self, rm):
        obj = MagicMock()
        obj.close = MagicMock()
        mr = ManagedResource(obj, name="old")
        # Simulate acquired long ago
        mr.info.acquired_at = time.monotonic() - 600  # 10 min ago

        rm = ResourceManager(leak_warn_threshold=300.0)
        await rm.register("old", mr)

        leaks = rm.check_leaks()
        assert len(leaks) == 1
        assert "old" in leaks[0]

    @pytest.mark.asyncio
    async def test_check_leaks_none_fresh(self, rm, make_managed):
        mr = make_managed("fresh")
        await rm.register("fresh", mr)
        leaks = rm.check_leaks()
        assert len(leaks) == 0

    @pytest.mark.asyncio
    async def test_add_finalizer(self, rm):
        results = []

        def finalize():
            results.append("done")

        rm.add_finalizer(finalize)
        await rm.shutdown()
        assert results == ["done"]

    @pytest.mark.asyncio
    async def test_register_during_shutdown(self, rm, make_managed):
        rm._shutting_down = True
        with pytest.raises(RuntimeError, match="shutting down"):
            await rm.register("late", make_managed("late"))


# ============================================================================
# Global singleton
# ============================================================================

class TestGlobalResourceManager:
    def test_singleton(self):
        # Use a fresh module-level variable
        from agentos.core import resource_manager as rm_mod

        original = rm_mod._global_resource_manager
        rm_mod._global_resource_manager = None
        try:
            rm1 = get_resource_manager()
            rm2 = get_resource_manager()
            assert rm1 is rm2
        finally:
            rm_mod._global_resource_manager = original


# ============================================================================
# AbstractResource
# ============================================================================

class TestAbstractResource:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            AbstractResource()

    def test_concrete_subclass(self):
        class MyResource(AbstractResource):
            async def close(self):
                pass

        r = MyResource()
        assert r is not None
