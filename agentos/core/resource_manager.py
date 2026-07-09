"""AgentOS Resource Manager — production-grade resource lifecycle & cleanup.

Manages:
- Async resource acquisition/release (connections, pools, files)
- Ordered shutdown (LIFO — last acquired, first released)
- Finalizer registry for guaranteed cleanup
- Health-checked resource pools
- Leak detection

Design: ~330 lines, zero external deps beyond stdlib + asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import (
    Any,
    TypeVar,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================
# Data types
# ============================================================================


class ResourceState(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class ResourceType(StrEnum):
    CONNECTION = "connection"
    POOL = "pool"
    FILE = "file"
    LOCK = "lock"
    SESSION = "session"
    OTHER = "other"


@dataclass
class ResourceInfo:
    """Metadata about a managed resource."""

    name: str
    resource_type: ResourceType = ResourceType.OTHER
    state: ResourceState = ResourceState.CREATED
    acquired_at: float = 0.0
    released_at: float = 0.0
    leak_warn_threshold: float = 300.0  # Warn if held > 5 min


# ============================================================================
# Abstract Resource
# ============================================================================


class AbstractResource(ABC):
    """Interface for managed resources."""

    @abstractmethod
    async def close(self) -> None:
        """Release the underlying resource."""

    async def health_check(self) -> bool:
        """Optional health check. Default: assume healthy if not closed."""
        return True

    def on_leak_detected(self) -> None:
        """Callback when resource appears to be leaked."""
        logger.warning("Resource leak suspected: %s", self)


# ============================================================================
# Managed Resource wrapper
# ============================================================================


class ManagedResource(AbstractResource):
    """Wraps any async-closeable object into a managed resource."""

    def __init__(
        self,
        resource: Any,
        close_fn: Callable[[Any], Any] | None = None,
        name: str = "unnamed",
        resource_type: ResourceType = ResourceType.OTHER,
    ):
        self._resource = resource
        self._close_fn = (
            close_fn or getattr(resource, "close", None) or getattr(resource, "aclose", None)
        )
        self.info = ResourceInfo(name=name, resource_type=resource_type)
        self.info.acquired_at = time.monotonic()
        self.info.state = ResourceState.ACTIVE

    @property
    def raw(self) -> Any:
        """Access the underlying resource object."""
        return self._resource

    async def close(self) -> None:
        if self.info.state == ResourceState.CLOSED:
            return

        self.info.state = ResourceState.CLOSING
        try:
            if self._close_fn is not None:
                result = self._close_fn()
                if asyncio.iscoroutine(result):
                    await result
        except Exception as exc:
            self.info.state = ResourceState.ERROR
            logger.error("Failed to close resource %s: %s", self.info.name, exc)
            raise
        else:
            self.info.state = ResourceState.CLOSED
            self.info.released_at = time.monotonic()

    async def health_check(self) -> bool:
        if self.info.state == ResourceState.CLOSED:
            return False
        health_fn = getattr(self._resource, "health_check", None) or getattr(
            self._resource, "ping", None
        )
        if health_fn is not None:
            try:
                result = health_fn()
                if asyncio.iscoroutine(result):
                    result = await result
                return bool(result)
            except Exception:
                return False
        return True


# ============================================================================
# Resource Pool
# ============================================================================


class ResourcePool(AbstractResource):
    """Generic async resource pool with health-checked lend/return.

    Usage:
        pool = ResourcePool(factory=create_db_conn, max_size=10)
        async with pool.acquire() as conn:
            await conn.query(...)
    """

    def __init__(
        self,
        factory: Callable[[], Any],
        max_size: int = 10,
        min_size: int = 0,
        idle_timeout: float = 300.0,
        health_check_interval: float = 30.0,
        name: str = "pool",
    ):
        self._factory = factory
        self._max_size = max_size
        self._min_size = min_size
        self._idle_timeout = idle_timeout
        self._health_check_interval = health_check_interval
        self._name = name

        self._available: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._in_use: dict[int, Any] = {}  # id(resource) → resource
        self._total: int = 0
        self._lock = asyncio.Lock()
        self._closed = False
        self._health_task: asyncio.Task | None = None

    async def _prefill(self):
        """Pre-create min_size connections."""
        for _ in range(self._min_size):
            resource = self._factory()
            if asyncio.iscoroutine(resource):
                resource = await resource
            await self._available.put(resource)
            self._total += 1

    async def start(self):
        """Initialize the pool."""
        await self._prefill()
        if self._health_check_interval > 0:
            self._health_task = asyncio.ensure_future(self._health_loop())

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        """Acquire a resource from the pool. Returns via context manager."""
        resource = await self._get()
        try:
            yield resource
        finally:
            await self._return(resource)

    async def _get(self) -> Any:
        if self._closed:
            raise RuntimeError(f"ResourcePool '{self._name}' is closed")

        # Try to get from available
        try:
            resource = self._available.get_nowait()
            self._in_use[id(resource)] = resource
            return resource
        except asyncio.QueueEmpty:
            pass

        # Try to create new
        async with self._lock:
            if self._total < self._max_size:
                resource = self._factory()
                if asyncio.iscoroutine(resource):
                    resource = await resource
                self._total += 1
                self._in_use[id(resource)] = resource
                return resource

        # Wait for one to become available
        resource = await self._available.get()
        self._in_use[id(resource)] = resource
        return resource

    async def _return(self, resource: Any):
        self._in_use.pop(id(resource), None)
        if not self._closed:
            await self._available.put(resource)

    async def _health_loop(self):
        """Periodic health check, remove dead connections."""
        while not self._closed:
            await asyncio.sleep(self._health_check_interval)
            # Drain and re-check
            healthy: list[Any] = []
            while not self._available.empty():
                try:
                    resource = self._available.get_nowait()
                    if self._is_healthy(resource):
                        healthy.append(resource)
                    else:
                        self._total -= 1
                        logger.debug("Pool '%s': removed unhealthy connection", self._name)
                except asyncio.QueueEmpty:
                    break

            for resource in healthy:
                await self._available.put(resource)

            # Top up to min_size
            while self._total < self._min_size and not self._closed:
                async with self._lock:
                    if self._total < self._max_size:
                        resource = self._factory()
                        if asyncio.iscoroutine(resource):
                            resource = await resource
                        await self._available.put(resource)
                        self._total += 1

    def _is_healthy(self, resource: Any) -> bool:
        """Check if a resource is healthy."""
        health_fn = getattr(resource, "health_check", None) or getattr(resource, "ping", None)
        if health_fn is None:
            return True
        try:
            result = health_fn()
            if asyncio.iscoroutine(result):
                return True  # Can't check async in sync context
            return bool(result)
        except Exception:
            return False

    def _close_resource(self, resource: Any, errors: list[Exception]):
        """Attempt to close a single resource, collecting errors."""
        close_fn = (
            getattr(resource, "close", None)
            or getattr(resource, "aclose", None)
            or (resource.get("close") if isinstance(resource, dict) else None)
            or (resource.get("aclose") if isinstance(resource, dict) else None)
        )
        if close_fn is not None:
            try:
                result = close_fn()
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(self._await_close(result, errors))
            except Exception as exc:
                errors.append(exc)

    @staticmethod
    async def _await_close(coro, errors: list[Exception]):
        try:
            await coro
        except Exception as exc:
            errors.append(exc)

    async def close(self) -> None:
        """Close all resources in the pool."""
        if self._closed:
            return
        self._closed = True

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Close all resources
        errors: list[Exception] = []

        # Close in-use
        for rid, resource in list(self._in_use.items()):
            self._close_resource(resource, errors)
        self._in_use.clear()

        # Close available
        while not self._available.empty():
            try:
                resource = self._available.get_nowait()
                self._close_resource(resource, errors)
            except asyncio.QueueEmpty:
                break
            except Exception as exc:
                errors.append(exc)

        if errors:
            logger.error("Pool '%s': %d errors during close", self._name, len(errors))

    async def health_check(self) -> bool:
        return not self._closed

    @property
    def stats(self) -> dict[str, Any]:
        """Pool statistics."""
        return {
            "name": self._name,
            "total": self._total,
            "in_use": len(self._in_use),
            "available": self._available.qsize(),
            "max_size": self._max_size,
            "closed": self._closed,
        }


# ============================================================================
# Resource Manager (central registry)
# ============================================================================


class ResourceManager:
    """Central resource lifecycle manager.

    Tracks all resources, ensures ordered shutdown (LIFO),
    provides leak detection.

    Usage:
        rm = ResourceManager()
        conn = await rm.register("db", managed_pg_conn)
        # ... use conn ...
        await rm.shutdown()  # closes all in reverse order
    """

    def __init__(self, leak_warn_threshold: float = 300.0):
        self._resources: list[tuple[str, AbstractResource]] = []
        self._lock = asyncio.Lock()
        self._leak_threshold = leak_warn_threshold
        self._shutting_down = False
        self._finalizers: list[Callable[[], Any]] = []

    async def register(self, name: str, resource: AbstractResource) -> AbstractResource:
        """Register a resource for lifecycle management."""
        async with self._lock:
            if self._shutting_down:
                raise RuntimeError(
                    "ResourceManager is shutting down — cannot register new resources"
                )
            self._resources.append((name, resource))
        return resource

    async def unregister(self, name: str) -> AbstractResource | None:
        """Remove a resource from management (without closing)."""
        async with self._lock:
            for i, (n, r) in enumerate(self._resources):
                if n == name:
                    self._resources.pop(i)
                    return r
        return None

    def add_finalizer(self, fn: Callable[[], Any]):
        """Register a finalizer to run during shutdown."""
        self._finalizers.append(fn)

    async def get(self, name: str) -> AbstractResource | None:
        """Find a managed resource by name."""
        for n, r in self._resources:
            if n == name:
                return r
        return None

    async def shutdown(self, timeout: float = 30.0) -> list[str]:
        """Ordered shutdown — LIFO order, with timeout per resource.

        Returns list of resource names that failed to close.
        """
        self._shutting_down = True
        failures: list[str] = []

        # Close resources in reverse order
        async with self._lock:
            resources = list(reversed(self._resources))
            self._resources.clear()

        for name, resource in resources:
            try:
                await asyncio.wait_for(resource.close(), timeout=timeout)
                logger.debug("Closed resource: %s", name)
            except TimeoutError:
                failures.append(f"{name} (timeout)")
                logger.error("Resource '%s' close timed out after %.0fs", name, timeout)
            except Exception as exc:
                failures.append(f"{name} ({exc})")
                logger.error("Failed to close resource '%s': %s", name, exc)

        # Run finalizers
        for fn in self._finalizers:
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error("Finalizer failed: %s", exc)

        return failures

    async def health_report(self) -> dict[str, bool]:
        """Health check all registered resources."""
        report: dict[str, bool] = {}
        async with self._lock:
            for name, resource in self._resources:
                try:
                    report[name] = await resource.health_check()
                except Exception:
                    report[name] = False
        return report

    def check_leaks(self) -> list[str]:
        """Check for resources held beyond leak threshold."""
        now = time.monotonic()
        leaks: list[str] = []
        for name, resource in self._resources:
            if hasattr(resource, "info") and hasattr(resource.info, "acquired_at"):
                age = now - resource.info.acquired_at
                if age > self._leak_threshold and resource.info.state != ResourceState.CLOSED:
                    leaks.append(f"{name} (held {age:.0f}s)")
        return leaks

    @property
    def size(self) -> int:
        return len(self._resources)


# ============================================================================
# Global singleton
# ============================================================================

_global_resource_manager: ResourceManager | None = None


def get_resource_manager() -> ResourceManager:
    """Get or create the global ResourceManager singleton."""
    global _global_resource_manager
    if _global_resource_manager is None:
        _global_resource_manager = ResourceManager()
    return _global_resource_manager
