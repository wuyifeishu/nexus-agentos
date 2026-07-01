"""
AgentOS v0.40 Experiments — A/B测试与Prompt实验框架。
支持：Prompt变体对比、A/B/n测试、结果统计显著性分析、实验报告生成。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class PromptVariant:
    """Prompt变体。"""
    name: str
    system_prompt: str
    user_template: str = ""
    model: str = "auto"
    temperature: float = 0.7
    max_tokens: int = 2048
    metadata: dict = field(default_factory=dict)


@dataclass
class TrialResult:
    """单次试验结果。"""
    variant_name: str
    input: str
    output: str
    latency_ms: float = 0
    tokens_used: int = 0
    cost: float = 0.0
    error: str = ""
    score: float = 0.0  # evaluator评分
    judged_by: str = ""


@dataclass
class ExperimentConfig:
    """实验配置。"""
    name: str
    variants: list[PromptVariant]
    test_inputs: list[str]
    evaluator: str = "auto"  # auto | llm_judge | human | custom
    trials_per_variant: int = 3
    shuffle: bool = True
    metric: str = "accuracy"  # accuracy | relevance | creativity | custom


@dataclass
class ExperimentReport:
    """实验报告。"""
    id: str
    config: ExperimentConfig
    results: list[TrialResult]
    winner: str = ""
    significance: float = 0.0
    summary: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class Evaluator:
    """评估器 — 自动评分模型输出。"""

    @staticmethod
    def llm_judge(output: str, expected: str, criteria: str = "accuracy") -> float:
        """使用LLM评判输出质量（占位符，实际调用模型）。"""
        # 生产环境会调用router进行评判
        # 当前返回启发式分
        if not expected:
            return 0.5

        output_lower = output.lower()
        expected_lower = expected.lower()

        # 简单重叠度
        out_words = set(output_lower.split())
        exp_words = set(expected_lower.split())
        if not exp_words:
            return 0.5
        overlap = len(out_words & exp_words) / len(exp_words)

        # 长度惩罚
        length_ratio = min(len(output_lower), len(expected_lower)) / max(len(output_lower), len(expected_lower), 1)

        return overlap * 0.7 + length_ratio * 0.3

    @staticmethod
    def exact_match(output: str, expected: str) -> float:
        return 1.0 if output.strip() == expected.strip() else 0.0

    @staticmethod
    def contains_all(output: str, keywords: list[str]) -> float:
        output_lower = output.lower()
        matches = sum(1 for kw in keywords if kw.lower() in output_lower)
        return matches / len(keywords) if keywords else 0.5


class ExperimentRunner:
    """实验执行器。"""

    def __init__(self, router=None, cache=None):
        self.router = router
        self.cache = cache or None
        self._reports: dict[str, ExperimentReport] = {}

    async def run(self, config: ExperimentConfig) -> ExperimentReport:
        """执行A/B实验。"""
        import random
        all_results: list[TrialResult] = []

        # 构建所有 (variant, input) 组合
        trials = []
        for variant in config.variants:
            for inp in config.test_inputs:
                for _ in range(config.trials_per_variant):
                    trials.append((variant, inp))

        if config.shuffle:
            random.shuffle(trials)

        for variant, inp in trials:
            start = time.time()
            try:
                if self.router:
                    messages = [
                        {"role": "system", "content": variant.system_prompt},
                        {"role": "user", "content": variant.user_template.format(input=inp) if variant.user_template else inp},
                    ]
                    output = await self.router.call_chat(messages)
                else:
                    output = f"[模拟输出] 变体 '{variant.name}' 对输入 '{inp[:30]}...' 的响应"

                latency = (time.time() - start) * 1000
                score = Evaluator.llm_judge(output, inp)  # 可自定义evaluator

                all_results.append(TrialResult(
                    variant_name=variant.name,
                    input=inp,
                    output=output,
                    latency_ms=latency,
                    score=score,
                    judged_by="auto",
                ))
            except Exception as e:
                all_results.append(TrialResult(
                    variant_name=variant.name, input=inp, output="",
                    error=str(e), score=0.0,
                ))

        # 汇总分析
        summary = self._analyze(all_results, config)
        winner = self._determine_winner(summary)

        report = ExperimentReport(
            id=f"exp_{uuid.uuid4().hex[:8]}",
            config=config,
            results=all_results,
            winner=winner,
            summary=summary,
        )
        self._reports[report.id] = report
        return report

    def _analyze(self, results: list[TrialResult], config: ExperimentConfig) -> dict:
        """统计分析。"""
        variant_stats = {}
        for r in results:
            if r.variant_name not in variant_stats:
                variant_stats[r.variant_name] = {"scores": [], "latencies": [], "errors": 0, "trials": 0}
            vs = variant_stats[r.variant_name]
            if r.error:
                vs["errors"] += 1
            else:
                vs["scores"].append(r.score)
                vs["latencies"].append(r.latency_ms)
            vs["trials"] += 1

        summary = {}
        for name, vs in variant_stats.items():
            scores = vs["scores"]
            latencies = vs["latencies"]
            summary[name] = {
                "avg_score": sum(scores) / len(scores) if scores else 0,
                "max_score": max(scores) if scores else 0,
                "min_score": min(scores) if scores else 0,
                "std_score": self._std(scores) if scores else 0,
                "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
                "error_rate": vs["errors"] / vs["trials"] if vs["trials"] else 0,
                "trials": vs["trials"],
            }
        return summary

    @staticmethod
    def _determine_winner(summary: dict) -> str:
        best_name = ""
        best_score = -1.0
        for name, stats in summary.items():
            penalty = stats["error_rate"] * 0.5
            adjusted = stats["avg_score"] * (1 - penalty)
            if adjusted > best_score:
                best_score = adjusted
                best_name = name
        return best_name

    @staticmethod
    def _std(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5

    def get_report(self, report_id: str) -> Optional[ExperimentReport]:
        return self._reports.get(report_id)

    def list_reports(self) -> list[dict]:
        return [{"id": rid, "name": r.config.name, "winner": r.winner, "variants": len(r.config.variants)}
                for rid, r in self._reports.items()]

    def generate_markdown_report(self, report: ExperimentReport) -> str:
        """生成Markdown格式实验报告。"""
        lines = [
            f"# 实验报告: {report.config.name}",
            f"**实验ID**: {report.id}",
            f"**变体数**: {len(report.config.variants)}",
            f"**测试输入数**: {len(report.config.test_inputs)}",
            f"**每变体试验次数**: {report.config.trials_per_variant}",
            f"**胜出变体**: **{report.winner}**",
            "",
            "## 统计摘要",
            "",
            "| 变体 | 平均分 | 最高分 | 最低分 | 标准差 | 平均延迟(ms) | 错误率 | 试验数 |",
            "|------|--------|--------|--------|--------|-------------|--------|--------|",
        ]
        for name, stats in report.summary.items():
            marker = " **← 胜出**" if name == report.winner else ""
            lines.append(
                f"| {name}{marker} | {stats['avg_score']:.3f} | {stats['max_score']:.3f} | "
                f"{stats['min_score']:.3f} | {stats['std_score']:.3f} | {stats['avg_latency_ms']:.0f} | "
                f"{stats['error_rate']:.1%} | {stats['trials']} |"
            )

        lines += ["", "## 变体配置", ""]
        for v in report.config.variants:
            lines += [
                f"### {v.name}",
                f"- 模型: {v.model}",
                f"- 温度: {v.temperature}",
                f"- Max Tokens: {v.max_tokens}",
                f"```\n{v.system_prompt[:200]}...\n```",
                "",
            ]

        return "\n".join(lines)
