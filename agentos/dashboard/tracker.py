"""
追踪状态管理器 — 记录 Agent 运行历史、会话、步骤。

数据存储在 ~/.agentos/tracker/ 下，以 JSONL 追加写入。
"""

from __future__ import annotations

import json
import time
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


TRACKER_DIR = Path.home() / ".agentos" / "tracker"


@dataclass
class StepRecord:
    """单步执行记录。"""
    step_index: int
    step_type: str       # "thinking" | "tool_call" | "tool_result" | "final_answer"
    detail: str          # 步骤内容摘要
    duration_ms: float
    tokens: int = 0


@dataclass
class SessionRecord:
    """单次会话完整记录。"""
    session_id: str
    task: str
    model: str
    provider: str
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    status: str = "running"   # "running" | "completed" | "error" | "cancelled"
    steps: list[StepRecord] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    error: str = ""


class Tracker:
    """线程安全的追踪记录器（文件级锁）+ 事件发布。

    支持订阅者模式：外部可 subscribe 回调，在 add_step/finish_session 时收到实时事件推送。
    """

    _instance: Tracker | None = None

    def __init__(self):
        TRACKER_DIR.mkdir(parents=True, exist_ok=True)
        self._sessions_file = TRACKER_DIR / "sessions.jsonl"
        self._active: dict[str, SessionRecord] = {}
        self._subscribers: list = []  # 回调列表

    @classmethod
    def get(cls) -> Tracker:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start_session(self, session_id: str, task: str, model: str = "", provider: str = "") -> SessionRecord:
        rec = SessionRecord(session_id=session_id, task=task, model=model, provider=provider)
        self._active[session_id] = rec
        return rec

    def add_step(self, session_id: str, step_type: str, detail: str, duration_ms: float = 0.0, tokens: int = 0):
        rec = self._active.get(session_id)
        if rec is None:
            return
        step = StepRecord(
            step_index=len(rec.steps),
            step_type=step_type,
            detail=detail,
            duration_ms=duration_ms,
            tokens=tokens,
        )
        rec.steps.append(step)
        rec.total_tokens += tokens
        self._notify("step", {"session_id": session_id, "step_type": step_type, "detail": detail, "duration_ms": duration_ms, "tokens": tokens})

    def finish_session(self, session_id: str, status: str = "completed", error: str = "", total_cost: float = 0.0):
        rec = self._active.pop(session_id, None)
        if rec is None:
            return
        rec.finished_at = time.time()
        rec.status = status
        rec.error = error
        rec.total_cost_usd = total_cost
        with open(self._sessions_file, "a") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
        self._notify("session_done", asdict(rec))

    def subscribe(self, callback):
        """订阅实时事件。callback 接收 (event_type: str, data: dict)。"""
        self._subscribers.append(callback)

    def unsubscribe(self, callback):
        """取消订阅。"""
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _notify(self, event_type: str, data: dict):
        for cb in self._subscribers:
            try:
                cb(event_type, data)
            except Exception:
                pass

    def list_sessions(self, limit: int = 50) -> list[dict]:
        sessions = []
        if self._sessions_file.exists():
            with open(self._sessions_file, "r") as f:
                for line in f:
                    if line.strip():
                        sessions.append(json.loads(line))
        # 倒序，最新的在前
        sessions.reverse()
        return sessions[:limit]

    def get_session(self, session_id: str) -> dict | None:
        # 先在 active 中找
        rec = self._active.get(session_id)
        if rec:
            return asdict(rec)
        # 再从文件中找
        if self._sessions_file.exists():
            with open(self._sessions_file, "r") as f:
                for line in f:
                    if line.strip():
                        d = json.loads(line)
                        if d.get("session_id") == session_id:
                            return d
        return None

    def clear(self):
        self._active.clear()
        if self._sessions_file.exists():
            self._sessions_file.unlink()
