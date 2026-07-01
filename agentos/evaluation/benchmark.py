"""
AgentOS v0.20 评测框架。
支持 SWE-bench、Tool-use 等基准测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class BenchmarkCase:
    """A single benchmark evaluation case."""
    id: str
    task: str
    expected_output: str | None = None
    expected_tools: list[str] | None = None
    ground_truth: dict[str, Any] = field(default_factory=dict)
    metrics: list[str] = field(default_factory=lambda: ["accuracy"])


@dataclass
class EvalResult:
    """Result of a benchmark evaluation run."""
    case_id: str
    passed: bool
    score: float
    output: str
    expected: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    duration_ms: float = 0.0


class Evaluator:
    """评测运行器。"""

    def __init__(self, agent_loop: Any):
        self.agent = agent_loop
        self.results: list[EvalResult] = []

    async def evaluate(self, benchmark: list[BenchmarkCase]) -> list[EvalResult]:
        """运行全部评测用例。"""
        import time

        self.results = []
        for case in benchmark:
            start = time.time()
            try:
                result = await self.agent.run(case.task)
                output = result.output
                passed = self._check(output, case)
                score = 1.0 if passed else 0.0
            except Exception as e:
                output = str(e)
                passed = False
                score = 0.0

            duration_ms = (time.time() - start) * 1000
            self.results.append(EvalResult(
                case_id=case.id,
                passed=passed,
                score=score,
                output=output[:2000],
                expected=case.expected_output,
                duration_ms=duration_ms,
            ))

        return self.results

    def _check(self, output: str, case: BenchmarkCase) -> bool:
        if case.ground_truth.get("exact_match"):
            return output.strip() == case.expected_output.strip()
        if case.expected_output:
            # 模糊匹配：输出包含预期内容
            return case.expected_output.lower() in output.lower()
        return True

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    @property
    def avg_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)

    def summary(self) -> str:
        return (
            f"总用例: {len(self.results)}\n"
            f"通过: {sum(1 for r in self.results if r.passed)}\n"
            f"通过率: {self.pass_rate:.1%}\n"
            f"平均分: {self.avg_score:.2f}"
        )


# ── 内置基准 ────────────────────────────────────

def builtin_benchmarks() -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            id="basic_qa",
            task="1+1等于几？只回答数字。",
            expected_output="2",
            ground_truth={"exact_match": True},
        ),
        BenchmarkCase(
            id="tool_use_shell",
            task="列出当前目录的文件。使用shell工具。",
            expected_tools=["shell"],
        ),
        BenchmarkCase(
            id="code_gen",
            task="写一个Python函数计算斐波那契数列第n项，返回代码。",
            expected_output="fibonacci",
        ),
        BenchmarkCase(
            id="multi_step",
            task="先创建目录test_dir，再在里面创建一个hello.txt文件，写入'Hello AgentOS'",
        ),
    ]
