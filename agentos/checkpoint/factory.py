"""
Checkpointer 工厂 — 统一创建不同后端的 Checkpointer。
"""

from __future__ import annotations

from typing import Any

from agentos.checkpoint.base import CheckpointBackend
from agentos.checkpoint.postgres import PostgresCheckpointer
from agentos.checkpoint.sqlite import SQLiteCheckpointer

__all__ = ["create_checkpointer"]


def create_checkpointer(
    backend: str = "sqlite",
    **kwargs: Any,
) -> CheckpointBackend:
    """
    创建 Checkpointer 实例。

    Args:
        backend: "sqlite" | "postgres"
        **kwargs: 后端特定参数
            - sqlite: db_path (默认 "checkpoints.db")
            - postgres: dsn (默认 "postgresql://localhost:5432/agentos")

    Returns:
        CheckpointBackend 实例。

    Raises:
        ValueError: 未知后端。
    """
    backend = backend.lower().strip()

    if backend == "sqlite":
        db_path = kwargs.pop("db_path", "checkpoints.db")
        return SQLiteCheckpointer(db_path=db_path, **kwargs)

    if backend == "postgres":
        return PostgresCheckpointer(**kwargs)

    raise ValueError(f"Unknown checkpoint backend: '{backend}'. Available: sqlite, postgres")
