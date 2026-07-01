"""
Persistent Thread Context (PTC) — Session Manager.

OpenClaw-style long-running session management:
  - Heartbeat: periodic ping to keep sessions alive
  - Auto-suspend: idle sessions that exceed TTL
  - State recovery: resume a session exactly where it left off
  - Cross-session memory: carry context across disconnected sessions
  - Event hooks: on_suspend, on_resume, on_expire

Design:
  SessionManager
    └─ Session (per-thread lifecycle)
         ├─ heartbeat() — keep alive
         ├─ suspend()  — save state, pause
         ├─ resume()   — restore state, continue
         └─ expire()   — cleanup after TTL
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import aiosqlite


# ── Session Models ──

class SessionStatus(str, Enum):
    ACTIVE = "active"       # Currently running
    IDLE = "idle"           # Alive but no recent activity
    SUSPENDED = "suspended" # Paused, state saved
    EXPIRED = "expired"     # Timed out, cleaned up
    ERROR = "error"         # Crashed but state saved


@dataclass
class SessionState:
    """Serializable state snapshot for a session."""

    conversation_history: list[dict] = field(default_factory=list)
    working_memory: dict[str, Any] = field(default_factory=dict)
    agent_context: dict[str, Any] = field(default_factory=dict)
    tool_state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "conversation_history": self.conversation_history,
            "working_memory": self.working_memory,
            "agent_context": self.agent_context,
            "tool_state": self.tool_state,
            "metadata": self.metadata,
        }, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, data: str) -> "SessionState":
        d = json.loads(data)
        return cls(
            conversation_history=d.get("conversation_history", []),
            working_memory=d.get("working_memory", {}),
            agent_context=d.get("agent_context", {}),
            tool_state=d.get("tool_state", {}),
            metadata=d.get("metadata", {}),
        )


@dataclass
class Session:
    """A single PTC session (one conversational thread)."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    name: str = ""
    user_id: str = "default"
    status: SessionStatus = SessionStatus.ACTIVE

    created_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    state: SessionState = field(default_factory=SessionState)

    # Config
    heartbeat_interval: float = 30.0      # seconds between heartbeats
    idle_timeout: float = 300.0           # idle → suspend (5 min)
    absolute_ttl: float = 86400.0         # max lifetime (24h)
    max_history_turns: int = 1000

    # Internal
    _heartbeat_task: Optional[asyncio.Task] = None

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    @property
    def is_expired(self) -> bool:
        return self.age_seconds > self.absolute_ttl

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "user_id": self.user_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_heartbeat": self.last_heartbeat,
            "last_activity": self.last_activity,
            "heartbeat_interval": self.heartbeat_interval,
            "idle_timeout": self.idle_timeout,
            "absolute_ttl": self.absolute_ttl,
            "state": self.state.to_json(),
        }


# ── Session Manager ──

class SessionManager:
    """Manage PTC sessions with heartbeat, suspend/resume, and persistence.

    Usage:
        manager = SessionManager(db_path="~/.agentos/sessions.db")

        # Create a new session
        session = await manager.create(name="research-thread")

        # Heartbeat loop (runs in background)
        await manager.start_heartbeat(session)

        # Suspend on idle
        await manager.suspend(session.id)

        # Resume later — state restored
        session = await manager.resume(session.id)

        # Hooks
        manager.on_suspend(lambda s: print(f"{s.name} suspended"))
        manager.on_resume(lambda s: print(f"{s.name} resumed"))
    """

    def __init__(
        self,
        db_path: str = "",
        max_concurrent: int = 100,
    ):
        db_path = Path(db_path) if db_path else Path.home() / ".agentos" / "sessions.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._max_concurrent = max_concurrent

        self._sessions: dict[str, Session] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task] = {}
        self._hooks: dict[str, list[Callable]] = {
            "create": [],
            "suspend": [],
            "resume": [],
            "expire": [],
            "heartbeat_missed": [],
        }

    # ── Hooks ──

    def on(self, event: str):
        """Decorator: register a hook for session events."""
        def decorator(fn):
            self._hooks.setdefault(event, []).append(fn)
            return fn
        return decorator

    def on_create(self, fn: Callable[[Session], Any]): self._hooks["create"].append(fn)
    def on_suspend(self, fn: Callable[[Session], Any]): self._hooks["suspend"].append(fn)
    def on_resume(self, fn: Callable[[Session], Any]): self._hooks["resume"].append(fn)
    def on_expire(self, fn: Callable[[Session], Any]): self._hooks["expire"].append(fn)

    async def _fire(self, event: str, session: Session):
        for hook in self._hooks.get(event, []):
            try:
                result = hook(session)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    # ── Session Lifecycle ──

    async def create(
        self,
        name: str = "",
        user_id: str = "default",
        heartbeat_interval: float = 30.0,
        idle_timeout: float = 300.0,
        absolute_ttl: float = 86400.0,
    ) -> Session:
        """Create a new PTC session."""
        if len(self._sessions) >= self._max_concurrent:
            oldest = min(self._sessions.values(), key=lambda s: s.last_activity)
            await self.expire(oldest.id)

        session = Session(
            name=name or f"session-{uuid.uuid4().hex[:6]}",
            user_id=user_id,
            heartbeat_interval=heartbeat_interval,
            idle_timeout=idle_timeout,
            absolute_ttl=absolute_ttl,
        )

        self._sessions[session.id] = session
        await self._persist(session)
        await self._fire("create", session)

        return session

    async def suspend(self, session_id: str) -> bool:
        """Suspend a session — save state, stop heartbeat."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session.status = SessionStatus.SUSPENDED

        # Stop heartbeat
        if session_id in self._heartbeat_tasks:
            self._heartbeat_tasks[session_id].cancel()
            del self._heartbeat_tasks[session_id]

        await self._persist(session)
        await self._fire("suspend", session)

        return True

    async def resume(self, session_id: str) -> Optional[Session]:
        """Resume a suspended session — restore state, restart heartbeat."""
        session = self._sessions.get(session_id)

        # Try loading from DB if not in memory
        if not session:
            session = await self._load_from_db(session_id)
            if not session:
                return None

        if session.status == SessionStatus.EXPIRED:
            return None

        session.status = SessionStatus.ACTIVE
        session.last_activity = time.time()
        session.last_heartbeat = time.time()

        self._sessions[session.id] = session
        await self._fire("resume", session)

        return session

    async def expire(self, session_id: str) -> bool:
        """Permanently expire a session — cleanup."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        session.status = SessionStatus.EXPIRED

        if session_id in self._heartbeat_tasks:
            self._heartbeat_tasks[session_id].cancel()
            del self._heartbeat_tasks[session_id]

        await self._persist(session)
        await self._fire("expire", session)

        return True

    async def destroy(self, session_id: str) -> bool:
        """Hard delete a session from memory and DB."""
        await self.expire(session_id)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await db.commit()
        return True

    # ── Heartbeat ──

    async def start_heartbeat(self, session: Session) -> None:
        """Start background heartbeat for a session."""
        if session.id in self._heartbeat_tasks:
            return

        async def _loop():
            while True:
                await asyncio.sleep(session.heartbeat_interval)

                if session.id not in self._sessions:
                    return

                session.last_heartbeat = time.time()

                # Check idle timeout → suspend
                if session.idle_seconds > session.idle_timeout:
                    await self.suspend(session.id)
                    return

                # Check absolute TTL → expire
                if session.is_expired:
                    await self.expire(session.id)
                    return

                # Re-persist state snapshot
                await self._persist(session)

        self._heartbeat_tasks[session.id] = asyncio.create_task(_loop())

    async def heartbeat(self, session_id: str) -> bool:
        """Manual heartbeat ping. Returns False if session not found."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session.last_heartbeat = time.time()
        session.last_activity = time.time()

        # Re-activate if suspended
        if session.status == SessionStatus.SUSPENDED:
            await self.resume(session_id)

        return True

    # ── State Management ──

    async def save_state(self, session_id: str, state: SessionState) -> bool:
        """Save explicit state snapshot for a session."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session.state = state
        session.last_activity = time.time()
        await self._persist(session)
        return True

    async def get_state(self, session_id: str) -> Optional[SessionState]:
        """Get the latest state snapshot for a session."""
        session = self._sessions.get(session_id)
        if session:
            return session.state

        session = await self._load_from_db(session_id)
        return session.state if session else None

    async def add_context(self, session_id: str, key: str, value: Any) -> bool:
        """Add a key-value to the session's working memory."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.state.working_memory[key] = value
        session.last_activity = time.time()
        return True

    # ── Query ──

    def get(self, session_id: str) -> Optional[Session]:
        """Get an active session by ID."""
        return self._sessions.get(session_id)

    def list_active(self, user_id: str = "") -> list[Session]:
        """List all active/idle sessions, optionally filtered by user."""
        sessions = [s for s in self._sessions.values()
                    if s.status in (SessionStatus.ACTIVE, SessionStatus.IDLE)]
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        return sorted(sessions, key=lambda s: s.last_activity, reverse=True)

    def list_suspended(self, user_id: str = "") -> list[Session]:
        """List suspended sessions."""
        sessions = [s for s in self._sessions.values()
                    if s.status == SessionStatus.SUSPENDED]
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        return sorted(sessions, key=lambda s: s.last_activity, reverse=True)

    async def count(self) -> int:
        """Total sessions in memory."""
        return len(self._sessions)

    # ── Monitor ──

    async def monitor(self) -> dict[str, Any]:
        """Get a monitoring snapshot of all sessions."""
        active = 0
        idle = 0
        suspended = 0

        for s in self._sessions.values():
            if s.status == SessionStatus.ACTIVE:
                active += 1
            elif s.status == SessionStatus.IDLE:
                idle += 1
            elif s.status == SessionStatus.SUSPENDED:
                suspended += 1

        return {
            "total": len(self._sessions),
            "active": active,
            "idle": idle,
            "suspended": suspended,
            "heartbeat_tasks": len(self._heartbeat_tasks),
        }

    # ── Persistence ──

    async def _persist(self, session: Session) -> None:
        """Save session to SQLite."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        name TEXT,
                        user_id TEXT,
                        status TEXT,
                        created_at REAL,
                        last_heartbeat REAL,
                        last_activity REAL,
                        heartbeat_interval REAL,
                        idle_timeout REAL,
                        absolute_ttl REAL,
                        state TEXT
                    )
                """)
                await db.execute("""
                    INSERT OR REPLACE INTO sessions
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session.id, session.name, session.user_id,
                    session.status.value, session.created_at,
                    session.last_heartbeat, session.last_activity,
                    session.heartbeat_interval, session.idle_timeout,
                    session.absolute_ttl, session.state.to_json(),
                ))
                await db.commit()
        except Exception:
            pass

    async def _load_from_db(self, session_id: str) -> Optional[Session]:
        """Load a session from SQLite."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY, name TEXT, user_id TEXT,
                        status TEXT, created_at REAL, last_heartbeat REAL,
                        last_activity REAL, heartbeat_interval REAL,
                        idle_timeout REAL, absolute_ttl REAL, state TEXT
                    )
                """)
                cursor = await db.execute(
                    "SELECT * FROM sessions WHERE id = ?", (session_id,)
                )
                row = await cursor.fetchone()
                if not row:
                    return None

                session = Session(
                    id=row[0], name=row[1], user_id=row[2],
                    status=SessionStatus(row[3]),
                    created_at=row[4], last_heartbeat=row[5],
                    last_activity=row[6], heartbeat_interval=row[7],
                    idle_timeout=row[8], absolute_ttl=row[9],
                    state=SessionState.from_json(row[10]),
                )
                self._sessions[session.id] = session
                return session
        except Exception:
            return None
