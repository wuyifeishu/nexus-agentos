"""
SQLite Checkpointer — 零依赖本地持久化。

适用场景: 单机部署、开发调试、POC。
生产多机部署请使用 PostgresCheckpointer。
"""

from __future__ import annotations

import json
import os
import sqlite3

from agentos.checkpoint.base import (
    Checkpoint,
    CheckpointBackend,
    CheckpointMetadata,
)

__all__ = ["SQLiteCheckpointer"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id       TEXT NOT NULL,
    checkpoint_id   TEXT NOT NULL UNIQUE,
    parent_id       TEXT,
    step            INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    summary         TEXT NOT NULL DEFAULT '',
    messages_blob   TEXT NOT NULL DEFAULT '[]',
    state_blob      TEXT NOT NULL DEFAULT '{}',
    tools_blob      TEXT NOT NULL DEFAULT '{}',
    next_node       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_thread_step ON checkpoints(thread_id, step DESC);
CREATE INDEX IF NOT EXISTS idx_checkpoint_id ON checkpoints(checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_parent ON checkpoints(parent_id);
"""


class SQLiteCheckpointer(CheckpointBackend):
    """SQLite 后端 Checkpointer。

    用法:
        cp = SQLiteCheckpointer(db_path="data/checkpoints.db")
        await cp.put(checkpoint)
        latest = await cp.get_latest("thread_abc")
    """

    def __init__(self, db_path: str = "checkpoints.db"):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_metadata(self, row: sqlite3.Row) -> CheckpointMetadata:
        return CheckpointMetadata(
            thread_id=row["thread_id"],
            checkpoint_id=row["checkpoint_id"],
            parent_checkpoint_id=row["parent_id"],
            step=row["step"],
            created_at=row["created_at"],
            tags=json.loads(row["tags"]),
            summary=row["summary"],
        )

    def _row_to_checkpoint(self, row: sqlite3.Row) -> Checkpoint:
        return Checkpoint(
            metadata=self._row_to_metadata(row),
            messages=json.loads(row["messages_blob"]),
            state=json.loads(row["state_blob"]),
            tools_result=json.loads(row["tools_blob"]),
            next_node=row["next_node"],
        )

    async def put(self, checkpoint: Checkpoint) -> str:
        meta = checkpoint.metadata
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO checkpoints
                   (thread_id, checkpoint_id, parent_id, step, created_at, tags, summary,
                    messages_blob, state_blob, tools_blob, next_node)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meta.thread_id,
                    meta.checkpoint_id,
                    meta.parent_checkpoint_id,
                    meta.step,
                    meta.created_at,
                    json.dumps(meta.tags),
                    meta.summary,
                    json.dumps(checkpoint.messages, ensure_ascii=False),
                    json.dumps(checkpoint.state, ensure_ascii=False),
                    json.dumps(checkpoint.tools_result, ensure_ascii=False),
                    checkpoint.next_node,
                ),
            )
            conn.commit()
        return meta.checkpoint_id

    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,)
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    async def get_latest(self, thread_id: str) -> Checkpoint | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE thread_id = ? ORDER BY step DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    async def list_threads(self, limit: int = 50, offset: int = 0) -> list[CheckpointMetadata]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM checkpoints
                   WHERE checkpoint_id IN (
                       SELECT checkpoint_id FROM checkpoints
                       GROUP BY thread_id HAVING step = MAX(step)
                   )
                   ORDER BY created_at DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [self._row_to_metadata(r) for r in rows]

    async def list_checkpoints(
        self, thread_id: str, limit: int = 100, offset: int = 0
    ) -> list[CheckpointMetadata]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE thread_id = ? ORDER BY step DESC LIMIT ? OFFSET ?",
                (thread_id, limit, offset),
            ).fetchall()
        return [self._row_to_metadata(r) for r in rows]

    async def delete_thread(self, thread_id: str) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            conn.commit()
            return cur.rowcount

    async def delete_before(self, thread_id: str, before_step: int) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ? AND step < ?",
                (thread_id, before_step),
            )
            conn.commit()
            return cur.rowcount
