"""
会话管理 — 多会话隔离与状态持久化。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Session:
    """Agent 会话记录。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    state: str = "active"  # active | completed | failed
    task: str = ""
    metadata: dict = field(default_factory=dict)


class SessionStore:
    """会话存储后端（内存实现，可替换为SQLite/Postgres）。"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, task: str, metadata: dict | None = None) -> Session:
        session = Session(task=task, metadata=metadata or {})
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def update_state(self, session_id: str, state: str):
        if session := self._sessions.get(session_id):
            session.state = state

    def list_active(self) -> list[Session]:
        return [s for s in self._sessions.values() if s.state == "active"]

    def delete(self, session_id: str):
        self._sessions.pop(session_id, None)
