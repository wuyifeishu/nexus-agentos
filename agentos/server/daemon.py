"""
AgentOS Server Daemon — Independent production server wrapper.

Provides:
  - PID file management (start/stop/status/restart)
  - Signal handling (SIGTERM/SIGINT) with graceful shutdown
  - Background asyncio task queue
  - Structured file logging with rotation
  - Health check endpoint (/healthz auto-mounted)
  - Configuration via environment variables
  - Memory persistence (v1.14.9): auto-save on shutdown, auto-load on startup

Usage:
    agentos-daemon start       # start as daemon
    agentos-daemon stop        # stop running daemon
    agentos-daemon status      # check if daemon is running
    agentos-daemon restart     # stop + start
    agentos-daemon run         # run in foreground (debug)

Environment:
    AGENTOS_DAEMON_HOST=0.0.0.0
    AGENTOS_DAEMON_PORT=8910
    AGENTOS_DAEMON_PIDFILE=~/.agentos/daemon.pid
    AGENTOS_DAEMON_LOGFILE=~/.agentos/daemon.log
    AGENTOS_DAEMON_WORKERS=4
    AGENTOS_DAEMON_TIMEOUT=30    # graceful shutdown timeout seconds
    AGENTOS_DAEMON_LOG_LEVEL=info
    AGENTOS_DAEMON_MEMORY_DIR=~/.agentos/memory   # memory persistence dir
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentos.memory.persistence import MemoryPersistenceManager

__all__ = [
    "ServerDaemon",
    "DaemonConfig",
    "BackgroundTask",
    "get_daemon",
    "create_daemon_app",
    "daemon_main",
]

# ── Config ──────────────────────────────────────────────


@dataclass
class DaemonConfig:
    """Server daemon configuration."""

    host: str = "0.0.0.0"
    port: int = 8910
    pidfile: str = "~/.agentos/daemon.pid"
    logfile: str = "~/.agentos/daemon.log"
    workers: int = 1
    shutdown_timeout: float = 30.0
    log_level: str = "info"
    log_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    log_backup_count: int = 5
    memory_dir: str = "~/.agentos/memory"
    persist_memory: bool = True

    @classmethod
    def from_env(cls) -> DaemonConfig:
        """Load config from environment variables."""
        return cls(
            host=os.getenv("AGENTOS_DAEMON_HOST", "0.0.0.0"),
            port=int(os.getenv("AGENTOS_DAEMON_PORT", "8910")),
            pidfile=os.path.expanduser(
                os.getenv("AGENTOS_DAEMON_PIDFILE", "~/.agentos/daemon.pid")
            ),
            logfile=os.path.expanduser(
                os.getenv("AGENTOS_DAEMON_LOGFILE", "~/.agentos/daemon.log")
            ),
            workers=int(os.getenv("AGENTOS_DAEMON_WORKERS", "1")),
            shutdown_timeout=float(os.getenv("AGENTOS_DAEMON_TIMEOUT", "30")),
            log_level=os.getenv("AGENTOS_DAEMON_LOG_LEVEL", "info"),
            memory_dir=os.path.expanduser(
                os.getenv("AGENTOS_DAEMON_MEMORY_DIR", "~/.agentos/memory")
            ),
            persist_memory=os.getenv("AGENTOS_DAEMON_PERSIST_MEMORY", "true").lower()
            not in ("0", "false", "no"),
        )


# ── Background Task Queue ──────────────────────────────


@dataclass
class BackgroundTask:
    """A tracked background task."""

    task_id: str
    name: str
    created_at: float = field(default_factory=time.time)
    status: str = "pending"
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "created_at": self.created_at,
            "status": self.status,
            "result": str(self.result)[:500] if self.result is not None else None,
            "error": self.error,
        }


class TaskQueue:
    """Minimal async background task queue (in-process, no external broker)."""

    def __init__(self, max_history: int = 1000) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._max_history = max_history
        self._asyncio_tasks: dict[str, asyncio.Task] = {}
        self._counter = 0

    def submit(self, name: str, coro) -> str:
        """Submit a coroutine for background execution. Returns task_id."""
        self._counter += 1
        tid = f"task_{self._counter}_{int(time.time())}"
        bt = BackgroundTask(task_id=tid, name=name, status="running")
        bt.created_at = time.time()
        self._tasks[tid] = bt

        async def _runner():
            try:
                bt.result = await coro
                bt.status = "completed"
            except Exception as exc:
                bt.error = str(exc)
                bt.status = "failed"

        self._asyncio_tasks[tid] = asyncio.create_task(_runner())
        self._prune_history()
        return tid

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> list[BackgroundTask]:
        items = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return items[:limit]

    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == "running")

    def _prune_history(self) -> None:
        if len(self._tasks) > self._max_history:
            completed = [
                tid for tid, t in self._tasks.items() if t.status in ("completed", "failed")
            ]
            overflow = len(self._tasks) - self._max_history
            for tid in completed[:overflow]:
                del self._tasks[tid]
                self._asyncio_tasks.pop(tid, None)

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Cancel all running tasks with a timeout."""
        if not self._asyncio_tasks:
            return
        for t in list(self._asyncio_tasks.values()):
            if not t.done():
                t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._asyncio_tasks.values(), return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            pass


# ── Daemon Core ────────────────────────────────────────


def _setup_file_logging(config: DaemonConfig) -> logging.Logger:
    """Configure rotating file logger."""
    from logging.handlers import RotatingFileHandler

    log_dir = Path(config.logfile).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("agentos.daemon")
    logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
    logger.propagate = False

    # Remove existing handlers
    for h in list(logger.handlers):
        logger.removeHandler(h)

    handler = RotatingFileHandler(
        config.logfile,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    return logger


class ServerDaemon:
    """Independent server daemon wrapping any ASGI app.

    Lifecycle:
        daemon = ServerDaemon(config, app_factory)
        daemon.start()    # daemonize
        daemon.stop()     # send SIGTERM
        daemon.status()   # read PID file
        daemon.restart()  # stop + start
    """

    def __init__(
        self,
        config: DaemonConfig | None = None,
        app_factory: Callable[[], FastAPI] | None = None,
    ) -> None:
        self.config = config or DaemonConfig.from_env()
        self._app_factory = app_factory or self._default_app_factory
        self._logger = _setup_file_logging(self.config)
        self.task_queue = TaskQueue()
        self._started_at: float | None = None
        self._shutdown_event: asyncio.Event | None = None

        # Memory persistence (v1.14.9)
        self._persistence_mgr = MemoryPersistenceManager(
            base_dir=self.config.memory_dir,
            compress=True,
        )
        self._memory_objects: dict[str, Any] = {
            "pyramid": None,
            "working": None,
            "conversation": None,
            "long_term": None,
            "reflection_engine": None,
            "consolidation_pipeline": None,
        }

    # ── Memory Persistence API (v1.14.9) ──────

    def register_memory(
        self,
        *,
        pyramid: Any = None,
        working: Any = None,
        conversation: Any = None,
        long_term: Any = None,
        reflection_engine: Any = None,
        consolidation_pipeline: Any = None,
    ) -> None:
        """Register memory objects for crash-safe persistence.

        Objects must implement get_state() and restore_state().
        On daemon shutdown, all registered objects are automatically saved
        to disk. On daemon startup, they are automatically restored.
        """
        if pyramid is not None:
            self._memory_objects["pyramid"] = pyramid
        if working is not None:
            self._memory_objects["working"] = working
        if conversation is not None:
            self._memory_objects["conversation"] = conversation
        if long_term is not None:
            self._memory_objects["long_term"] = long_term
        if reflection_engine is not None:
            self._memory_objects["reflection_engine"] = reflection_engine
        if consolidation_pipeline is not None:
            self._memory_objects["consolidation_pipeline"] = consolidation_pipeline

        self._logger.info(
            f"Registered {sum(1 for v in self._memory_objects.values() if v is not None)} "
            f"memory subsystems for persistence"
        )

    async def save_memory_snapshot(self) -> str | None:
        """Save current memory state to disk. Returns snapshot path or None."""
        if not self.config.persist_memory:
            return None

        mo = self._memory_objects
        try:
            path = await self._persistence_mgr.save_all(
                pyramid=mo["pyramid"],
                working=mo["working"],
                conversation=mo["conversation"],
                long_term=mo["long_term"],
                reflection_engine=mo["reflection_engine"],
                consolidation_pipeline=mo["consolidation_pipeline"],
            )
            self._logger.info(f"Memory snapshot saved: {path}")
            return path
        except Exception as exc:
            self._logger.error(f"Failed to save memory snapshot: {exc}")
            return None

    async def load_memory_snapshot(self) -> int:
        """Load memory state from disk and restore into registered objects.
        Returns count of subsystems restored.
        """
        if not self.config.persist_memory:
            return 0

        mo = self._memory_objects
        try:
            restored = await self._persistence_mgr.restore_all(
                pyramid=mo["pyramid"],
                working=mo["working"],
                conversation=mo["conversation"],
                long_term=mo["long_term"],
                reflection_engine=mo["reflection_engine"],
                consolidation_pipeline=mo["consolidation_pipeline"],
            )
            if restored > 0:
                self._logger.info(f"Memory snapshot loaded: {restored} subsystems restored")
            return restored
        except Exception as exc:
            self._logger.error(f"Failed to load memory snapshot: {exc}")
            return 0

    def memory_snapshot_info(self) -> dict[str, Any]:
        """Return metadata about the current memory snapshot on disk."""
        return self._persistence_mgr.snapshot_info()

    # ── PID file helpers ──────────────────────

    def _read_pid(self) -> int | None:
        """Read PID from pidfile. Returns None if not running."""
        path = Path(self.config.pidfile)
        if not path.exists():
            return None
        try:
            pid = int(path.read_text().strip())
        except (ValueError, OSError):
            return None
        # Check if process is actually running
        try:
            os.kill(pid, 0)
            return pid
        except (ProcessLookupError, PermissionError):
            return None

    def _write_pid(self, pid: int) -> None:
        """Write PID to pidfile."""
        path = Path(self.config.pidfile)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n")

    def _remove_pid(self) -> None:
        """Remove pidfile."""
        path = Path(self.config.pidfile)
        if path.exists():
            path.unlink()

    # ── Status ────────────────────────────────

    def status(self) -> dict:
        """Get daemon status as a dict."""
        pid = self._read_pid()
        running = pid is not None
        uptime = time.time() - self._started_at if self._started_at and running else 0
        return {
            "running": running,
            "pid": pid,
            "host": self.config.host,
            "port": self.config.port,
            "pidfile": self.config.pidfile,
            "logfile": self.config.logfile,
            "uptime_seconds": round(uptime, 1),
            "active_tasks": self.task_queue.active_count() if running else 0,
        }

    # ── Start ─────────────────────────────────

    def start(self, daemonize: bool = True) -> int:
        """Start the server. Returns PID if daemonized, 0 if foreground."""
        if self._read_pid():
            self._logger.warning("Daemon is already running.")
            print(
                f"Daemon already running (pid={self._read_pid()}) on "
                f"http://{self.config.host}:{self.config.port}"
            )
            return self._read_pid() or 0

        if daemonize:
            return self._daemonize()
        else:
            return self._run_foreground()

    def _daemonize(self) -> int:
        """Fork into background daemon."""
        pid = os.fork()
        if pid > 0:
            # Parent: wait briefly for child to start, then return
            time.sleep(0.5)
            child_pid = self._read_pid()
            if child_pid:
                self._logger.info(f"Daemon started (pid={child_pid})")
                print(
                    f"Daemon started (pid={child_pid})\n"
                    f"  http://{self.config.host}:{self.config.port}\n"
                    f"  health: http://{self.config.host}:{self.config.port}/healthz\n"
                    f"  logs:   {self.config.logfile}"
                )
                return child_pid
            else:
                print("Failed to start daemon — check logs.")
                return 1

        # Child process
        os.setsid()
        # Second fork to detach from session
        pid2 = os.fork()
        if pid2 > 0:
            os._exit(0)

        # Grandchild: the actual daemon
        self._write_pid(os.getpid())
        atexit.register(self._remove_pid)

        # Redirect stdin/stdout/stderr
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, sys.stdin.fileno())
        os.dup2(devnull, sys.stdout.fileno())
        os.dup2(devnull, sys.stderr.fileno())
        if devnull > 2:
            os.close(devnull)

        self._started_at = time.time()
        self._logger.info(f"Daemon starting on http://{self.config.host}:{self.config.port}")
        self._run_server()
        return 0

    def _run_foreground(self) -> int:
        """Run in foreground (debug mode)."""
        self._write_pid(os.getpid())
        atexit.register(self._remove_pid)
        self._started_at = time.time()
        print(
            f"Running in foreground on http://{self.config.host}:{self.config.port}\n"
            f"  health: http://{self.config.host}:{self.config.port}/healthz\n"
            f"  press Ctrl+C to stop"
        )
        self._run_server()
        return 0

    def _run_server(self) -> None:
        """Run the uvicorn server (blocking)."""
        app = self._build_app()
        uvicorn.run(
            app,
            host=self.config.host,
            port=self.config.port,
            log_level=self.config.log_level,
            workers=self.config.workers if self.config.workers > 1 else None,
            timeout_graceful_shutdown=self.config.shutdown_timeout,
        )

    # ── Stop ──────────────────────────────────

    def stop(self) -> bool:
        """Stop the running daemon via SIGTERM."""
        pid = self._read_pid()
        if not pid:
            print("No running daemon found.")
            return False

        self._logger.info(f"Stopping daemon (pid={pid})")
        print(f"Stopping daemon (pid={pid})...")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._remove_pid()
            print("Daemon already stopped.")
            return True

        # Wait for graceful shutdown
        timeout = self.config.shutdown_timeout
        for _ in range(int(timeout * 2)):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                self._remove_pid()
                print("Daemon stopped.")
                return True

        # Force kill
        print(f"Daemon did not stop within {timeout}s, sending SIGKILL...")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self._remove_pid()
        print("Daemon force-stopped.")
        return True

    # ── Restart ───────────────────────────────

    def restart(self, daemonize: bool = True) -> int:
        """Stop then start the daemon."""
        self.stop()
        time.sleep(1)
        return self.start(daemonize=daemonize)

    # ── App building ──────────────────────────

    def _default_app_factory(self) -> FastAPI:
        """Default app: minimal standalone with health check."""
        return create_daemon_app(self.task_queue)

    def _build_app(self) -> FastAPI:
        """Build the FastAPI application with memory persistence hooks."""
        app = self._app_factory()

        # Inject daemon state into app
        app.state.daemon = self
        app.state.task_queue = self.task_queue

        # Patch lifespan to add memory persistence hooks (v1.14.9)
        _original_lifespan = getattr(app.router, "lifespan_context", None)

        @asynccontextmanager
        async def memory_lifespan(app: FastAPI):
            """Wrap existing lifespan with memory save/load."""
            # Load on startup
            restored = await self.load_memory_snapshot()
            if restored > 0:
                self._logger.info(f"Loaded {restored} memory subsystems from snapshot")

            # Execute original lifespan
            if _original_lifespan is not None:
                async with _original_lifespan(app):
                    pass

            # Yield to the app
            yield

            # Save on shutdown
            await self.save_memory_snapshot()
            self._logger.info("Memory snapshot saved on shutdown")

        app.router.lifespan_context = memory_lifespan

        # Ensure /healthz endpoint exists
        has_healthz = any(
            any(r.path == "/healthz" for r in router.routes)
            for router in app.router.routes
            if hasattr(router, "routes")
        )
        # Also check top-level routes
        has_healthz = has_healthz or any(getattr(r, "path", "") == "/healthz" for r in app.routes)

        if not has_healthz:
            health_router = _make_health_router(self, self.task_queue)
            app.include_router(health_router)

        return app


# ── Health / API routes ─────────────────────────────────


def _make_health_router(daemon: ServerDaemon, tq: TaskQueue) -> APIRouter:
    """Create the health check and management router."""
    router = APIRouter(tags=["daemon"])

    @router.get("/healthz")
    async def healthz():
        """Kubernetes-style health check."""
        return {
            "status": "healthy",
            "uptime_seconds": round(time.time() - (daemon._started_at or time.time()), 1),
            "active_tasks": tq.active_count(),
        }

    @router.get("/healthz/ready")
    async def ready():
        """Readiness check."""
        return {
            "status": "ready",
            "active_tasks": tq.active_count(),
        }

    @router.get("/api/daemon/status")
    async def daemon_status():
        """Full daemon status."""
        return daemon.status()

    @router.get("/api/daemon/tasks")
    async def list_tasks(limit: int = 50):
        """List background tasks."""
        tasks = [t.to_dict() for t in tq.list_tasks(limit)]
        return {"count": len(tasks), "active": tq.active_count(), "tasks": tasks}

    @router.get("/api/daemon/memory")
    async def memory_status():
        """Memory persistence status."""
        info = daemon.memory_snapshot_info()
        return {
            "persistence_enabled": daemon.config.persist_memory,
            "memory_dir": daemon.config.memory_dir,
            "snapshot": info,
        }

    return router


# ── Convenience factory ────────────────────────────────


def create_daemon_app(task_queue: TaskQueue | None = None) -> FastAPI:
    """Create a minimal standalone daemon FastAPI app."""
    tq = task_queue or TaskQueue()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Handle startup and shutdown."""
        yield
        await tq.shutdown(timeout=10.0)

    app = FastAPI(
        title="AgentOS Daemon",
        version="1.14.9",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        return {
            "service": "AgentOS Daemon",
            "version": "1.14.9",
            "endpoints": {
                "health": "/healthz",
                "ready": "/healthz/ready",
                "status": "/api/daemon/status",
                "tasks": "/api/daemon/tasks",
            },
        }

    return app


# ── Module-level singleton ─────────────────────────────

_daemon_instance: ServerDaemon | None = None


def get_daemon(config: DaemonConfig | None = None) -> ServerDaemon:
    """Get or create the module-level daemon singleton."""
    global _daemon_instance
    if _daemon_instance is None:
        _daemon_instance = ServerDaemon(config=config)
    return _daemon_instance


# ── Main entry point ──────────────────────────────────


def daemon_main(args: list[str] | None = None) -> int:
    """CLI entry point for daemon commands."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="agentos-daemon",
        description="AgentOS Independent Server Daemon",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("start", help="Start daemon in background")
    sub.add_parser("run", help="Run in foreground")
    sub.add_parser("stop", help="Stop running daemon")
    sub.add_parser("restart", help="Stop then start")
    sub.add_parser("status", help="Show daemon status")

    ns = parser.parse_args(args)

    daemon = get_daemon()

    if ns.command == "start":
        return daemon.start(daemonize=True)
    elif ns.command == "run":
        return daemon.start(daemonize=False)
    elif ns.command == "stop":
        return 0 if daemon.stop() else 1
    elif ns.command == "restart":
        return daemon.restart()
    elif ns.command == "status":
        s = daemon.status()
        if s["running"]:
            print(
                f"RUNNING (pid={s['pid']})\n"
                f"  url:     http://{s['host']}:{s['port']}\n"
                f"  uptime:  {s['uptime_seconds']}s\n"
                f"  tasks:   {s['active_tasks']} active"
            )
        else:
            print("STOPPED")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(daemon_main())
