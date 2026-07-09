"""
A2A Task Store — persistent task and session storage for A2A protocol.

Backends: InMemory (default), SQLite, custom.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agentos.protocols.a2a import A2ATask, TaskState


class A2ATaskStore(ABC):
    """Abstract task store for A2A protocol persistence."""

    @abstractmethod
    def save_task(self, task: A2ATask) -> None:
        """Insert or update a task."""
        ...

    @abstractmethod
    def get_task(self, task_id: str) -> A2ATask | None:
        """Retrieve a task by ID."""
        ...

    @abstractmethod
    def list_tasks(
        self,
        state: TaskState | None = None,
        limit: int = 100,
        offset: int = 0,
        agent: str = "",
    ) -> list[A2ATask]:
        """List tasks, optionally filtered by state/agent."""
        ...

    @abstractmethod
    def delete_task(self, task_id: str) -> bool:
        """Delete a task. Returns True if deleted."""
        ...

    @abstractmethod
    def cleanup_terminal(
        self,
        max_age_seconds: float = 3600.0,
    ) -> int:
        """Remove terminal tasks older than max_age. Returns count."""
        ...

    @abstractmethod
    def count(self, state: TaskState | None = None) -> int:
        """Count tasks, optionally filtered by state."""
        ...


class InMemoryTaskStore(A2ATaskStore):
    """Fast, non-persistent task store for development/testing."""

    def __init__(self):
        self._tasks: dict[str, A2ATask] = {}
        self._lock = threading.Lock()

    def save_task(self, task: A2ATask) -> None:
        with self._lock:
            self._tasks[task.task_id] = task

    def get_task(self, task_id: str) -> A2ATask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(
        self,
        state: TaskState | None = None,
        limit: int = 100,
        offset: int = 0,
        agent: str = "",
    ) -> list[A2ATask]:
        with self._lock:
            tasks = list(self._tasks.values())
        if state:
            tasks = [t for t in tasks if t.state == state]
        if agent:
            tasks = [t for t in tasks if t.meta.get("target_agent") == agent]
        return tasks[offset : offset + limit]

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                return True
            return False

    def cleanup_terminal(self, max_age_seconds: float = 3600.0) -> int:
        now = time.time()
        with self._lock:
            to_del = [
                tid
                for tid, t in self._tasks.items()
                if t.is_terminal() and (now - t._updated) > max_age_seconds
            ]
            for tid in to_del:
                del self._tasks[tid]
        return len(to_del)

    def count(self, state: TaskState | None = None) -> int:
        if state is None:
            with self._lock:
                return len(self._tasks)
        tasks = self.list_tasks(state=state, limit=999999)
        return len(tasks)


class SqliteTaskStore(A2ATaskStore):
    """Persistent SQLite-backed task store for production use."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS a2a_tasks (
        task_id TEXT PRIMARY KEY,
        state TEXT NOT NULL DEFAULT 'submitted',
        input_json TEXT,
        output_json TEXT,
        artifacts_json TEXT DEFAULT '[]',
        error TEXT,
        meta_json TEXT DEFAULT '{}',
        created REAL NOT NULL,
        updated REAL NOT NULL,
        agent TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_a2a_state ON a2a_tasks(state);
    CREATE INDEX IF NOT EXISTS idx_a2a_agent ON a2a_tasks(agent);
    CREATE INDEX IF NOT EXISTS idx_a2a_updated ON a2a_tasks(updated);
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(self.SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        yield self._local.conn

    def save_task(self, task: A2ATask) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO a2a_tasks
                   (task_id, state, input_json, output_json, artifacts_json,
                    error, meta_json, created, updated, agent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.task_id,
                    task.state.value,
                    json.dumps(task.input.to_dict()) if task.input else None,
                    json.dumps(task.output.to_dict()) if task.output else None,
                    json.dumps([a.to_dict() for a in task.artifacts]),
                    task.error,
                    json.dumps(task.meta),
                    task._created,
                    task._updated,
                    task.meta.get("target_agent", ""),
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> A2ATask | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM a2a_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_task(row)

    def list_tasks(
        self,
        state: TaskState | None = None,
        limit: int = 100,
        offset: int = 0,
        agent: str = "",
    ) -> list[A2ATask]:
        query = "SELECT * FROM a2a_tasks WHERE 1=1"
        params: list[Any] = []
        if state:
            query += " AND state = ?"
            params.append(state.value)
        if agent:
            query += " AND agent = ?"
            params.append(agent)
        query += " ORDER BY updated DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_task(r) for r in rows]

    def delete_task(self, task_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM a2a_tasks WHERE task_id = ?", (task_id,))
            conn.commit()
            return cur.rowcount > 0

    def cleanup_terminal(self, max_age_seconds: float = 3600.0) -> int:
        cutoff = time.time() - max_age_seconds
        with self._conn() as conn:
            cur = conn.execute(
                """DELETE FROM a2a_tasks
                   WHERE state IN ('completed', 'failed', 'cancelled')
                   AND updated < ?""",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount

    def count(self, state: TaskState | None = None) -> int:
        query = "SELECT COUNT(*) FROM a2a_tasks"
        params: list[Any] = []
        if state:
            query += " WHERE state = ?"
            params.append(state.value)
        with self._conn() as conn:
            return conn.execute(query, params).fetchone()[0]

    def _row_to_task(self, row) -> A2ATask:
        from agentos.protocols.a2a import A2AArtifact, A2AMessage

        task = A2ATask(
            task_id=row["task_id"],
            state=TaskState(row["state"]),
            error=row["error"],
            meta=json.loads(row["meta_json"] or "{}"),
            _created=row["created"],
            _updated=row["updated"],
        )
        if row["input_json"]:
            task.input = A2AMessage.from_dict(json.loads(row["input_json"]))
        if row["output_json"]:
            task.output = A2AMessage.from_dict(json.loads(row["output_json"]))
        task.artifacts = [
            A2AArtifact.from_dict(a) for a in json.loads(row["artifacts_json"] or "[]")
        ]
        return task
