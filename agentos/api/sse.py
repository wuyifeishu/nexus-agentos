"""
SSE (Server-Sent Events) Streaming — production-grade async streaming endpoint.

Provides an ASGI-compatible SSE stream with automatic reconnection,
client heartbeat, backpressure control, and typed event dispatching.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

DEFAULT_RETRY_MS = 3000
DEFAULT_HEARTBEAT_S = 30
MAX_QUEUE_SIZE = 256


class SSEEventType(StrEnum):
    """Standard SSE event types plus AgentOS extensions."""

    MESSAGE = "message"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    DONE = "done"
    PING = "ping"
    HEARTBEAT = "heartbeat"
    METADATA = "metadata"


@dataclass
class SSEEvent:
    """A single SSE event to be serialized to the wire."""

    event: str = SSEEventType.MESSAGE
    data: Any = ""
    id: str = ""
    retry: int = DEFAULT_RETRY_MS

    def serialize(self) -> str:
        """Serialize to raw SSE wire format."""
        lines: list[str] = []
        if self.event:
            lines.append(f"event: {self.event.value}")
        if self.id:
            lines.append(f"id: {self.id}")
        if self.retry != DEFAULT_RETRY_MS:
            lines.append(f"retry: {self.retry}")

        if isinstance(self.data, (dict, list)):
            data_str = json.dumps(self.data, ensure_ascii=False)
        else:
            data_str = str(self.data)

        # Multi-line data
        for line in data_str.split("\n"):
            lines.append(f"data: {line}")
        return "\n".join(lines) + "\n\n"

    @classmethod
    def token(cls, text: str, seq: int = 0) -> "SSEEvent":
        return cls(event=SSEEventType.TOKEN, data={"text": text, "seq": seq})

    @classmethod
    def tool_call(cls, name: str, args: dict) -> "SSEEvent":
        return cls(
            event=SSEEventType.TOOL_CALL,
            data={"name": name, "arguments": args},
        )

    @classmethod
    def tool_result(cls, name: str, result: Any) -> "SSEEvent":
        return cls(
            event=SSEEventType.TOOL_RESULT,
            data={"name": name, "result": result},
        )

    @classmethod
    def error(cls, message: str, code: str = "UNKNOWN") -> "SSEEvent":
        return cls(
            event=SSEEventType.ERROR,
            data={"message": message, "code": code},
        )

    @classmethod
    def done(cls, metadata: dict[str, Any] | None = None) -> "SSEEvent":
        return cls(
            event=SSEEventType.DONE,
            data=metadata or {},
        )

    @classmethod
    def metadata(cls, meta: dict[str, Any]) -> "SSEEvent":
        return cls(event=SSEEventType.METADATA, data=meta)


class SSEStream:
    """SSE stream with heartbeats and backpressure handling.

    Usage::

        stream = SSEStream(retry_ms=3000)
        # Producer
        await stream.queue.put(SSEEvent.token("Hello"))
        await stream.queue.put(SSEEvent.done())
        await stream.close()

        # Consumer (ASGI)
        async for chunk in stream.iter_chunks():
            yield chunk
    """

    def __init__(
        self,
        retry_ms: int = DEFAULT_RETRY_MS,
        heartbeat_s: float = DEFAULT_HEARTBEAT_S,
        max_queue: int = MAX_QUEUE_SIZE,
    ):
        self.retry_ms = retry_ms
        self.heartbeat_s = heartbeat_s
        self.queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue(maxsize=max_queue)
        self._closed = False
        self._heartbeat_task: asyncio.Task | None = None
        self._last_event_id = 0

    async def start(self):
        """Start the heartbeat background task."""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        """Send periodic heartbeat pings."""
        try:
            while not self._closed:
                await asyncio.sleep(self.heartbeat_s)
                if not self._closed:
                    await self.queue.put(
                        SSEEvent(
                            event=SSEEventType.HEARTBEAT,
                            data={"ts": time.time()},
                        )
                    )
        except asyncio.CancelledError:
            pass

    async def send(self, event: SSEEvent):
        """Enqueue an event. Raises QueueFull if backpressure exceeded."""
        if self._closed:
            raise RuntimeError("Stream is closed")
        self._last_event_id += 1
        if not event.id:
            event.id = str(self._last_event_id)
        self.queue.put_nowait(event)

    async def close(self):
        """Signal end of stream."""
        self._closed = True
        await self.queue.put(None)  # Sentinel
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def iter_events(self) -> AsyncIterator[SSEEvent]:
        """Async iterator over enqueued events."""
        while True:
            event = await self.queue.get()
            if event is None:
                break
            yield event

    async def iter_chunks(self) -> AsyncIterator[str]:
        """Async iterator yielding raw SSE wire-format chunks."""
        async for event in self.iter_events():
            yield event.serialize()


class SSEResponse:
    """Factory for generating ASGI-compatible SSE HTTP responses.

    Usage (Starlette / FastAPI)::

        from starlette.responses import StreamingResponse

        sse = SSEResponse(stream)
        return StreamingResponse(
            sse.body(),
            media_type="text/event-stream",
            headers=sse.headers(),
        )
    """

    HEADERS = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }

    def __init__(self, stream: SSEStream):
        self.stream = stream

    def headers(self) -> dict[str, str]:
        return dict(self.HEADERS)

    async def body(self) -> AsyncIterator[str]:
        """ASGI-compatible body iterator."""
        async for chunk in self.stream.iter_chunks():
            yield chunk
