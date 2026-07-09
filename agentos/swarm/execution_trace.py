"""
v1.9.6: Execution Trace — full observability into Agent task execution.

Captures every sub-task, gate evaluation, retry, and timing detail.
Supports timeline visualization, bottleneck detection, and debugging.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TraceEvent(StrEnum):
    """Event types in an execution trace."""

    TASK_START = "task_start"
    TASK_END = "task_end"
    SUBTASK_START = "subtask_start"
    SUBTASK_END = "subtask_end"
    DECOMPOSE = "decompose"
    FUSE = "fuse"
    RETRY = "retry"
    FALLBACK = "fallback"
    GATE_CHECK = "gate_check"
    HITL_BREAK = "hitl_break"
    HITL_RESUME = "hitl_resume"
    SANDBOX_RUN = "sandbox_run"
    ERROR = "error"
    ABORT = "abort"


@dataclass
class TraceSpan:
    """A single span in an execution trace."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    parent_id: str = ""
    event: TraceEvent = TraceEvent.TASK_START
    name: str = ""
    status: str = "started"  # started, done, failed, aborted
    start_ms: float = field(default_factory=lambda: time.time() * 1000)
    end_ms: float = 0.0
    duration_ms: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    children: list[TraceSpan] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "event": self.event.value,
            "name": self.name,
            "status": self.status,
            "start_ms": f"{self.start_ms:.1f}",
            "end_ms": f"{self.end_ms:.1f}" if self.end_ms else "-",
            "duration_ms": f"{self.duration_ms:.1f}",
            "data": {k: str(v)[:100] for k, v in self.data.items()},
            "tags": self.tags,
            "children": [c.to_dict() for c in self.children] if self.children else [],
        }

    def to_flat_list(self) -> list[dict]:
        """Flatten tree to list for tabular display."""
        rows = [self.to_dict()]
        for child in self.children:
            rows.extend(child.to_flat_list())
        return rows


@dataclass
class ExecutionTrace:
    """
    Full execution trace for a single task execution.

    Captures a tree of spans representing every step: decomposition,
    sub-task execution, fusion, retries, gate checks, etc.

    Usage:
        trace = ExecutionTrace(task_name="research_query")

        span = trace.start_span(TraceEvent.TASK_START, name="main")
        # ... do work ...
        trace.end_span(span.id, status="done")

        print(trace.summary())
        print(trace.to_json())
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_name: str = ""
    root_span: TraceSpan | None = None
    _span_map: dict[str, TraceSpan] = field(default_factory=dict)
    _current_spans: list[str] = field(default_factory=list)  # stack
    total_spans: int = 0
    total_retries: int = 0
    total_errors: int = 0
    total_fallbacks: int = 0
    created_at: float = field(default_factory=time.time)

    def start_span(
        self,
        event: TraceEvent,
        name: str = "",
        data: dict | None = None,
        tags: list[str] | None = None,
    ) -> TraceSpan:
        """Start a new span and add it to the trace tree."""
        span = TraceSpan(
            event=event,
            name=name,
            data=data or {},
            tags=tags or [],
        )

        # Determine parent
        if self._current_spans:
            span.parent_id = self._current_spans[-1]
            parent = self._span_map.get(span.parent_id)
            if parent:
                parent.children.append(span)
        elif self.root_span is None:
            self.root_span = span
        else:
            # Attach to root as sibling
            span.parent_id = self.root_span.id
            self.root_span.children.append(span)

        self._span_map[span.id] = span
        self._current_spans.append(span.id)
        self.total_spans += 1

        if event == TraceEvent.RETRY:
            self.total_retries += 1
        elif event == TraceEvent.ERROR:
            self.total_errors += 1
        elif event == TraceEvent.FALLBACK:
            self.total_fallbacks += 1

        return span

    def end_span(
        self, span_id: str, status: str = "done", data: dict | None = None
    ) -> TraceSpan | None:
        """End a span and record its duration."""
        span = self._span_map.get(span_id)
        if not span:
            return None

        span.end_ms = time.time() * 1000
        span.duration_ms = span.end_ms - span.start_ms
        span.status = status
        if data:
            span.data.update(data)

        # Pop from current stack
        if self._current_spans and self._current_spans[-1] == span_id:
            self._current_spans.pop()

        return span

    def add_event(
        self,
        event: TraceEvent,
        name: str = "",
        data: dict | None = None,
        tags: list[str] | None = None,
        duration_ms: float = 0.0,
    ) -> TraceSpan:
        """Quick-add a leaf event (start+end in one call)."""
        span = self.start_span(event, name, data, tags)
        span.end_ms = span.start_ms + duration_ms
        span.duration_ms = duration_ms
        span.status = "done"

        if self._current_spans and self._current_spans[-1] == span.id:
            self._current_spans.pop()

        return span

    def to_dict(self) -> dict:
        return {
            "trace_id": self.id,
            "task_name": self.task_name,
            "total_spans": self.total_spans,
            "total_retries": self.total_retries,
            "total_errors": self.total_errors,
            "total_fallbacks": self.total_fallbacks,
            "created_at": self.created_at,
            "root": self.root_span.to_dict() if self.root_span else {},
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_tree_string(self, span: TraceSpan | None = None, indent: int = 0) -> str:
        """Render trace as indented ASCII tree."""
        if span is None:
            span = self.root_span
        if span is None:
            return "(empty trace)"

        lines = []
        prefix = "  " * indent
        status_icon = {"done": "O", "failed": "X", "started": ">", "aborted": "!"}.get(
            span.status, "?"
        )
        lines.append(
            f"{prefix}{status_icon} [{span.event.value}] {span.name} "
            f"({span.duration_ms:.0f}ms) [{span.status}]"
        )
        for child in span.children:
            lines.append(self.to_tree_string(child, indent + 1))
        return "\n".join(lines)

    def summary(self) -> str:
        """One-line summary of trace."""
        total_ms = 0.0
        if self.root_span and self.root_span.duration_ms:
            total_ms = self.root_span.duration_ms
        return (
            f"Trace[{self.id}] '{self.task_name}' "
            f"{self.total_spans} spans, "
            f"{self.total_retries} retries, "
            f"{self.total_errors} errors, "
            f"{total_ms:.0f}ms total"
        )

    def bottlenecks(self, top_n: int = 5) -> list[dict]:
        """Find slowest spans — helps identify bottlenecks."""
        all_spans: list[TraceSpan] = []

        def collect(s: TraceSpan):
            all_spans.append(s)
            for c in s.children:
                collect(c)

        if self.root_span:
            collect(self.root_span)

        sorted_spans = sorted(all_spans, key=lambda s: s.duration_ms, reverse=True)
        result = []
        for s in sorted_spans[:top_n]:
            result.append(
                {
                    "name": s.name,
                    "event": s.event.value,
                    "duration_ms": round(s.duration_ms, 1),
                    "status": s.status,
                    "tags": s.tags,
                }
            )
        return result

    def errors_list(self) -> list[dict]:
        """List all error spans."""
        errors: list[dict] = []

        def collect(s: TraceSpan):
            if s.event == TraceEvent.ERROR or s.status == "failed":
                errors.append(
                    {
                        "name": s.name,
                        "data": {k: str(v)[:100] for k, v in s.data.items()},
                        "tags": s.tags,
                    }
                )
            for c in s.children:
                collect(c)

        if self.root_span:
            collect(self.root_span)

        return errors

    def timeline(self) -> list[dict]:
        """Generate a flat timeline of all spans sorted by start time."""
        all_spans: list[TraceSpan] = []

        def collect(s: TraceSpan):
            all_spans.append(s)
            for c in s.children:
                collect(c)

        if self.root_span:
            collect(self.root_span)

        all_spans.sort(key=lambda s: s.start_ms)

        timeline = []
        for s in all_spans:
            timeline.append(
                {
                    "time_ms": f"{s.start_ms:.1f}",
                    "event": s.event.value,
                    "name": s.name,
                    "duration_ms": f"{s.duration_ms:.1f}",
                    "status": s.status,
                }
            )
        return timeline


class TraceCollector:
    """
    Collects multiple execution traces and generates aggregate reports.

    Usage:
        collector = TraceCollector()
        trace1 = await run_task("query_a")
        collector.add(trace1)
        trace2 = await run_task("query_b")
        collector.add(trace2)

        print(collector.stats())
    """

    def __init__(self, max_traces: int = 100):
        self._traces: dict[str, ExecutionTrace] = {}
        self.max_traces = max_traces

    def add(self, trace: ExecutionTrace) -> None:
        self._traces[trace.id] = trace
        if len(self._traces) > self.max_traces:
            oldest = next(iter(self._traces))
            del self._traces[oldest]

    def get(self, trace_id: str) -> ExecutionTrace | None:
        return self._traces.get(trace_id)

    def stats(self) -> dict:
        """Aggregate statistics across all traces."""
        if not self._traces:
            return {"count": 0}

        total_spans = sum(t.total_spans for t in self._traces.values())
        total_retries = sum(t.total_retries for t in self._traces.values())
        total_errors = sum(t.total_errors for t in self._traces.values())
        total_fallbacks = sum(t.total_fallbacks for t in self._traces.values())

        durations = []
        for t in self._traces.values():
            if t.root_span and t.root_span.duration_ms:
                durations.append(t.root_span.duration_ms)

        return {
            "count": len(self._traces),
            "total_spans": total_spans,
            "total_retries": total_retries,
            "total_errors": total_errors,
            "total_fallbacks": total_fallbacks,
            "retry_rate": round(total_retries / max(total_spans, 1), 3),
            "error_rate": round(total_errors / max(total_spans, 1), 3),
            "avg_duration_ms": round(sum(durations) / len(durations), 1) if durations else 0,
            "max_duration_ms": round(max(durations), 1) if durations else 0,
            "min_duration_ms": round(min(durations), 1) if durations else 0,
        }

    def failed_tasks(self) -> list[dict]:
        """List tasks that ended with errors."""
        failed = []
        for t in self._traces.values():
            if t.root_span and t.root_span.status in ("failed", "aborted"):
                failed.append(
                    {
                        "trace_id": t.id,
                        "task_name": t.task_name,
                        "status": t.root_span.status,
                        "errors": t.total_errors,
                    }
                )
        return failed
