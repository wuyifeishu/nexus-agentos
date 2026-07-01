"""
AgentOS v0.20 流式输出系统。
支持 SSE (Server-Sent Events) 格式流式传输。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StreamEvent(str, Enum):

    """流式事件。"""

    START = "start"
    STEP_START = "step_start"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TEXT = "text"
    ERROR = "error"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


@dataclass
class StreamChunk:
    """流式输出的单块数据。"""

    event: StreamEvent
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0  # auto-filled by emitter

    def to_sse(self) -> str:
        import json
        payload = {
            "event": self.event.value,
            **self.data,
            "ts": self.timestamp,
        }
        return f"data: {json.dumps(payload, default=str)}\n\n"

    @property
    def is_terminal(self) -> bool:
        return self.event in (StreamEvent.COMPLETE, StreamEvent.ERROR, StreamEvent.CANCELLED)


class StreamEmitter:
    """异步SSE发射器。"""

    def __init__(self):
        import time
        self._start = time.time()

    def emit(self, event: StreamEvent, **data) -> StreamChunk:
        import time
        chunk = StreamChunk(event=event, data=data)
        chunk.timestamp = (time.time() - self._start) * 1000
        return chunk

    def thinking(self, text: str) -> StreamChunk:
        return self.emit(StreamEvent.THINKING, text=text)

    def text(self, text: str) -> StreamChunk:
        return self.emit(StreamEvent.TEXT, text=text)

    def tool_call(self, name: str, args: dict) -> StreamChunk:
        return self.emit(StreamEvent.TOOL_CALL, name=name, arguments=args)

    def tool_result(self, name: str, result: str) -> StreamChunk:
        return self.emit(StreamEvent.TOOL_RESULT, name=name, result=result)

    def error(self, message: str) -> StreamChunk:
        return self.emit(StreamEvent.ERROR, error=message)


class ResponseCollector:
    """收集流式chunk并拼接为最终响应。"""

    def __init__(self):
        self.chunks: list[StreamChunk] = []
        self._text_buf: list[str] = []

    def feed(self, chunk: StreamChunk):
        self.chunks.append(chunk)
        if chunk.event == StreamEvent.TEXT:
            self._text_buf.append(chunk.data.get("text", ""))

    @property
    def full_text(self) -> str:
        return "".join(self._text_buf)
