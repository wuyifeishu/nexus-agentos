"""
A2A Streaming — real-time task status updates via SSE for A2A protocol.

Provides push-based task lifecycle notifications so agents don't poll.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, Optional

from agentos.protocols.a2a import A2ATask, TaskState


class A2AStreamEvent(str, Enum):
    """A2A-specific streaming event types."""

    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    ARTIFACT_ADDED = "artifact.added"
    HEARTBEAT = "heartbeat"


@dataclass
class TaskProgress:
    """Progress update within a running task."""

    percent: float = 0.0
    message: str = ""
    step: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class A2AStreamSession:
    """Manages a streaming connection for a single task.

    Agents subscribe to receive push updates as the task progresses.
    """

    def __init__(self, task: A2ATask):
        self.task_id = task.task_id
        self._subscribers: list[asyncio.Queue[dict]] = []
        self._closed = False
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def start(self, heartbeat_s: float = 30.0):
        """Start heartbeat loop."""
        async def _pulse():
            while not self._closed:
                await asyncio.sleep(heartbeat_s)
                if not self._closed:
                    await self._broadcast({
                        "event": A2AStreamEvent.HEARTBEAT,
                        "task_id": self.task_id,
                        "timestamp": time.time(),
                    })
        self._heartbeat_task = asyncio.create_task(_pulse())

    def subscribe(self) -> asyncio.Queue[dict]:
        """Register a new subscriber. Returns a queue of SSE events."""
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=64)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, sub: asyncio.Queue):
        """Remove a subscriber."""
        try:
            self._subscribers.remove(sub)
        except ValueError:
            pass

    async def emit(self, event: A2AStreamEvent, data: dict | None = None):
        """Push an event to all subscribers."""
        payload = {
            "event": event.value,
            "task_id": self.task_id,
            "timestamp": time.time(),
        }
        if data:
            payload["data"] = data
        await self._broadcast(payload)

    async def _broadcast(self, payload: dict):
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    async def close(self):
        """Shut down the stream."""
        self._closed = True
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        # Close all subscriber queues
        for q in self._subscribers:
            try:
                q.put_nowait(None)  # Sentinel
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()

    async def iter_events(self, subscriber: asyncio.Queue) -> AsyncIterator[dict]:
        """Async iterator yielding SSE-compatible event dicts."""
        while True:
            event = await subscriber.get()
            if event is None:
                break
            yield event

    def to_sse(self, event: dict) -> str:
        """Format a single event dict into SSE wire format."""
        lines: list[str] = [f"event: {event['event']}"]
        for key in ("task_id", "timestamp"):
            if key in event:
                lines.append(f"id: {key}={event[key]}")
        data_str = json.dumps(event.get("data", {}), ensure_ascii=False)
        for line in data_str.split("\n"):
            lines.append(f"data: {line}")
        return "\n".join(lines) + "\n\n"


class A2AStreamManager:
    """Global manager for A2A task streaming sessions.

    Tracks all active task streams and dispatches events on state transitions.
    """

    def __init__(self):
        self._sessions: dict[str, A2AStreamSession] = {}
        self._on_state_change: Optional[Callable] = None

    def on_state_change(self, callback: Callable[[A2ATask, TaskState, TaskState], Any]):
        """Register a hook called on every state transition (old_state, new_state)."""
        self._on_state_change = callback

    def create_session(self, task: A2ATask) -> A2AStreamSession:
        """Create a streaming session for a new task."""
        session = A2AStreamSession(task)
        self._sessions[task.task_id] = session
        return session

    def get_session(self, task_id: str) -> Optional[A2AStreamSession]:
        return self._sessions.get(task_id)

    async def notify_state_change(self, task: A2ATask, old_state: TaskState):
        """Called when a task transitions state."""
        session = self._sessions.get(task.task_id)
        if not session:
            return

        event_map = {
            TaskState.SUBMITTED: A2AStreamEvent.TASK_CREATED,
            TaskState.WORKING: A2AStreamEvent.TASK_STARTED,
            TaskState.COMPLETED: A2AStreamEvent.TASK_COMPLETED,
            TaskState.FAILED: A2AStreamEvent.TASK_FAILED,
            TaskState.CANCELLED: A2AStreamEvent.TASK_CANCELLED,
        }
        event = event_map.get(task.state, A2AStreamEvent.TASK_PROGRESS)
        await session.emit(event, {
            "previous_state": old_state.value,
            "current_state": task.state.value,
            "error": task.error,
        })

        if task.is_terminal():
            await session.close()
            del self._sessions[task.task_id]

    async def notify_artifact(self, task_id: str, artifact_name: str):
        """Called when an artifact is added to a task."""
        session = self._sessions.get(task_id)
        if session:
            await session.emit(A2AStreamEvent.ARTIFACT_ADDED, {
                "artifact_name": artifact_name,
            })

    async def notify_progress(
        self,
        task_id: str,
        progress: TaskProgress,
    ):
        """Push a progress update to subscribers."""
        session = self._sessions.get(task_id)
        if session:
            await session.emit(A2AStreamEvent.TASK_PROGRESS, {
                "percent": progress.percent,
                "message": progress.message,
                "step": progress.step,
                "metadata": progress.metadata,
            })

    async def shutdown(self):
        """Gracefully close all sessions."""
        for sid in list(self._sessions.keys()):
            session = self._sessions[sid]
            await session.close()
        self._sessions.clear()
