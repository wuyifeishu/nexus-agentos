"""
AgentOS v0.20 持久化存储层。
Base + SQLite实现，支持Checkpoint持久化。
"""

from __future__ import annotations

import json
import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

# ── 抽象基类 ────────────────────────────────────


class CheckpointStore(ABC):
    """检查点存储基类。"""

    @abstractmethod
    async def save(self, session_id: str, snapshot: dict): ...
    @abstractmethod
    async def load(self, session_id: str) -> dict | None: ...
    @abstractmethod
    async def delete(self, session_id: str): ...
    @abstractmethod
    async def list_sessions(self, limit: int = 50) -> list[str]: ...


@dataclass
class SqliteStore(CheckpointStore):
    """SQLite 持久化存储。"""

    path: str = ":memory:"

    def __post_init__(self):
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                session_id TEXT PRIMARY KEY,
                snapshot TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_updated ON checkpoints(updated_at DESC)")
        self._conn.commit()

    async def save(self, session_id: str, snapshot: dict):
        now = time.time()
        self._conn.execute(
            """INSERT INTO checkpoints(session_id, snapshot, created_at, updated_at)
               VALUES(?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
               snapshot=excluded.snapshot, updated_at=excluded.updated_at""",
            (session_id, json.dumps(snapshot, default=str), now, now),
        )
        self._conn.commit()

    async def load(self, session_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT snapshot FROM checkpoints WHERE session_id=?", (session_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    async def delete(self, session_id: str):
        self._conn.execute("DELETE FROM checkpoints WHERE session_id=?", (session_id,))
        self._conn.commit()

    async def list_sessions(self, limit: int = 50) -> list[str]:
        rows = self._conn.execute(
            "SELECT session_id FROM checkpoints ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r[0] for r in rows]
