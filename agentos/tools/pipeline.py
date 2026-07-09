"""
Pipeline — composable data processing pipeline for AgentOS.

Features:
- Linear and branching pipelines
- Fan-out / fan-in patterns
- Backpressure and quota control
- Stage-level error handling and retry
- Pipeline serialization for checkpoint/resume
"""

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Generic, TypeVar

T = TypeVar("T")
U = TypeVar("U")


# ============================================================================
# Core Types
# ============================================================================


class StageStatus(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPED = auto()
    ERROR = auto()


@dataclass
class PipelineContext:
    """Shared context flowing through the pipeline."""

    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


# ============================================================================
# Stage
# ============================================================================

_NO_FALLBACK = object()


class Stage(Generic[T, U], ABC):
    """Abstract pipeline stage. Transforms T → U."""

    def __init__(self, name: str = "", max_retries: int = 0):
        self.name = name or self.__class__.__name__
        self.max_retries = max_retries
        self.status: StageStatus = StageStatus.IDLE
        self._error: Exception | None = None
        self._items_processed: int = 0
        self._items_errored: int = 0

    @abstractmethod
    def process(self, item: T, ctx: PipelineContext) -> U: ...

    def on_error(self, item: T, error: Exception, ctx: PipelineContext) -> Any:
        """Override to provide fallback on error. Return _NO_FALLBACK to propagate."""
        return _NO_FALLBACK

    def execute(self, item: T, ctx: PipelineContext) -> U:
        self.status = StageStatus.RUNNING
        for attempt in range(self.max_retries + 1):
            try:
                result = self.process(item, ctx)
                self._items_processed += 1
                self.status = StageStatus.IDLE
                return result
            except Exception as e:
                self._items_errored += 1
                if attempt < self.max_retries:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                fallback = self.on_error(item, e, ctx)
                if fallback is not _NO_FALLBACK:
                    self.status = StageStatus.IDLE
                    return fallback
                self._error = e
                self.status = StageStatus.ERROR
                raise

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.name,
            "items_processed": self._items_processed,
            "items_errored": self._items_errored,
        }


class LambdaStage(Stage[T, U]):
    """Convenience stage from a callable."""

    def __init__(self, fn: Callable[[T, PipelineContext], U], name: str = "", max_retries: int = 0):
        super().__init__(name=name, max_retries=max_retries)
        self._fn = fn

    def process(self, item: T, ctx: PipelineContext) -> U:
        return self._fn(item, ctx)


# ============================================================================
# Pipeline
# ============================================================================


class Pipeline(Generic[T, U]):
    """Linear pipeline: a sequence of stages T → ? → ... → U."""

    def __init__(self, name: str = "pipeline"):
        self.name = name
        self._stages: list[Stage] = []
        self._lock = threading.Lock()
        self._ctx = PipelineContext()
        self.status: StageStatus = StageStatus.IDLE

    def add_stage(self, stage: Stage) -> "Pipeline":
        with self._lock:
            self._stages.append(stage)
        return self

    def then(
        self, fn: Callable[[Any, PipelineContext], Any], name: str = "", max_retries: int = 0
    ) -> "Pipeline":
        """Fluent API: add a lambda stage."""
        return self.add_stage(LambdaStage(fn, name=name, max_retries=max_retries))

    def run(self, input_item: T) -> U:
        """Run pipeline on a single item."""
        current = input_item
        self.status = StageStatus.RUNNING
        try:
            for stage in self._stages:
                current = stage.execute(current, self._ctx)
            return current
        finally:
            all_idle = all(s.status == StageStatus.IDLE for s in self._stages)
            self.status = StageStatus.IDLE if all_idle else StageStatus.ERROR

    def run_batch(self, items: list[T]) -> list[U]:
        """Run pipeline on a batch."""
        results = []
        for item in items:
            results.append(self.run(item))
        return results

    @property
    def context(self) -> PipelineContext:
        return self._ctx

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.name,
            "stages": [s.stats for s in self._stages],
        }


# ============================================================================
# ParallelPipeline — Fan-out / Fan-in
# ============================================================================


class ParallelPipeline(Generic[T, U]):
    """Branches: split input across parallel stages, then merge results.

    Fan-out: single input → all branches simultaneously.
    Fan-in: all branch outputs → merge function → single output.
    """

    def __init__(self, name: str = "parallel_pipeline"):
        self.name = name
        self._branches: list[Pipeline] = []
        self._merge: Callable[[list[Any], PipelineContext], U] | None = None
        self._lock = threading.Lock()
        self._ctx = PipelineContext()

    def branch(self, pipeline: Pipeline) -> "ParallelPipeline":
        with self._lock:
            self._branches.append(pipeline)
        return self

    def merge(self, fn: Callable[[list[Any], PipelineContext], U]) -> "ParallelPipeline":
        self._merge = fn
        return self

    def run(self, input_item: T) -> U:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self._branches)) as pool:
            futures = {
                pool.submit(branch.run, input_item): i for i, branch in enumerate(self._branches)
            }
            results = [None] * len(self._branches)
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                results[idx] = future.result()

        if self._merge:
            return self._merge(results, self._ctx)
        return results  # type: ignore

    @property
    def context(self) -> PipelineContext:
        return self._ctx


# ============================================================================
# Stage helpers
# ============================================================================


class FilterStage(Stage[T, T]):
    """Pass-through stage that filters items."""

    def __init__(
        self,
        predicate: Callable[[T, PipelineContext], bool],
        name: str = "filter",
        max_retries: int = 0,
    ):
        super().__init__(name=name, max_retries=max_retries)
        self._predicate = predicate

    def process(self, item: T, ctx: PipelineContext) -> T:
        if not self._predicate(item, ctx):
            raise FilterDrop()
        return item

    def on_error(self, item: T, error: Exception, ctx: PipelineContext) -> T | None:
        if isinstance(error, FilterDrop):
            return None
        return super().on_error(item, error, ctx)


class FilterDrop(Exception):  # noqa: N818
    """Signal that an item should be filtered out."""



class BatchStage(Stage[list[T], list[U]]):
    """Accumulates items into batches before processing."""

    def __init__(
        self,
        batch_size: int,
        fn: Callable[[list[T], PipelineContext], list[U]],
        name: str = "batch",
        max_retries: int = 0,
    ):
        super().__init__(name=name, max_retries=max_retries)
        self.batch_size = batch_size
        self._buffer: list[T] = []
        self._fn = fn

    def process(self, item: list[T], ctx: PipelineContext) -> list[U]:
        return self._fn(item, ctx)
