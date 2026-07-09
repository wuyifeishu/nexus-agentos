"""
Tests for AgentOS Streaming Optimizer (agentos/core/streaming_optimizer.py)
"""

import asyncio
import time

import pytest

from agentos.core.streaming_optimizer import (
    AggregationStrategy,
    MetricsCollector,
    StreamChunk,
    StreamConfig,
    StreamingOptimizer,
    TransformerPipeline,
    add_token_count,
    filter_empty_chunks,
    normalize_newlines,
    strip_leading_whitespace,
)


class TestStreamChunk:
    """StreamChunk data class tests."""

    def test_creation(self):
        chunk = StreamChunk(content="hello", index=0)
        assert chunk.content == "hello"
        assert chunk.index == 0
        assert not chunk.is_final

    def test_with_metadata(self):
        chunk = StreamChunk(content="x", index=1, metadata={"tokens": 5})
        assert chunk.metadata["tokens"] == 5

    def test_is_final(self):
        chunk = StreamChunk(content="", index=99, is_final=True)
        assert chunk.is_final

    def test_timestamp(self):
        before = time.time()
        chunk = StreamChunk(content="t", index=0)
        assert chunk.timestamp >= before


class TestStreamConfig:
    """StreamConfig tests."""

    def test_defaults(self):
        config = StreamConfig()
        assert config.strategy == AggregationStrategy.ADAPTIVE
        assert config.min_chunk_size == 3
        assert config.max_chunk_size == 50
        assert config.time_window_ms == 50

    def test_fixed_size_strategy(self):
        config = StreamConfig(strategy=AggregationStrategy.FIXED_SIZE, min_chunk_size=10)
        assert config.strategy == AggregationStrategy.FIXED_SIZE


class TestTransformerPipeline:
    """Transformer pipeline tests."""

    def test_strip_leading_whitespace(self):
        pipeline = TransformerPipeline()
        pipeline.add(strip_leading_whitespace())
        chunk = StreamChunk(content="  hello", index=0)
        result = pipeline.apply(chunk)
        assert result.content == "hello"

    def test_strip_only_first(self):
        pipeline = TransformerPipeline()
        pipeline.add(strip_leading_whitespace())
        c1 = StreamChunk(content="  first", index=0)
        c2 = StreamChunk(content="  second", index=1)
        assert pipeline.apply(c1).content == "first"
        assert pipeline.apply(c2).content == "  second"

    def test_normalize_newlines(self):
        pipeline = TransformerPipeline()
        pipeline.add(normalize_newlines())
        chunk = StreamChunk(content="line1\r\nline2\r\n", index=0)
        result = pipeline.apply(chunk)
        assert "\r\n" not in result.content
        assert "\n" in result.content

    def test_filter_empty_chunks(self):
        pipeline = TransformerPipeline()
        pipeline.add(filter_empty_chunks())
        assert pipeline.apply(StreamChunk(content="", index=0)) is None
        assert pipeline.apply(StreamChunk(content="x", index=1)) is not None

    def test_add_token_count(self):
        pipeline = TransformerPipeline()
        pipeline.add(add_token_count())
        chunk = pipeline.apply(StreamChunk(content="Hello world", index=0))
        assert "approx_tokens" in chunk.metadata
        assert chunk.metadata["approx_tokens"] >= 1

    def test_chain(self):
        pipeline = TransformerPipeline()
        pipeline.add(strip_leading_whitespace())
        pipeline.add(normalize_newlines())
        pipeline.add(add_token_count())
        chunk = StreamChunk(content="  hello\r\n", index=0)
        result = pipeline.apply(chunk)
        assert result.content == "hello\n"
        assert "approx_tokens" in result.metadata

    def test_pipeline_size(self):
        pipeline = TransformerPipeline()
        assert pipeline.size == 0
        pipeline.add(strip_leading_whitespace())
        assert pipeline.size == 1


class TestMetricsCollector:
    """Metrics collector tests."""

    def test_record_received(self):
        mc = MetricsCollector()
        mc.record_received()
        assert mc._metrics.total_chunks_received == 1

    def test_record_emitted(self):
        mc = MetricsCollector()
        mc.record_emitted(tokens=3, latency_ms=50.0)
        assert mc._metrics.total_chunks_emitted == 1
        assert mc._metrics.total_tokens_emitted == 3

    def test_record_backpressure(self):
        mc = MetricsCollector()
        mc.record_backpressure()
        assert mc._metrics.backpressure_events == 1

    def test_record_buffer_size_peak(self):
        mc = MetricsCollector()
        mc.record_buffer_size(10)
        mc.record_buffer_size(5)
        mc.record_buffer_size(15)
        assert mc._metrics.peak_buffer_size == 15

    def test_finalize(self):
        mc = MetricsCollector()
        mc.record_received()
        mc.record_emitted(tokens=5, latency_ms=10)
        mc.record_emitted(tokens=5, latency_ms=20)
        metrics = mc.finalize(wall_time_ms=1000)
        assert metrics.total_chunks_received == 1
        assert metrics.total_tokens_emitted == 10
        assert metrics.avg_chunk_latency_ms == 15.0
        assert metrics.tokens_per_second > 0

    def test_aggregation_ratio(self):
        mc = MetricsCollector()
        mc._metrics.total_chunks_received = 100
        mc._metrics.total_chunks_emitted = 10
        assert mc._metrics.aggregation_ratio == 10.0


@pytest.mark.asyncio
class TestStreamingOptimizer:
    """Streaming optimizer async tests."""

    async def _mock_stream(self, chunks):
        for c in chunks:
            yield c
            await asyncio.sleep(0)

    async def test_passthrough_none_strategy(self):
        config = StreamConfig(strategy=AggregationStrategy.NONE)
        opt = StreamingOptimizer(config=config)
        stream = self._mock_stream([
            StreamChunk(content="a", index=0, is_final=True),
        ])
        results = []
        async for chunk in opt.optimize(stream):
            results.append(chunk)
        assert len(results) == 1

    async def test_aggregation(self):
        config = StreamConfig(
            strategy=AggregationStrategy.FIXED_SIZE,
            min_chunk_size=2,
        )
        opt = StreamingOptimizer(config=config)
        stream = self._mock_stream([
            StreamChunk(content="a", index=0),
            StreamChunk(content="b", index=1),
            StreamChunk(content="c", index=2, is_final=True),
        ])
        results = []
        async for chunk in opt.optimize(stream):
            results.append(chunk)
        # Should aggregate "a"+"b" and "c" separately
        assert len(results) >= 1

    async def test_optimize_simple(self):
        config = StreamConfig(strategy=AggregationStrategy.NONE)
        opt = StreamingOptimizer(config=config)
        stream = self._mock_stream([
            StreamChunk(content="hello", index=0, is_final=True),
        ])
        results = []
        async for chunk in opt.optimize(stream):
            results.append(chunk)
        assert results[0].content == "hello"

    async def test_metrics_collected(self):
        config = StreamConfig(strategy=AggregationStrategy.NONE)
        opt = StreamingOptimizer(config=config)
        stream = self._mock_stream([
            StreamChunk(content="a", index=0),
            StreamChunk(content="b", index=1, is_final=True),
        ])
        async for _ in opt.optimize(stream):
            pass
        metrics = opt.get_metrics()
        assert metrics.total_chunks_received >= 1
        assert metrics.total_wall_time_ms > 0

    async def test_metrics_reset(self):
        config = StreamConfig(strategy=AggregationStrategy.NONE)
        opt = StreamingOptimizer(config=config)
        stream = self._mock_stream([StreamChunk(content="a", index=0, is_final=True)])
        async for _ in opt.optimize(stream):
            pass
        opt.reset_metrics()
        metrics = opt.get_metrics()
        assert metrics.total_chunks_received == 0

    async def test_pipeline_integration(self):
        config = StreamConfig(strategy=AggregationStrategy.NONE)
        opt = StreamingOptimizer(config=config)
        opt.pipeline.add(strip_leading_whitespace())
        stream = self._mock_stream([StreamChunk(content="  hello", index=0, is_final=True)])
        results = []
        async for chunk in opt.optimize(stream):
            results.append(chunk)
        assert results[0].content == "hello"

    async def test_empty_stream(self):
        config = StreamConfig(strategy=AggregationStrategy.NONE)
        opt = StreamingOptimizer(config=config)
        stream = self._mock_stream([])
        results = []
        async for chunk in opt.optimize(stream):
            results.append(chunk)
        assert len(results) == 0

    async def test_config_accessible(self):
        opt = StreamingOptimizer()
        assert opt.config.strategy == AggregationStrategy.ADAPTIVE

    async def test_pipeline_accessible(self):
        opt = StreamingOptimizer()
        assert isinstance(opt.pipeline, TransformerPipeline)


# Sync fallback tests (non-async for basic coverage)
class TestStreamingOptimizerSync:
    """Synchronous-compatible tests for StreamingOptimizer."""

    def test_creation(self):
        opt = StreamingOptimizer()
        assert opt.config is not None
        assert opt.pipeline is not None

    def test_get_metrics_initial(self):
        opt = StreamingOptimizer()
        metrics = opt.get_metrics()
        assert metrics.total_chunks_received == 0
