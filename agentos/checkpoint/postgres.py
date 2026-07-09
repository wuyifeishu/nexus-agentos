"""
Postgres Checkpointer — 生产级持久化后端。

需安装: pip install asyncpg

参考 LangGraph PostgresSaver 的 schema 设计。
"""

from __future__ import annotations

import json
from typing import Any

from agentos.checkpoint.base import (
    Checkpoint,
    CheckpointBackend,
    CheckpointMetadata,
)

__all__ = ["PostgresCheckpointer"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id              BIGSERIAL PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    checkpoint_id   TEXT NOT NULL UNIQUE,
    parent_id       TEXT,
    step            INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tags            JSONB NOT NULL DEFAULT '[]',
    summary         TEXT NOT NULL DEFAULT '',
    messages_blob   JSONB NOT NULL DEFAULT '[]',
    state_blob      JSONB NOT NULL DEFAULT '{}',
    tools_blob      JSONB NOT NULL DEFAULT '{}',
    next_node       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_thread_step ON checkpoints(thread_id, step DESC);
CREATE INDEX IF NOT EXISTS idx_checkpoint_id ON checkpoints(checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_parent ON checkpoints(parent_id);
CREATE INDEX IF NOT EXISTS idx_created_at ON checkpoints(created_at DESC);
"""


class PostgresCheckpointer(CheckpointBackend):
    """Postgres 后端 Checkpointer — 生产环境推荐。

    用法:
        cp = PostgresCheckpointer(dsn="postgresql://user:pass@localhost:5432/agentos")
        await cp.put(checkpoint)
        latest = await cp.get_latest("thread_abc")
    """

    def __init__(self, dsn: str = "", **kwargs: Any):
        self._dsn = dsn or "postgresql://localhost:5432/agentos"
        self._kwargs = kwargs
        self._pool: Any = None
        self._initialized = False

    async def _ensure_pool(self):
        if self._pool is not None:
            return
        import asyncpg

        self._pool = await asyncpg.create_pool(dsn=self._dsn, **self._kwargs)
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA)

    async def put(self, checkpoint: Checkpoint) -> str:
        await self._ensure_pool()
        meta = checkpoint.metadata
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO checkpoints
                   (thread_id, checkpoint_id, parent_id, step, created_at, tags, summary,
                    messages_blob, state_blob, tools_blob, next_node)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                   ON CONFLICT (checkpoint_id) DO UPDATE SET
                     step=$4, messages_blob=$8, state_blob=$9, tools_blob=$10, next_node=$11""",
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
            )
        return meta.checkpoint_id

    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM checkpoints WHERE checkpoint_id = $1", checkpoint_id
            )
        return self._row_to_checkpoint(row) if row else None

    async def get_latest(self, thread_id: str) -> Checkpoint | None:
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM checkpoints WHERE thread_id = $1 ORDER BY step DESC LIMIT 1",
                thread_id,
            )
        return self._row_to_checkpoint(row) if row else None

    async def list_threads(self, limit: int = 50, offset: int = 0) -> list[CheckpointMetadata]:
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT ON (thread_id) *
                   FROM checkpoints
                   ORDER BY thread_id, step DESC
                   LIMIT $1 OFFSET $2""",
                limit,
                offset,
            )
        return [self._row_to_metadata(r) for r in rows]

    async def list_checkpoints(
        self, thread_id: str, limit: int = 100, offset: int = 0
    ) -> list[CheckpointMetadata]:
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM checkpoints WHERE thread_id = $1 ORDER BY step DESC LIMIT $2 OFFSET $3",
                thread_id,
                limit,
                offset,
            )
        return [self._row_to_metadata(r) for r in rows]

    async def delete_thread(self, thread_id: str) -> int:
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM checkpoints WHERE thread_id = $1", thread_id)
        return int(result.split()[-1]) if result else 0

    async def delete_before(self, thread_id: str, before_step: int) -> int:
        await self._ensure_pool()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = $1 AND step < $2",
                thread_id,
                before_step,
            )
        return int(result.split()[-1]) if result else 0

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _row_to_metadata(row: Any) -> CheckpointMetadata:
        return CheckpointMetadata(
            thread_id=row["thread_id"],
            checkpoint_id=row["checkpoint_id"],
            parent_checkpoint_id=row["parent_id"],
            step=row["step"],
            created_at=str(row["created_at"]),
            tags=row["tags"] if isinstance(row["tags"], list) else json.loads(row["tags"]),
            summary=row["summary"],
        )

    @staticmethod
    def _row_to_checkpoint(row: Any) -> Checkpoint:
        messages = (
            row["messages_blob"]
            if isinstance(row["messages_blob"], list)
            else json.loads(row["messages_blob"])
        )
        state = (
            row["state_blob"]
            if isinstance(row["state_blob"], dict)
            else json.loads(row["state_blob"])
        )
        tools = (
            row["tools_blob"]
            if isinstance(row["tools_blob"], dict)
            else json.loads(row["tools_blob"])
        )
        return Checkpoint(
            metadata=PostgresCheckpointer._row_to_metadata(row),
            messages=messages,
            state=state,
            tools_result=tools,
            next_node=row["next_node"],
        )
