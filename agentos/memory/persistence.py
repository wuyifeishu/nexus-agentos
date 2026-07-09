"""
AgentOS v1.14.9 — Memory Persistence Manager.

Unified save/load for all 12 memory subsystems, bridging the gap between
the existing in-memory pyramid and crash-safe disk persistence.

All writes are atomic (write to temp file, then rename). JSON format with
gzip compression for production efficiency; plain JSON for debug.

Usage:
    mgr = MemoryPersistenceManager(base_dir="~/.agentos/memory")

    # Save everything
    await mgr.save_all(
        pyramid=pyramid,
        working=working,
        conversation=conv,
        long_term=lterm,
        reflection_engine=reflection,
        consolidation_pipeline=pipeline,
        retriever_index=retriever_index,
    )

    # Restore everything
    state = await mgr.load_all()
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Snapshot Data Models ──────────────────────


@dataclass
class MemorySnapshot:
    """Complete state of all memory subsystems at a point in time."""

    version: str = "1.14.9"
    created_at: float = field(default_factory=time.time)
    # Per-subsystem state dicts (optional — only non-empty ones are saved)
    pyramid_state: dict[str, Any] = field(default_factory=dict)
    working_state: dict[str, Any] = field(default_factory=dict)
    conversation_state: dict[str, Any] = field(default_factory=dict)
    long_term_state: dict[str, Any] = field(default_factory=dict)
    reflection_state: dict[str, Any] = field(default_factory=dict)
    consolidation_state: dict[str, Any] = field(default_factory=dict)
    retriever_index_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "version": self.version,
            "created_at": self.created_at,
        }
        for field_name in [
            "pyramid_state",
            "working_state",
            "conversation_state",
            "long_term_state",
            "reflection_state",
            "consolidation_state",
            "retriever_index_state",
        ]:
            val = getattr(self, field_name)
            if val:
                result[field_name] = val
        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MemorySnapshot:
        return cls(
            version=d.get("version", "1.14.9"),
            created_at=d.get("created_at", time.time()),
            pyramid_state=d.get("pyramid_state", {}),
            working_state=d.get("working_state", {}),
            conversation_state=d.get("conversation_state", {}),
            long_term_state=d.get("long_term_state", {}),
            reflection_state=d.get("reflection_state", {}),
            consolidation_state=d.get("consolidation_state", {}),
            retriever_index_state=d.get("retriever_index_state", {}),
        )


# ── Persistence Manager ──────────────────────


class MemoryPersistenceManager:
    """Centralized save/load manager for all memory subsystems.

    Writes snapshots as compressed JSON files under base_dir.
    Supports atomic writes (temp file + rename) and optional gzip compression.
    """

    def __init__(
        self,
        base_dir: str = "",
        compress: bool = True,
    ):
        base = Path(base_dir) if base_dir else Path.home() / ".agentos" / "memory"
        base.mkdir(parents=True, exist_ok=True)
        self.base_dir: Path = base
        self.compress = compress
        self._snapshot_path: Path = base / ("snapshot.json.gz" if compress else "snapshot.json")
        self._max_backups: int = 3

    # ── Save ────────────────────────────────

    async def save_all(
        self,
        pyramid: Any = None,
        working: Any = None,
        conversation: Any = None,
        long_term: Any = None,
        reflection_engine: Any = None,
        consolidation_pipeline: Any = None,
        retriever_index: dict[str, Any] | None = None,
    ) -> str:
        """Save all memory subsystems to a single snapshot file.

        Each subsystem provides a get_state() / dump_state() method;
        we probe for supported interfaces and extract what we can.

        Returns the snapshot file path.
        """
        snapshot = MemorySnapshot()

        if pyramid is not None:
            try:
                snapshot.pyramid_state = pyramid.get_state()
            except AttributeError:
                pass

        if working is not None:
            try:
                snapshot.working_state = working.get_state()
            except AttributeError:
                pass

        if conversation is not None:
            try:
                snapshot.conversation_state = conversation.get_state()
            except AttributeError:
                pass

        if long_term is not None:
            try:
                snapshot.long_term_state = long_term.get_state()
            except AttributeError:
                pass

        if reflection_engine is not None:
            try:
                snapshot.reflection_state = reflection_engine.get_state()
            except AttributeError:
                pass

        if consolidation_pipeline is not None:
            try:
                snapshot.consolidation_state = consolidation_pipeline.get_state()
            except AttributeError:
                pass

        if retriever_index is not None:
            snapshot.retriever_index_state = retriever_index

        return self._atomic_write(snapshot)

    def save_sync(
        self,
        pyramid: Any = None,
        working: Any = None,
        conversation: Any = None,
        long_term: Any = None,
        reflection_engine: Any = None,
        consolidation_pipeline: Any = None,
        retriever_index: dict[str, Any] | None = None,
    ) -> str:
        """Synchronous save — for use in signal handlers / atexit hooks."""
        snapshot = MemorySnapshot()

        for obj, attr in [
            (pyramid, "pyramid_state"),
            (working, "working_state"),
            (conversation, "conversation_state"),
            (long_term, "long_term_state"),
            (reflection_engine, "reflection_state"),
            (consolidation_pipeline, "consolidation_state"),
        ]:
            if obj is not None:
                try:
                    setattr(snapshot, attr, obj.get_state())
                except AttributeError:
                    pass

        if retriever_index is not None:
            snapshot.retriever_index_state = retriever_index

        return self._atomic_write(snapshot)

    # ── Load ────────────────────────────────

    async def load_all(self) -> MemorySnapshot:
        """Load the latest memory snapshot from disk.

        Returns a MemorySnapshot; empty fields mean no saved state for that subsystem.
        """
        if not self._snapshot_path.exists():
            return MemorySnapshot()

        data = self._read_snapshot_file()
        if data is None:
            return MemorySnapshot()

        return MemorySnapshot.from_dict(data)

    def load_sync(self) -> MemorySnapshot:
        """Synchronous load."""
        if not self._snapshot_path.exists():
            return MemorySnapshot()

        data = self._read_snapshot_file()
        if data is None:
            return MemorySnapshot()

        return MemorySnapshot.from_dict(data)

    async def restore_all(
        self,
        pyramid: Any = None,
        working: Any = None,
        conversation: Any = None,
        long_term: Any = None,
        reflection_engine: Any = None,
        consolidation_pipeline: Any = None,
        retriever_index_target: dict[str, Any] | None = None,
    ) -> int:
        """Load snapshot from disk and restore into live objects.

        Each target object must have a restore_state(state_dict) method.
        Returns count of subsystems restored.
        """
        snapshot = await self.load_all()
        restored = 0

        for obj, state_attr in [
            (pyramid, "pyramid_state"),
            (working, "working_state"),
            (conversation, "conversation_state"),
            (long_term, "long_term_state"),
            (reflection_engine, "reflection_state"),
            (consolidation_pipeline, "consolidation_state"),
        ]:
            state = getattr(snapshot, state_attr, {})
            if obj is not None and state:
                try:
                    obj.restore_state(state)
                    restored += 1
                except AttributeError:
                    pass

        if retriever_index_target is not None and snapshot.retriever_index_state:
            retriever_index_target.clear()
            retriever_index_target.update(snapshot.retriever_index_state)
            restored += 1

        return restored

    # ── Atomic write ────────────────────────

    def _atomic_write(self, snapshot: MemorySnapshot) -> str:
        """Write snapshot atomically: temp file → rename."""
        data = snapshot.to_dict()
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")

        if self.compress:
            json_bytes = gzip.compress(json_bytes, compresslevel=6)

        # Write to temp file, then rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.base_dir),
            prefix=".snapshot-tmp-",
            suffix=".json.gz" if self.compress else ".json",
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(json_bytes)

            # Rotate old backups
            self._rotate_backups()

            os.replace(tmp_path, str(self._snapshot_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return str(self._snapshot_path)

    # ── Read snapshot ────────────────────────

    def _read_snapshot_file(self) -> dict[str, Any] | None:
        """Read and parse snapshot file. Returns None on failure."""
        try:
            with open(self._snapshot_path, "rb") as f:
                raw = f.read()

            if self.compress:
                raw = gzip.decompress(raw)

            return json.loads(raw.decode("utf-8"))
        except (OSError, json.JSONDecodeError, gzip.BadGzipFile):
            return None

    # ── Backup rotation ──────────────────────

    def _rotate_backups(self) -> None:
        """Rotate old snapshot backups, keeping self._max_backups."""
        for i in range(self._max_backups - 1, 0, -1):
            old_path = self.base_dir / f"snapshot.{i}.json.gz"
            new_path = self.base_dir / f"snapshot.{i + 1}.json.gz"
            if old_path.exists():
                try:
                    os.replace(str(old_path), str(new_path))
                except OSError:
                    pass

        # Rotate current into .1
        if self._snapshot_path.exists():
            backup_path = self.base_dir / "snapshot.1.json.gz"
            try:
                os.replace(str(self._snapshot_path), str(backup_path))
            except OSError:
                pass

    # ── Query ────────────────────────────────

    def snapshot_info(self) -> dict[str, Any]:
        """Return metadata about the current snapshot."""
        if not self._snapshot_path.exists():
            return {"exists": False}

        try:
            stat = self._snapshot_path.stat()
            snapshot = self.load_sync()

            subsystems_saved = sum(
                1
                for v in [
                    snapshot.pyramid_state,
                    snapshot.working_state,
                    snapshot.conversation_state,
                    snapshot.long_term_state,
                    snapshot.reflection_state,
                    snapshot.consolidation_state,
                    snapshot.retriever_index_state,
                ]
                if v
            )

            return {
                "exists": True,
                "path": str(self._snapshot_path),
                "size_bytes": stat.st_size,
                "created_at": snapshot.created_at,
                "version": snapshot.version,
                "subsystems_saved": subsystems_saved,
                "compressed": self.compress,
            }
        except Exception:
            return {"exists": True, "error": "unreadable"}

    def delete_snapshot(self) -> bool:
        """Delete the current snapshot file(s)."""
        deleted = False
        for path in self.base_dir.glob("snapshot*.json.gz"):
            try:
                path.unlink()
                deleted = True
            except OSError:
                pass
        for path in self.base_dir.glob("snapshot*.json"):
            try:
                path.unlink()
                deleted = True
            except OSError:
                pass
        return deleted

    def list_backups(self) -> list[dict[str, Any]]:
        """List all available snapshot backups."""
        results = []
        for path in sorted(self.base_dir.glob("snapshot*.json*")):
            try:
                stat = path.stat()
                results.append(
                    {
                        "name": path.name,
                        "size_bytes": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
            except OSError:
                continue
        return results
