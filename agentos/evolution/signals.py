"""
Behavior Signal Detection — User behavior signal collection and analysis.

Signals collected:
  - Tool usage frequency and patterns
  - Explicit feedback (thumbs up/down, ratings)
  - Implicit feedback (corrections, re-prompts, "no/stop/undo")
  - Conversation context (topic shifts, depth, sentiment)
  - Timing signals (response latency, session duration)
  - Preference signals (format preferences, language, tone)

These signals feed into the Learner to generate evolution proposals.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

# ── Signal Types ──


class SignalType(StrEnum):
    TOOL_USAGE = "tool_usage"  # Tool was invoked
    EXPLICIT_FEEDBACK = "explicit_feedback"  # User gave explicit rating
    CORRECTION = "correction"  # User corrected agent
    RE_PROMPT = "re_prompt"  # User re-asked the same thing
    UNDO = "undo"  # User undid an action
    SESSION_LENGTH = "session_length"  # Session duration
    TOPIC_SWITCH = "topic_switch"  # User changed topic abruptly
    FORMAT_PREFERENCE = "format_preference"  # Output format preference
    RESPONSE_LATENCY = "response_latency"  # How fast agent responded
    ERROR_RECOVERY = "error_recovery"  # Error occurred and agent recovered
    PATTERN_MATCH = "pattern_match"  # Recognized repeated pattern


class FeedbackPolarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


# ── Signal Data ──


@dataclass
class BehaviorSignal:
    """A single observed user behavior signal."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    type_: SignalType = SignalType.TOOL_USAGE
    timestamp: float = field(default_factory=time.time)
    user_id: str = "default"
    session_id: str = ""

    # Payload
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_success: bool = True
    tool_duration_ms: float = 0.0

    feedback_type: str = ""  # "thumbs_up", "thumbs_down", "rating:4"
    feedback_text: str = ""
    polarity: FeedbackPolarity = FeedbackPolarity.NEUTRAL

    context_before: str = ""  # What happened before this signal
    context_after: str = ""  # Result after this signal

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type_.value,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_success": self.tool_success,
            "tool_duration_ms": self.tool_duration_ms,
            "feedback_type": self.feedback_type,
            "feedback_text": self.feedback_text,
            "polarity": self.polarity.value,
            "context_before": self.context_before[:500],
            "context_after": self.context_after[:500],
            "metadata": self.metadata,
        }


@dataclass
class SignalSummary:
    """Aggregated signal analysis over a time window."""

    window_start: float = 0.0
    window_end: float = field(default_factory=time.time)
    total_signals: int = 0

    # Tool usage
    top_tools: list[tuple[str, int]] = field(default_factory=list)  # [(tool_name, count)]
    tool_success_rate: float = 0.0

    # Feedback
    positive_feedback: int = 0
    negative_feedback: int = 0
    correction_count: int = 0
    undo_count: int = 0
    re_prompt_count: int = 0

    # Patterns
    detected_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "total_signals": self.total_signals,
            "top_tools": self.top_tools,
            "tool_success_rate": self.tool_success_rate,
            "positive_feedback": self.positive_feedback,
            "negative_feedback": self.negative_feedback,
            "correction_count": self.correction_count,
            "undo_count": self.undo_count,
            "re_prompt_count": self.re_prompt_count,
            "detected_patterns": self.detected_patterns,
        }


# ── Signal Collector ──


class SignalCollector:
    """Collects and persists user behavior signals.

    Features:
      - In-memory ring buffer (last N signals)
      - Optional disk persistence
      - Signal hooks for real-time processing
      - Aggregation windows for analysis

    Usage:
        collector = SignalCollector(buffer_size=1000)

        # Record tool usage
        collector.record_tool_usage("web_search", {"query": "..."}, success=True)

        # Record explicit feedback
        collector.record_feedback("thumbs_up", "Great answer!")

        # Record correction
        collector.record_correction("No, use Python not JS")

        # Get summary
        summary = collector.summarize(hours=24)
    """

    def __init__(
        self,
        buffer_size: int = 2000,
        persist_path: str | None = None,
    ):
        self._buffer: list[BehaviorSignal] = []
        self._buffer_size = buffer_size
        self._persist_path = Path(persist_path) if persist_path else None
        self._hooks: list[Callable[[BehaviorSignal], None]] = []
        self._tool_counter: dict[str, int] = defaultdict(int)
        self._session_id: str = ""

        if self._persist_path:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id

    # ── Recording API ──

    def record_tool_usage(
        self,
        tool_name: str,
        tool_args: dict = None,
        success: bool = True,
        duration_ms: float = 0.0,
    ) -> BehaviorSignal:
        """Record a tool invocation."""
        signal = BehaviorSignal(
            type_=SignalType.TOOL_USAGE,
            tool_name=tool_name,
            tool_args=tool_args or {},
            tool_success=success,
            tool_duration_ms=duration_ms,
            session_id=self._session_id,
        )
        self._tool_counter[tool_name] += 1
        self._append(signal)
        return signal

    def record_feedback(
        self,
        feedback_type: str,
        feedback_text: str = "",
    ) -> BehaviorSignal:
        """Record explicit user feedback."""
        polarity = FeedbackPolarity.NEUTRAL
        if feedback_type in ("thumbs_up", "positive", "5", "4"):
            polarity = FeedbackPolarity.POSITIVE
        elif feedback_type in ("thumbs_down", "negative", "1", "2"):
            polarity = FeedbackPolarity.NEGATIVE

        signal = BehaviorSignal(
            type_=SignalType.EXPLICIT_FEEDBACK,
            feedback_type=feedback_type,
            feedback_text=feedback_text,
            polarity=polarity,
            session_id=self._session_id,
        )
        self._append(signal)
        return signal

    def record_correction(self, correction_text: str, context: str = "") -> BehaviorSignal:
        """Record a user correction."""
        signal = BehaviorSignal(
            type_=SignalType.CORRECTION,
            feedback_text=correction_text,
            context_before=context,
            polarity=FeedbackPolarity.NEGATIVE,
            session_id=self._session_id,
        )
        self._append(signal)
        return signal

    def record_undo(self, action: str = "") -> BehaviorSignal:
        """Record an undo action."""
        signal = BehaviorSignal(
            type_=SignalType.UNDO,
            tool_name=action,
            polarity=FeedbackPolarity.NEGATIVE,
            session_id=self._session_id,
        )
        self._append(signal)
        return signal

    def record_re_prompt(self, original_query: str = "") -> BehaviorSignal:
        """Record a re-prompt (user asked again differently)."""
        signal = BehaviorSignal(
            type_=SignalType.RE_PROMPT,
            context_before=original_query,
            polarity=FeedbackPolarity.NEGATIVE,
            session_id=self._session_id,
        )
        self._append(signal)
        return signal

    def record_format_preference(self, format_type: str) -> BehaviorSignal:
        """Record output format preference."""
        signal = BehaviorSignal(
            type_=SignalType.FORMAT_PREFERENCE,
            feedback_type=format_type,
            session_id=self._session_id,
        )
        self._append(signal)
        return signal

    def record_error_recovery(self, error: str, recovered: bool = True) -> BehaviorSignal:
        """Record an error that the agent recovered from."""
        signal = BehaviorSignal(
            type_=SignalType.ERROR_RECOVERY,
            context_before=error,
            tool_success=recovered,
            session_id=self._session_id,
        )
        self._append(signal)
        return signal

    # ── Analysis ──

    def summarize(self, hours: float = 24) -> SignalSummary:
        """Generate a summary of signals over the last N hours."""
        now = time.time()
        cutoff = now - hours * 3600

        signals = [s for s in self._buffer if s.timestamp >= cutoff]

        summary = SignalSummary(
            window_start=cutoff,
            window_end=now,
            total_signals=len(signals),
        )

        tool_counts: dict[str, int] = defaultdict(int)
        total_tools = 0
        successful_tools = 0

        for s in signals:
            if s.type_ == SignalType.TOOL_USAGE:
                tool_counts[s.tool_name] += 1
                total_tools += 1
                if s.tool_success:
                    successful_tools += 1

            elif s.type_ == SignalType.EXPLICIT_FEEDBACK:
                if s.polarity == FeedbackPolarity.POSITIVE:
                    summary.positive_feedback += 1
                elif s.polarity == FeedbackPolarity.NEGATIVE:
                    summary.negative_feedback += 1

            elif s.type_ == SignalType.CORRECTION:
                summary.correction_count += 1

            elif s.type_ == SignalType.UNDO:
                summary.undo_count += 1

            elif s.type_ == SignalType.RE_PROMPT:
                summary.re_prompt_count += 1

        summary.top_tools = sorted(tool_counts.items(), key=lambda x: -x[1])[:10]
        summary.tool_success_rate = successful_tools / max(total_tools, 1)

        # Detect patterns
        summary.detected_patterns = self._detect_patterns(signals)

        return summary

    def get_tool_ranking(self, top_n: int = 10) -> list[tuple[str, int]]:
        return sorted(self._tool_counter.items(), key=lambda x: -x[1])[:top_n]

    def get_feedback_ratio(self, hours: float = 168) -> float:
        """Positive feedback ratio over time window."""
        summary = self.summarize(hours)
        total = summary.positive_feedback + summary.negative_feedback
        if total == 0:
            return 0.5
        return summary.positive_feedback / total

    # ── Hooks ──

    def on_signal(self, hook: Callable[[BehaviorSignal], None]) -> None:
        """Register a hook called on every new signal."""
        self._hooks.append(hook)

    # ── Internal ──

    def _append(self, signal: BehaviorSignal) -> None:
        self._buffer.append(signal)
        if len(self._buffer) > self._buffer_size:
            self._buffer = self._buffer[-self._buffer_size :]

        for hook in self._hooks:
            try:
                hook(signal)
            except Exception:
                pass

        if self._persist_path:
            self._save_to_disk()

    def _detect_patterns(self, signals: list[BehaviorSignal]) -> list[str]:
        """Detect behavioral patterns from signals."""
        patterns = []

        # Pattern: frequent corrections on same topic
        corrections = [s for s in signals if s.type_ == SignalType.CORRECTION]
        if len(corrections) >= 3:
            patterns.append(f"frequent_corrections:{len(corrections)}")

        # Pattern: high undo rate
        undos = [s for s in signals if s.type_ == SignalType.UNDO]
        if len(undos) >= 2:
            patterns.append(f"high_undo_rate:{len(undos)}")

        # Pattern: repeated tool failures
        failed_tools = [
            s for s in signals if s.type_ == SignalType.TOOL_USAGE and not s.tool_success
        ]
        if len(failed_tools) >= 3:
            tools = set(s.tool_name for s in failed_tools)
            patterns.append(f"failing_tools:{','.join(tools)}")

        # Pattern: positive feedback streak
        positive = [s for s in signals if s.polarity == FeedbackPolarity.POSITIVE]
        if len(positive) >= 5:
            patterns.append(f"positive_streak:{len(positive)}")

        return patterns

    def _save_to_disk(self) -> None:
        if not self._persist_path:
            return
        try:
            data = [s.to_dict() for s in self._buffer[-500:]]
            self._persist_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def _load_from_disk(self) -> None:
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text())
            for item in data[-500:]:
                signal = BehaviorSignal(
                    id=item.get("id", ""),
                    type_=SignalType(item.get("type", "tool_usage")),
                    timestamp=item.get("timestamp", 0),
                    user_id=item.get("user_id", "default"),
                    session_id=item.get("session_id", ""),
                    tool_name=item.get("tool_name", ""),
                    tool_success=item.get("tool_success", True),
                    feedback_type=item.get("feedback_type", ""),
                    feedback_text=item.get("feedback_text", ""),
                    polarity=FeedbackPolarity(item.get("polarity", "neutral")),
                    context_before=item.get("context_before", ""),
                    context_after=item.get("context_after", ""),
                    metadata=item.get("metadata", {}),
                )
                self._buffer.append(signal)
                self._tool_counter[signal.tool_name] += 1
        except Exception:
            pass
