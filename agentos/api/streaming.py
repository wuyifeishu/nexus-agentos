"""
Streaming SSE (Server-Sent Events) endpoint for agent interactions.

Provides real-time streaming of agent outputs via HTTP SSE, enabling
browser-based chat UIs and real-time monitoring dashboards.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class StreamEvent:
    """Single SSE event emitted by the stream."""

    event: str
    """Event type: 'chunk', 'tool_call', 'tool_result', 'done', 'error'."""

    data: dict[str, Any]
    """Event payload as JSON-serializable dict."""

    id: Optional[str] = None
    """Optional event ID for resume support."""

    retry: Optional[int] = None
    """Reconnection retry interval in milliseconds."""

    def to_sse(self) -> str:
        """Format as SSE wire format."""
        lines: list[str] = []
        if self.id:
            lines.append(f"id: {self.id}")
        if self.event:
            lines.append(f"event: {self.event}")
        lines.append(f"data: {json.dumps(self.data, ensure_ascii=False)}")
        if self.retry:
            lines.append(f"retry: {self.retry}")
        lines.append("")  # blank line terminates event
        return "\n".join(lines)


@dataclass
class StreamSession:
    """Track an active streaming session."""

    session_id: str
    started_at: float = field(default_factory=time.time)
    events_emitted: int = 0
    last_event_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class StreamingAgent:
    """
    Agent that emits Server-Sent Events for real-time streaming.

    Example (FastAPI integration)::

        streaming = StreamingAgent(agent_loop)

        @app.get("/agent/stream")
        async def stream():
            return StreamingResponse(
                streaming.stream_chat("What is quantum computing?", "session-1"),
                media_type="text/event-stream"
            )
    """

    def __init__(
        self,
        agent_loop: Any = None,
        heartbeat_interval: float = 15.0,
    ):
        """
        Args:
            agent_loop: The underlying agent loop (sync or async).
            heartbeat_interval: Seconds between heartbeat keepalive events.
        """
        self._loop = agent_loop
        self._heartbeat = heartbeat_interval
        self._sessions: dict[str, StreamSession] = defaultdict(StreamSession)

    async def stream_chat(
        self,
        message: str,
        session_id: str = "default",
    ) -> AsyncIterator[str]:
        """
        Stream a chat interaction as SSE events.

        Yields:
            SSE-formatted strings suitable for HTTP response body.
        """
        session = self._sessions[session_id]
        session.session_id = session_id
        t_start = time.time()

        # Emit start event
        yield StreamEvent(
            event="start",
            data={"session_id": session_id, "message": message},
        ).to_sse()
        session.events_emitted += 1

        # Simulate streaming chunks (integrate with real agent loop)
        chunks = self._generate_chunks(message)
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(session_id)
        )

        try:
            async for chunk in chunks:
                yield StreamEvent(
                    event="chunk",
                    data={"content": chunk, "session_id": session_id},
                ).to_sse()
                session.events_emitted += 1
                session.last_event_at = time.time()
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        # Emit done event
        total_ms = (time.time() - t_start) * 1000
        yield StreamEvent(
            event="done",
            data={
                "session_id": session_id,
                "total_latency_ms": total_ms,
                "events_emitted": session.events_emitted,
            },
        ).to_sse()

    def stream_chat_sync(self, message: str, session_id: str = "default"):
        """Synchronous wrapper for stream_chat."""
        loop = asyncio.get_event_loop()
        return _SyncSSEWrapper(
            loop.run_until_complete(
                self._collect_events(message, session_id)
            )
        )

    async def _collect_events(
        self, message: str, session_id: str
    ) -> list[str]:
        events: list[str] = []
        async for sse in self.stream_chat(message, session_id):
            events.append(sse)
        return events

    async def _generate_chunks(self, message: str) -> AsyncIterator[str]:
        """Generate streaming text chunks. Override with real LLM integration."""
        if self._loop and hasattr(self._loop, "run"):
            # Integrate with actual agent loop
            result = self._loop.run(message)
            text = str(result.output) if hasattr(result, "output") else str(result)
            words = text.split()
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield chunk
                await asyncio.sleep(0.02)  # simulate streaming
        else:
            # Fallback: simulate streaming
            words = message.split()
            yield f"Processing: {message}\n"
            await asyncio.sleep(0.3)
            for i in range(3):
                yield f"Agent step {i + 1}: analyzing...\n"
                await asyncio.sleep(0.5)
            yield f"Complete. Response for: {message}"

    async def _heartbeat_loop(self, session_id: str) -> None:
        """Send periodic heartbeat comments to keep connection alive."""
        while True:
            await asyncio.sleep(self._heartbeat)

    def emit_tool_call(self, session_id: str, tool_name: str, args: dict) -> str:
        """Emit a tool_call SSE event (non-streaming helper)."""
        return StreamEvent(
            event="tool_call",
            data={
                "session_id": session_id,
                "tool": tool_name,
                "arguments": args,
            },
        ).to_sse()

    def emit_tool_result(
        self, session_id: str, tool_name: str, result: Any
    ) -> str:
        """Emit a tool_result SSE event."""
        return StreamEvent(
            event="tool_result",
            data={
                "session_id": session_id,
                "tool": tool_name,
                "result": result,
            },
        ).to_sse()

    def emit_error(self, session_id: str, error: str) -> str:
        """Emit an error SSE event."""
        return StreamEvent(
            event="error",
            data={"session_id": session_id, "error": error},
        ).to_sse()

    def get_session(self, session_id: str) -> Optional[StreamSession]:
        return self._sessions.get(session_id)

    def list_sessions(self) -> dict[str, StreamSession]:
        return dict(self._sessions)


class _SyncSSEWrapper:
    """Makes a list of SSE strings iterable for sync streaming."""

    def __init__(self, events: list[str]):
        self._events = events

    def __iter__(self):
        return iter(self._events)
