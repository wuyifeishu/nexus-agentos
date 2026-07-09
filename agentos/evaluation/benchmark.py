"""
AgentOS v0.20 评测框架。
支持 SWE-bench、Tool-use 等基准测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
            self.results.append(
                EvalResult(
                    case_id=case.id,
                    passed=passed,
                    score=score,
                    output=output[:2000],
                    expected=case.expected_output,
                    duration_ms=duration_ms,
                )
            )

        return self.results

    def _check(self, output: str, case: BenchmarkCase) -> bool:
        # Enhanced scoring: use CompositeScorer for fuzzy matching
        if not case.expected_output:
            return True

        from agentos.evaluation.scorers import (
            STRATEGY_CODE_GEN,
            STRATEGY_QA,
            STRATEGY_SUMMARY,
            STRATEGY_TRANSLATION,
            CompositeScorer,
            ScoringStrategy,
        )

        # Select strategy based on case category
        category = case.ground_truth.get("category", "qa")
        strategy_map = {
            "qa": STRATEGY_QA,
            "code": STRATEGY_CODE_GEN,
            "summary": STRATEGY_SUMMARY,
            "translation": STRATEGY_TRANSLATION,
        }
        strategy = strategy_map.get(
            category,
            ScoringStrategy(
                weights={"rouge_l": 0.3, "bleu": 0.1, "contains": 0.4, "exact": 0.2},
                pass_threshold=0.5,
            ),
        )

        scorer = CompositeScorer(strategy)
        result = scorer.score(case.expected_output, output)

        # Store detailed scores in metrics
        if hasattr(result, "scores"):
            for k, v in result.scores.items():
                case.metrics.append(k)

        return result.passed

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
    """Built-in benchmark suite across 4 categories."""
    return [
        # ── QA ──
        BenchmarkCase(
            id="qa_math_1",
            task="1+1等于几？只回答数字。",
            expected_output="2",
            ground_truth={"category": "qa"},
        ),
        BenchmarkCase(
            id="qa_fact_1",
            task="法国的首都是哪里？",
            expected_output="Paris",
            ground_truth={"category": "qa"},
        ),
        BenchmarkCase(
            id="qa_fact_2",
            task="水的沸点是多少度？",
            expected_output="100",
            ground_truth={"category": "qa"},
        ),
        BenchmarkCase(
            id="qa_fact_3",
            task="太阳系最大的行星是？",
            expected_output="木星",
            ground_truth={"category": "qa"},
        ),
        BenchmarkCase(
            id="qa_define_1",
            task="什么是人工智能？",
            expected_output="人工智能",
            ground_truth={"category": "qa"},
        ),
        # ── Code ──
        BenchmarkCase(
            id="code_fib",
            task="写一个Python函数计算斐波那契数列第n项。",
            expected_output="def fibonacci",
            ground_truth={"category": "code"},
        ),
        BenchmarkCase(
            id="code_sort",
            task="用Python写一个列表排序函数。",
            expected_output="def sort",
            ground_truth={"category": "code"},
        ),
        BenchmarkCase(
            id="code_read",
            task="如何用Python读取文件？",
            expected_output="open",
            ground_truth={"category": "code"},
        ),
        # ── Summary ──
        BenchmarkCase(
            id="sum_short",
            task="用一句话总结：地球是太阳系第三颗行星，拥有液态水和大气层。",
            expected_output="地球",
            ground_truth={"category": "summary"},
        ),
        BenchmarkCase(
            id="sum_tech",
            task="总结Python的主要特点。",
            expected_output="Python",
            ground_truth={"category": "summary"},
        ),
        # ── Translation ──
        BenchmarkCase(
            id="trans_en2zh",
            task="把Hello翻译成中文。",
            expected_output="你好",
            ground_truth={"category": "translation"},
        ),
        BenchmarkCase(
            id="trans_zh2en",
            task="把谢谢翻译成英文。",
            expected_output="thank you",
            ground_truth={"category": "translation"},
        ),
        # ── Tool-use ──
        BenchmarkCase(
            id="tool_shell",
            task="列出当前目录的文件。使用shell工具。",
            expected_tools=["shell"],
            ground_truth={"category": "qa"},
        ),
        BenchmarkCase(
            id="multi_step",
            task="先创建目录test_dir，再创建hello.txt并写入内容。",
            ground_truth={"category": "qa"},
        ),
    ]
