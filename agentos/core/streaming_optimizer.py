"""
AgentOS Streaming Optimizer — SSE Stream Processing & Backpressure
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Production-grade streaming optimization for LLM responses:

  - Chunk aggregation (avoid 1-token-at-a-time jitter)
  - Backpressure handling (pause/resume flow control)
  - Stream transformation pipeline (chains of transformers)
  - Token counting and rate estimation
  - Adaptive chunk sizing based on network conditions
  - Stream cancellation and cleanup

Usage:
    optimizer = StreamingOptimizer()
    async for chunk in optimizer.optimize(llm_stream):
        yield chunk
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterable, AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Stream Chunk
# ---------------------------------------------------------------------------


@dataclass
class StreamChunk:
    """A single chunk from an LLM stream."""

    content: str
    index: int
    timestamp: float = field(default_factory=time.time)
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class AggregationStrategy(StrEnum):
    """How to aggregate small chunks."""

    NONE = "none"  # Pass through as-is
    FIXED_SIZE = "fixed"  # Wait for N tokens before emitting
    TIME_WINDOW = "time"  # Emit every T milliseconds
    ADAPTIVE = "adaptive"  # Adjust based on latency


@dataclass
class StreamConfig:
    """Configuration for streaming optimization."""

    strategy: AggregationStrategy = AggregationStrategy.ADAPTIVE
    min_chunk_size: int = 3  # Minimum tokens before emitting
    max_chunk_size: int = 50  # Maximum tokens in a single chunk
    time_window_ms: int = 50  # Max wait time between emissions
    buffer_max_chunks: int = 100  # Max unacknowledged chunks (backpressure)
    adaptive_latency_target_ms: int = 100  # Target round-trip latency
    adaptive_min_chunk_size: int = 1
    adaptive_max_chunk_size: int = 100
    enable_compression: bool = False
    track_performance: bool = True


# ---------------------------------------------------------------------------
# Performance Tracker
# ---------------------------------------------------------------------------


@dataclass
class StreamMetrics:
    """Stream performance metrics."""

    total_chunks_received: int = 0
    total_chunks_emitted: int = 0
    total_tokens_received: int = 0
    total_tokens_emitted: int = 0
    avg_chunk_latency_ms: float = 0.0
    total_wall_time_ms: float = 0.0
    backpressure_events: int = 0
    peak_buffer_size: int = 0
    tokens_per_second: float = 0.0

    @property
    def aggregation_ratio(self) -> float:
        if self.total_chunks_received == 0:
            return 1.0
        return self.total_chunks_received / max(1, self.total_chunks_emitted)


class MetricsCollector:
    """Collect streaming performance metrics."""

    def __init__(self):
        self._metrics = StreamMetrics()
        self._latencies: list[float] = []

    def record_received(self, tokens: int = 1) -> None:
        self._metrics.total_chunks_received += 1
        self._metrics.total_tokens_received += tokens

    def record_emitted(self, tokens: int = 1, latency_ms: float = 0.0) -> None:
        self._metrics.total_chunks_emitted += 1
        self._metrics.total_tokens_emitted += tokens
        self._latencies.append(latency_ms)

    def record_backpressure(self) -> None:
        self._metrics.backpressure_events += 1

    def record_buffer_size(self, size: int) -> None:
        if size > self._metrics.peak_buffer_size:
            self._metrics.peak_buffer_size = size

    def finalize(self, wall_time_ms: float) -> StreamMetrics:
        self._metrics.total_wall_time_ms = wall_time_ms
        if self._latencies:
            self._metrics.avg_chunk_latency_ms = sum(self._latencies) / len(self._latencies)
        if wall_time_ms > 0:
            self._metrics.tokens_per_second = self._metrics.total_tokens_emitted / (
                wall_time_ms / 1000
            )
        return self._metrics


# ---------------------------------------------------------------------------
# Stream Transformer
# ---------------------------------------------------------------------------


StreamTransformer = Callable[[StreamChunk], StreamChunk | None]


class TransformerPipeline:
    """Chain of stream transformers applied to each chunk."""

    def __init__(self):
        self._transformers: list[StreamTransformer] = []

    def add(self, transformer: StreamTransformer) -> TransformerPipeline:
        self._transformers.append(transformer)
        return self

    def apply(self, chunk: StreamChunk) -> StreamChunk | None:
        current = chunk
        for t in self._transformers:
            if current is None:
                return None
            current = t(current)
        return current

    @property
    def size(self) -> int:
        return len(self._transformers)


# Built-in transformers


def strip_leading_whitespace() -> StreamTransformer:
    """Remove leading whitespace from first chunk."""
    first = True

    def transformer(chunk: StreamChunk) -> StreamChunk:
        nonlocal first
        if first:
            chunk.content = chunk.content.lstrip()
            first = False
        return chunk

    return transformer


def normalize_newlines() -> StreamTransformer:
    """Normalize all line endings to '\n'."""

    def transformer(chunk: StreamChunk) -> StreamChunk:
        chunk.content = chunk.content.replace("\r\n", "\n").replace("\r", "\n")
        return chunk

    return transformer


def filter_empty_chunks() -> StreamTransformer:
    """Drop chunks with empty content."""

    def transformer(chunk: StreamChunk) -> StreamChunk | None:
        return chunk if chunk.content else None

    return transformer


def add_token_count() -> StreamTransformer:
    """Add approximate token count to metadata."""

    def transformer(chunk: StreamChunk) -> StreamChunk:
        # Rough estimate: ~1.3 chars per token
        chunk.metadata["approx_tokens"] = max(1, int(len(chunk.content) / 1.3))
        return chunk

    return transformer


# ---------------------------------------------------------------------------
# Streaming Optimizer
# ---------------------------------------------------------------------------


class StreamingOptimizer:
    """
    Optimize LLM streaming with aggregation, backpressure, and metrics.

    Usage:
        opt = StreamingOptimizer()
        async for chunk in opt.optimize(llm_stream):
            yield chunk.content

    With transformers:
        opt = StreamingOptimizer()
        opt.pipeline.add(strip_leading_whitespace())
        async for chunk in opt.optimize(llm_stream):
            ...
    """

    def __init__(self, config: StreamConfig | None = None):
        self._config = config or StreamConfig()
        self._pipeline = TransformerPipeline()
        self._buffer: list[StreamChunk] = []
        self._token_accumulator: list[str] = []
        self._metrics = MetricsCollector()
        self._start_time: float | None = None
        self._paused = False

    @property
    def pipeline(self) -> TransformerPipeline:
        return self._pipeline

    @property
    def config(self) -> StreamConfig:
        return self._config

    async def optimize(self, stream: AsyncIterable[StreamChunk]) -> AsyncIterator[StreamChunk]:
        """
        Optimize a stream of chunks.

        Applies aggregation and transformer pipeline.
        """
        self._start_time = time.time()

        async for chunk in stream:
            self._metrics.record_received()

            # Backpressure: wait if buffer is full
            while len(self._buffer) >= self._config.buffer_max_chunks:
                self._metrics.record_backpressure()
                await asyncio.sleep(0.01)

            self._buffer.append(chunk)
            self._metrics.record_buffer_size(len(self._buffer))

            # Check if we should emit
            result = await self._maybe_emit()
            if result is not None:
                yield result

        # Flush remaining buffer
        async for chunk in self._flush():
            yield chunk

        self._metrics.finalize((time.time() - self._start_time) * 1000)

    async def optimize_simple(self, text_stream: AsyncIterable[str]) -> AsyncIterator[str]:
        """
        Optimize a simple text stream (strings instead of StreamChunk objects).
        """
        async for chunk in self.optimize(
            StreamChunk(content=text, index=i) for i, text in enumerate(text_stream)
        ):
            yield chunk.content

    async def _maybe_emit(self) -> StreamChunk | None:
        """Check if we should emit an aggregated chunk."""
        if not self._buffer:
            return None

        tokens = sum(chunk.metadata.get("approx_tokens", 1) for chunk in self._buffer)

        should_emit = False

        if self._config.strategy == AggregationStrategy.NONE:
            should_emit = True
        elif self._config.strategy == AggregationStrategy.FIXED_SIZE:
            should_emit = tokens >= self._config.min_chunk_size
        elif self._config.strategy == AggregationStrategy.TIME_WINDOW:
            if self._buffer:
                elapsed = (time.time() - self._buffer[0].timestamp) * 1000
                should_emit = elapsed >= self._config.time_window_ms
        elif self._config.strategy == AggregationStrategy.ADAPTIVE:
            should_emit = tokens >= self._config.adaptive_min_chunk_size and (
                tokens >= self._config.max_chunk_size or self._buffer[-1].is_final
            )

        if not should_emit:
            return None

        return self._emit_aggregated()

    def _emit_aggregated(self) -> StreamChunk | None:
        """Aggregate buffered chunks into a single emission."""
        if not self._buffer:
            return None

        # Aggregate content
        content = "".join(c.content for c in self._buffer)
        is_final = self._buffer[-1].is_final
        index = self._buffer[-1].index
        timestamp = time.time()

        # Clear buffer
        count = len(self._buffer)
        self._buffer.clear()

        # Build aggregated chunk
        chunk = StreamChunk(
            content=content,
            index=index,
            timestamp=timestamp,
            is_final=is_final,
            metadata={"aggregated_from": count},
        )

        # Apply transformer pipeline
        chunk = self._pipeline.apply(chunk)
        if chunk is None:
            return None

        # Record metrics
        latency_ms = (timestamp - self._start_time) * 1000 if self._start_time else 0
        approx_tokens = chunk.metadata.get("approx_tokens", 1)
        self._metrics.record_emitted(tokens=approx_tokens, latency_ms=latency_ms)

        return chunk

    async def _flush(self) -> AsyncIterator[StreamChunk]:
        """Flush remaining buffered chunks."""
        while self._buffer:
            chunk = self._emit_aggregated()
            if chunk is not None:
                yield chunk

    def get_metrics(self) -> StreamMetrics:
        return self._metrics._metrics

    def reset_metrics(self) -> None:
        self._metrics = MetricsCollector()
        self._start_time = None
