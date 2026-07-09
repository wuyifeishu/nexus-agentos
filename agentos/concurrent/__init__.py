"""AgentOS Concurrent Primitives.

- ParallelExecutor: 异步并行执行器（fan-out/fan-in + 限流 + 超时）。
- FanOutExecutor: 扇出模式（race/merge/all + 结果聚合）。
- parallel_gather: 并行等待多个协程，支持超时和部分结果。
- parallel_map: 并行映射异步函数到列表。
"""

from agentos.concurrent.parallel import (
    FanOutConfig,
    FanOutExecutor,
    GatherResult,
    ParallelExecutor,
    TaskResult,
    TaskStatus,
    TaskThrottler,
    create_parallel_agent_gather,
    parallel_gather,
    parallel_map,
)

__all__ = [
    "ParallelExecutor",
    "FanOutExecutor",
    "FanOutConfig",
    "TaskThrottler",
    "TaskResult",
    "TaskStatus",
    "GatherResult",
    "parallel_gather",
    "parallel_map",
    "create_parallel_agent_gather",
]
