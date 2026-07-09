"""Tests for agentos.core.streaming — SSE streaming system."""

import json

from agentos.core.streaming import (
    ResponseCollector,
    StreamChunk,
    StreamEmitter,
    StreamEvent,
)


class TestStreamEvent:
    def test_all_events(self):
        events = {e.value for e in StreamEvent}
        assert "start" in events
        assert "thinking" in events
        assert "tool_call" in events
        assert "complete" in events
        assert "error" in events


class TestStreamChunk:
    def test_to_sse_format(self):
        chunk = StreamChunk(event=StreamEvent.TEXT, data={"text": "hello"}, timestamp=100.0)
        sse = chunk.to_sse()
        assert sse.startswith("data: ")
        payload = json.loads(sse[6:].strip())
        assert payload["event"] == "text"
        assert payload["text"] == "hello"
        assert payload["ts"] == 100.0

    def test_is_terminal_complete(self):
        assert StreamChunk(event=StreamEvent.COMPLETE).is_terminal
        assert StreamChunk(event=StreamEvent.ERROR).is_terminal
        assert StreamChunk(event=StreamEvent.CANCELLED).is_terminal

    def test_is_not_terminal_text(self):
        assert not StreamChunk(event=StreamEvent.TEXT).is_terminal
        assert not StreamChunk(event=StreamEvent.THINKING).is_terminal
        assert not StreamChunk(event=StreamEvent.TOOL_CALL).is_terminal


class TestStreamEmitter:
    def test_emit_basic(self):
        em = StreamEmitter()
        chunk = em.emit(StreamEvent.START, agent="test")
        assert chunk.event == StreamEvent.START
        assert chunk.data["agent"] == "test"
        assert chunk.timestamp >= 0

    def test_thinking(self):
        em = StreamEmitter()
        chunk = em.thinking("let me think")
        assert chunk.event == StreamEvent.THINKING
        assert chunk.data["text"] == "let me think"

    def test_text(self):
        em = StreamEmitter()
        chunk = em.text("hello world")
        assert chunk.event == StreamEvent.TEXT
        assert chunk.data["text"] == "hello world"

    def test_tool_call(self):
        em = StreamEmitter()
        chunk = em.tool_call("search", {"q": "test"})
        assert chunk.event == StreamEvent.TOOL_CALL
        assert chunk.data["name"] == "search"
        assert chunk.data["arguments"] == {"q": "test"}

    def test_tool_result(self):
        em = StreamEmitter()
        chunk = em.tool_result("search", "found 5 results")
        assert chunk.event == StreamEvent.TOOL_RESULT
        assert chunk.data["result"] == "found 5 results"

    def test_error(self):
        em = StreamEmitter()
        chunk = em.error("something went wrong")
        assert chunk.event == StreamEvent.ERROR
        assert chunk.data["error"] == "something went wrong"

    def test_timestamp_monotonic(self):
        em = StreamEmitter()
        c1 = em.text("first")
        c2 = em.text("second")
        assert c2.timestamp >= c1.timestamp


class TestResponseCollector:
    def test_feed_and_full_text(self):
        rc = ResponseCollector()
        em = StreamEmitter()
        rc.feed(em.text("Hello"))
        rc.feed(em.text(" "))
        rc.feed(em.text("World"))
        assert rc.full_text == "Hello World"
        assert len(rc.chunks) == 3

    def test_feed_non_text(self):
        rc = ResponseCollector()
        em = StreamEmitter()
        rc.feed(em.emit(StreamEvent.START))
        rc.feed(em.thinking("hmm"))
        assert rc.full_text == ""
        assert len(rc.chunks) == 2
