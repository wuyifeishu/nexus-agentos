"""v0.80 — 性能基准测试运行器：延迟/吞吐/并发。"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BenchmarkScenario:
    """单个基准测试场景。"""

    name: str
    description: str = ""
    setup: Callable[[], Any] | None = None
    teardown: Callable[[Any], None] | None = None


@dataclass
class BenchmarkConfig:
    """基准测试配置。"""

    warmup_iterations: int = 3
    measure_iterations: int = 10
    concurrency_levels: list[int] = field(default_factory=lambda: [1, 4, 8])
    timeout_per_run: float = 30.0


@dataclass
class _LatencyStats:
    min_ms: float = 0
    max_ms: float = 0
    avg_ms: float = 0
    p50_ms: float = 0
    p95_ms: float = 0
    p99_ms: float = 0

    @staticmethod
    def compute(latencies_ms: list[float]) -> _LatencyStats:
        if not latencies_ms:
            return _LatencyStats()
        s = sorted(latencies_ms)
        n = len(s)
        return _LatencyStats(
            min_ms=s[0],
            max_ms=s[-1],
            avg_ms=sum(s) / n,
            p50_ms=s[int(n * 0.5)],
            p95_ms=s[int(n * 0.95)] if int(n * 0.95) < n else s[-1],
            p99_ms=s[int(n * 0.99)] if int(n * 0.99) < n else s[-1],
        )


@dataclass
class BenchmarkReport:
    """基准测试报告。"""

    scenario: str = ""
    description: str = ""
    config: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    results: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "scenario": self.scenario,
                "description": self.description,
                "results": self.results,
                "summary": self.summary,
            },
            indent=2,
            ensure_ascii=False,
        )

    def to_markdown(self) -> str:
        lines = [
            f"# Benchmark: {self.scenario}",
            "",
            f"_{self.description}_",
            "",
            "| 并发 | 总调用 | 总耗时(s) | 吞吐(QPS) | 平均延迟(ms) | P50(ms) | P95(ms) | P99(ms) | 成功率 |",
            "|------|--------|-----------|-----------|-------------|---------|---------|---------|--------|",
        ]
        for r in self.results:
            lines.append(
                f"| {r['concurrency']} | {r['total_calls']} | {r['total_time_s']:.2f} | "
                f"{r['throughput_qps']:.1f} | {r['latency_stats']['avg_ms']:.1f} | "
                f"{r['latency_stats']['p50_ms']:.1f} | {r['latency_stats']['p95_ms']:.1f} | "
                f"{r['latency_stats']['p99_ms']:.1f} | {r['success_rate']*100:.0f}% |"
            )
        if self.summary:
            lines.extend(["", f"> {self.summary}"])
        return "\n".join(lines)


class BenchmarkRunner:
    """基准测试运行器。"""

    def __init__(self, config: BenchmarkConfig | None = None):
        self.config = config or BenchmarkConfig()

    async def run(
        self,
        scenario: BenchmarkScenario,
        callable_fn: Callable[[], Any],
        async_callable_fn: Callable[[], Awaitable[Any]] | None = None,
    ) -> BenchmarkReport:
        """运行基准测试。

        Args:
            scenario: 测试场景。
            callable_fn: 同步测试函数。
            async_callable_fn: 异步测试函数（用于并发测试）。
        """
        setup_state = scenario.setup() if scenario.setup else None

        results: list[dict[str, Any]] = []

        for concurrency in self.config.concurrency_levels:
            total_calls = concurrency * self.config.measure_iterations
            total_start = time.perf_counter()
            success = 0
            latencies_ms: list[float] = []

            async def _one_call():
                nonlocal success
                t0 = time.perf_counter()
                try:
                    if async_callable_fn:
                        await async_callable_fn()
                    else:
                        callable_fn()
                    success += 1
                except Exception:
                    pass
                latencies_ms.append((time.perf_counter() - t0) * 1000)

            # warmup
            for _ in range(self.config.warmup_iterations):
                try:
                    callable_fn()
                except Exception:
                    pass

            # measure
            tasks = [_one_call() for _ in range(total_calls)]
            await asyncio.gather(*tasks)

            total_time = time.perf_counter() - total_start
            stats = _LatencyStats.compute(latencies_ms)

            results.append(
                {
                    "concurrency": concurrency,
                    "total_calls": total_calls,
                    "total_time_s": round(total_time, 3),
                    "throughput_qps": round(total_calls / total_time, 1) if total_time > 0 else 0,
                    "latency_stats": {
                        "min_ms": round(stats.min_ms, 2),
                        "max_ms": round(stats.max_ms, 2),
                        "avg_ms": round(stats.avg_ms, 2),
                        "p50_ms": round(stats.p50_ms, 2),
                        "p95_ms": round(stats.p95_ms, 2),
                        "p99_ms": round(stats.p99_ms, 2),
                    },
                    "success_rate": round(success / total_calls, 4) if total_calls else 0,
                }
            )

        if scenario.teardown and setup_state is not None:
            scenario.teardown(setup_state)

        avg_throughput = sum(r["throughput_qps"] for r in results) / len(results) if results else 0
        return BenchmarkReport(
            scenario=scenario.name,
            description=scenario.description,
            config=self.config,
            results=results,
            summary=f"平均吞吐: {avg_throughput:.1f} QPS | 并发级别: {self.config.concurrency_levels}",
        )


async def run_benchmark(
    scenario_name: str,
    callable_fn: Callable[[], Any],
    config: BenchmarkConfig | None = None,
) -> BenchmarkReport:
    """便捷函数：运行一次基准测试并返回 Markdown 报告。"""
    runner = BenchmarkRunner(config)
    scenario = BenchmarkScenario(name=scenario_name)
    return await runner.run(scenario, callable_fn)
