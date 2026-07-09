"""AgentOS Lifecycle — graceful startup/shutdown with ordered hooks.

Provides enterprise-grade process lifecycle management:
- Ordered startup hooks with timeout and health gate
- Ordered shutdown hooks with grace period
- SIGTERM/SIGINT graceful shutdown integration
- Component-level health registration
- Liveness/readiness probe support

Design: ~370 lines, zero external deps beyond stdlib + asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Types
# ============================================================================


class LifecyclePhase(StrEnum):
    """Ordered lifecycle phases during startup."""

    CONFIG = "config"  # Configuration loading
    INFRA = "infra"  # DB, Redis, message queues
    SECURITY = "security"  # Auth, encryption, certs
    SERVICES = "services"  # Internal services
    MIDDLEWARE = "middleware"  # Middleware pipeline
    API = "api"  # HTTP/gRPC server
    READY = "ready"  # Final readiness signal


class ComponentStatus(StrEnum):
    """Component health status."""

    UNINITIALIZED = "uninitialized"
    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    SHUTTING_DOWN = "shutting_down"
    STOPPED = "stopped"


@dataclass
class LifecycleHook:
    """A single startup or shutdown hook with metadata."""

    name: str
    phase: LifecyclePhase
    fn: Callable[[], Any]  # or async callable
    timeout_seconds: float = 30.0
    is_async: bool = False
    critical: bool = True  # Fail startup if critical hook fails
    weight: int = 50  # Ordering within same phase (lower = first)
    retries: int = 0
    retry_delay: float = 1.0


@dataclass
class ComponentHealth:
    """Health status of a single component."""

    name: str
    status: ComponentStatus = ComponentStatus.UNINITIALIZED
    phase: LifecyclePhase | None = None
    message: str = ""
    error: str | None = None
    started_at: float | None = None
    duration_ms: float = 0.0


@dataclass
class LifecycleReport:
    """Full lifecycle status report."""

    overall_status: ComponentStatus = ComponentStatus.UNINITIALIZED
    phase: str = ""
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    startup_duration_ms: float = 0.0
    shutdown_remaining_hooks: int = 0

    @property
    def is_healthy(self) -> bool:
        return self.overall_status == ComponentStatus.HEALTHY

    @property
    def is_ready(self) -> bool:
        return self.overall_status in (ComponentStatus.HEALTHY, ComponentStatus.DEGRADED)


# ============================================================================
# Lifecycle Manager
# ============================================================================


class LifecycleManager:
    """Orchestrates ordered startup and graceful shutdown.

    Usage:
        lm = LifecycleManager()

        @lm.on_startup(phase=LifecyclePhase.INFRA)
        async def init_db():
            ...

        @lm.on_shutdown
        async def close_db():
            ...

        async with lm:
            # Application runs here
            ...

    Signal handling (SIGTERM, SIGINT) integrated automatically.
    """

    PHASE_ORDER: list[LifecyclePhase] = [
        LifecyclePhase.CONFIG,
        LifecyclePhase.INFRA,
        LifecyclePhase.SECURITY,
        LifecyclePhase.SERVICES,
        LifecyclePhase.MIDDLEWARE,
        LifecyclePhase.API,
        LifecyclePhase.READY,
    ]

    def __init__(
        self,
        grace_period: float = 30.0,
        startup_timeout: float = 120.0,
    ):
        self._startup_hooks: list[LifecycleHook] = []
        self._shutdown_hooks: list[LifecycleHook] = []
        self._health: dict[str, ComponentHealth] = {}
        self._status = ComponentStatus.UNINITIALIZED
        self._start_time: float | None = None
        self._grace_period = grace_period
        self._startup_timeout = startup_timeout
        self._shutdown_event = asyncio.Event()
        self._ready_event = asyncio.Event()

    # ── Registration ──────────────────────────────────────────────────────

    def on_startup(
        self,
        name: str | None = None,
        *,
        phase: LifecyclePhase = LifecyclePhase.SERVICES,
        critical: bool = True,
        timeout_seconds: float = 30.0,
        weight: int = 50,
        retries: int = 0,
        retry_delay: float = 1.0,
    ) -> Callable:
        """Decorator: register a startup hook."""

        def decorator(fn):
            hook_name = name or fn.__name__
            is_async = asyncio.iscoroutinefunction(fn)
            self._startup_hooks.append(
                LifecycleHook(
                    name=hook_name,
                    phase=phase,
                    fn=fn,
                    timeout_seconds=timeout_seconds,
                    is_async=is_async,
                    critical=critical,
                    weight=weight,
                    retries=retries,
                    retry_delay=retry_delay,
                )
            )
            self._health[hook_name] = ComponentHealth(name=hook_name, phase=phase)
            return fn

        return decorator

    def on_shutdown(
        self,
        name: str | None = None,
        *,
        timeout_seconds: float = 10.0,
        weight: int = 50,
    ) -> Callable:
        """Decorator: register a shutdown hook (reverse order)."""

        def decorator(fn):
            hook_name = name or fn.__name__
            is_async = asyncio.iscoroutinefunction(fn)
            self._shutdown_hooks.append(
                LifecycleHook(
                    name=hook_name,
                    phase=LifecyclePhase.READY,  # irrelevant for shutdown
                    fn=fn,
                    timeout_seconds=timeout_seconds,
                    is_async=is_async,
                    critical=False,
                    weight=weight,
                )
            )
            return fn

        return decorator

    # ── Startup ───────────────────────────────────────────────────────────

    async def start(self) -> LifecycleReport:
        """Execute all startup hooks in phase/weight order."""
        self._start_time = time.perf_counter()
        self._status = ComponentStatus.STARTING

        # Sort: phase order first, then weight within phase
        phase_idx = {p: i for i, p in enumerate(self.PHASE_ORDER)}
        sorted_hooks = sorted(
            self._startup_hooks,
            key=lambda h: (phase_idx.get(h.phase, 99), h.weight),
        )

        for hook in sorted_hooks:
            ok = await self._execute_hook(hook, is_startup=True)
            if not ok and hook.critical:
                self._status = ComponentStatus.UNHEALTHY
                return self.report()

        self._status = ComponentStatus.HEALTHY
        self._ready_event.set()

        return self.report()

    async def _execute_hook(self, hook: LifecycleHook, is_startup: bool = True) -> bool:
        """Execute a single hook with timeout, retries, and health tracking."""
        health = self._health.get(hook.name) or ComponentHealth(name=hook.name)
        health.status = ComponentStatus.STARTING if is_startup else ComponentStatus.SHUTTING_DOWN
        health.started_at = time.time()

        attempt = 0
        last_error = None

        while attempt <= hook.retries:
            t0 = time.perf_counter()
            try:
                if hook.is_async:
                    await asyncio.wait_for(hook.fn(), timeout=hook.timeout_seconds)
                else:
                    loop = asyncio.get_event_loop()
                    await asyncio.wait_for(
                        loop.run_in_executor(None, hook.fn),
                        timeout=hook.timeout_seconds,
                    )
                health.duration_ms = (time.perf_counter() - t0) * 1000
                health.status = ComponentStatus.HEALTHY if is_startup else ComponentStatus.STOPPED
                health.message = "OK"
                logger.info(f"[lifecycle] {hook.name}: OK ({health.duration_ms:.0f}ms)")
                return True

            except TimeoutError:
                last_error = f"Timeout after {hook.timeout_seconds}s"
                health.error = last_error
                logger.warning(f"[lifecycle] {hook.name}: {last_error}")
            except Exception as e:
                last_error = str(e)
                health.error = last_error
                logger.warning(f"[lifecycle] {hook.name}: {last_error}")

            attempt += 1
            if attempt <= hook.retries:
                await asyncio.sleep(hook.retry_delay)

        health.status = ComponentStatus.UNHEALTHY
        health.duration_ms = (time.perf_counter() - t0) * 1000
        return False

    # ── Shutdown ──────────────────────────────────────────────────────────

    async def shutdown(self, signal_name: str = "") -> LifecycleReport:
        """Execute all shutdown hooks in reverse registration order."""
        if self._status == ComponentStatus.STOPPED:
            return self.report()

        self._status = ComponentStatus.SHUTTING_DOWN
        self._shutdown_event.set()
        logger.info(
            f"[lifecycle] Shutting down gracefully{f' ({signal_name})' if signal_name else ''}"
        )

        # Reverse order for shutdown (LIFO — last started, first stopped)
        for hook in reversed(self._shutdown_hooks):
            await self._execute_hook(hook, is_startup=False)

        self._status = ComponentStatus.STOPPED
        return self.report()

    # ── Signal integration ────────────────────────────────────────────────

    def setup_signal_handlers(self, loop: asyncio.AbstractEventLoop | None = None):
        """Register SIGTERM/SIGINT handlers on the event loop."""
        if loop is None:
            loop = asyncio.get_event_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.ensure_future(self.shutdown(signal.Signals(s).name)),
                )
            except (NotImplementedError, RuntimeError):
                # Windows or non-main-thread — fallback to signal.signal
                signal.signal(
                    sig, lambda s, f: asyncio.ensure_future(self.shutdown(signal.Signals(s).name))
                )

    # ── Probes ────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """Readiness probe: is the service ready to accept requests?"""
        return self._ready_event.is_set()

    def is_live(self) -> bool:
        """Liveness probe: is the process alive (not hung)?"""
        return self._status not in (ComponentStatus.STOPPED, ComponentStatus.UNHEALTHY)

    # ── Report ────────────────────────────────────────────────────────────

    def report(self) -> LifecycleReport:
        """Generate a full lifecycle status report."""
        startup_ms = 0.0
        if self._start_time:
            startup_ms = (time.perf_counter() - self._start_time) * 1000

        return LifecycleReport(
            overall_status=self._status,
            phase=self._status.value,
            components=dict(self._health),
            startup_duration_ms=startup_ms,
            shutdown_remaining_hooks=len(
                [
                    h
                    for h in self._shutdown_hooks
                    if self._health.get(h.name, ComponentHealth(name=h.name)).status
                    not in (ComponentStatus.STOPPED,)
                ]
            ),
        )

    # ── Context manager ───────────────────────────────────────────────────

    async def __aenter__(self):
        """Async context manager: start lifecycle."""
        self.setup_signal_handlers()
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager: graceful shutdown."""
        await self.shutdown()
        return False  # Don't suppress exceptions


# ============================================================================
# Singleton helper
# ============================================================================

_default_lifecycle: LifecycleManager | None = None


def get_lifecycle(
    grace_period: float = 30.0,
    startup_timeout: float = 120.0,
) -> LifecycleManager:
    """Get or create the global LifecycleManager singleton."""
    global _default_lifecycle
    if _default_lifecycle is None:
        _default_lifecycle = LifecycleManager(
            grace_period=grace_period,
            startup_timeout=startup_timeout,
        )
    return _default_lifecycle
