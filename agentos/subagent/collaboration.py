"""
Agent 协作模式 — Debate/Vote/Review/Pipeline/Ensemble。
基于 SubAgentManager + 父子通信之上，提供高级多Agent协作原语。

使用示例::

    mgr = SubAgentManager()
    collab = AgentCollaboration(mgr)

    result = await collab.debate("Python vs Rust for web backend", agents=2)
    result = await collab.vote(["方案A", "方案B", "方案C"], agents=5)
    result = await collab.review("写一篇关于AI安全的文章", rounds=2)
    result = await collab.pipeline("分析Q2财报数据", stages=3)
    result = await collab.ensemble("设计系统架构方案", agents=3)
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from .manager import SubAgentManager, SubAgentSpec, SubAgentResult
from .parent_child import ChildStatus, ChildContext, SharedState, ChildHandle


# ──────────────────────────────────────────────
# 枚举与数据类型
# ──────────────────────────────────────────────


class CollaborationMode(str, Enum):
    DEBATE = "debate"
    VOTE = "vote"
    REVIEW = "review"
    PIPELINE = "pipeline"
    ENSEMBLE = "ensemble"


class VoteStrategy(str, Enum):
    MAJORITY = "majority"
    WEIGHTED = "weighted"
    RANKED = "ranked"
    UNANIMOUS = "unanimous"


@dataclass
class DebateRound:
    """一轮辩论。"""
    round: int
    arguments: list[str]     # 各方论点
    rebuttals: list[str]     # 反驳
    winner: int | None = None


@dataclass
class VoteBallot:
    """一张选票。"""
    agent_id: str
    choice: str
    confidence: float = 1.0
    reasoning: str = ""


@dataclass
class ReviewPass:
    """一轮审查。"""
    round: int
    draft: str
    feedback: str
    revised: str
    score: float = 0.0


@dataclass
class CollaborationResult:
    """协作结果。"""
    mode: CollaborationMode
    agents: list[str]
    rounds: int
    final_output: str
    intermediate: list[Any] = field(default_factory=list)
    consensus: float = 0.0
    duration: float = 0.0


# ──────────────────────────────────────────────
# 角色性格库
# ──────────────────────────────────────────────

_PERSONAS = [
    "Be logical, data-driven, and cite evidence.",
    "Be creative, think outside the box, challenge assumptions.",
    "Focus on practical concerns: cost, timeline, feasibility.",
    "Advocate for user experience and human-centered design.",
    "Take a contrarian stance, find flaws in all arguments.",
]

# ──────────────────────────────────────────────
# 核心协作引擎
# ──────────────────────────────────────────────


class AgentCollaboration:
    """多Agent协作引擎。

    参数:
        manager: SubAgentManager 实例
        run_func: 执行函数 (task_str, ctx) -> (output, iterations)
        default_timeout: 每个子Agent默认超时（秒）
    """

    def __init__(
        self,
        manager: SubAgentManager | None = None,
        run_func: Callable[[SubAgentSpec, ChildContext], Awaitable[tuple[str, int]]] | None = None,
        default_timeout: float | None = 300.0,
    ):
        self._mgr = manager or SubAgentManager()
        self._run = run_func
        self._timeout = default_timeout

    # ── 便捷属性 ────────────────────────────

    @property
    def manager(self) -> SubAgentManager:
        return self._mgr

    @property
    def shared_state(self) -> SharedState:
        return self._mgr.shared_state

    async def cancel_all(self) -> None:
        await self._mgr.cancel_all()

    @property
    def active_agents(self) -> int:
        return self._mgr.active_children

    # ── 内部辅助 ────────────────────────────

    async def _spawn(self, task: str, timeout: float | None = None) -> SubAgentResult:
        """Fork 一个单Agent执行 task。"""
        return await self._mgr.spawn_fork(
            task=task,
            run_func=self._run,
            timeout=timeout or self._timeout,
        )

    async def _spawn_many(self, tasks: list[str], timeout: float | None = None) -> list[SubAgentResult]:
        """Swarm 并行执行多个 task。"""
        return await self._mgr.spawn_swarm(
            tasks=tasks,
            run_func=self._run,
            timeout=timeout or self._timeout,
        )

    @staticmethod
    def _parse_score(output: str) -> float:
        """从输出中解析 SCORE: N 格式的评分。"""
        m = re.search(r'SCORE:\s*([\d.]+)', output, re.IGNORECASE)
        if m:
            return max(0.0, min(10.0, float(m.group(1)))) / 10.0
        return 0.7

    @staticmethod
    def _parse_choice(
        output: str, option_count: int
    ) -> tuple[int | None, float, str]:
        """解析 CHOICE: N | CONFIDENCE: X | REASONING: text。"""
        choice = None
        confidence = 0.5
        reasoning = output[:200]

        m_choice = re.search(r'CHOICE:\s*(\d+)', output, re.IGNORECASE)
        if m_choice:
            num = int(m_choice.group(1))
            if 1 <= num <= option_count:
                choice = num

        m_conf = re.search(r'CONFIDENCE:\s*([\d.]+)', output, re.IGNORECASE)
        if m_conf:
            confidence = max(0.0, min(1.0, float(m_conf.group(1))))

        m_reason = re.search(r'REASONING:\s*(.+?)(?:\n|$)', output, re.IGNORECASE | re.DOTALL)
        if m_reason:
            reasoning = m_reason.group(1).strip()[:200]

        return choice, confidence, reasoning

    # ══════════════════════════════════════════
    # 1. Debate 辩论模式
    # ══════════════════════════════════════════

    async def debate(
        self,
        topic: str,
        agents: int = 2,
        rounds: int = 3,
        timeout: float | None = None,
    ) -> CollaborationResult:
        """多个Agent辩论 topic，裁判总结。

        流程:
            Round 0: 各方发表初始论点
            Round 1~N: 反驳对方 + 强化己方
            裁判: 综合所有论点给出最终裁决
        """
        t0 = time.time()
        history: list[DebateRound] = []
        all_agent_ids: list[str] = []

        # Round 0 — 初始论点
        r0_tasks = [
            f"Debate topic: {topic}\n"
            f"You are debater {chr(65+i)}. {_PERSONAS[i % len(_PERSONAS)]}\n"
            f"Present your opening argument."
            for i in range(agents)
        ]
        r0_results = await self._spawn_many(r0_tasks, timeout)
        r0_args = [r.output for r in r0_results]
        history.append(DebateRound(round=0, arguments=r0_args, rebuttals=[]))
        all_agent_ids.extend(r.agent_id for r in r0_results)

        # Round 1..N — 反驳强化
        for rnd in range(1, rounds):
            rebut_tasks = []
            for i in range(agents):
                opponent_args = [
                    history[-1].arguments[j]
                    for j in range(agents) if j != i
                ]
                rebut_tasks.append(
                    f"Debate topic: {topic}\n"
                    f"You are debater {chr(65+i)}. {_PERSONAS[i % len(_PERSONAS)]}\n"
                    f"Opponent arguments: {' | '.join(opponent_args)}\n"
                    f"Provide your rebuttal and strengthen your position."
                )
            rebut_results = await self._spawn_many(rebut_tasks, timeout)
            rebuttals = [r.output for r in rebut_results]
            history.append(DebateRound(
                round=rnd,
                arguments=[history[-1].arguments[i] for i in range(agents)],
                rebuttals=rebuttals,
            ))
            all_agent_ids.extend(r.agent_id for r in rebut_results)

        # 裁判总结
        all_args = "\n\n".join([
            f"Debater {chr(65+i)} initial: {history[0].arguments[i]}\n"
            f"Debater {chr(65+i)} final rebuttal: "
            f"{history[-1].rebuttals[i] if i < len(history[-1].rebuttals) else 'N/A'}"
            for i in range(agents)
        ])
        judge = await self._spawn(
            f"As an impartial judge, synthesize this debate on '{topic}' and give your verdict:\n"
            f"{all_args}",
            timeout,
        )
        all_agent_ids.append(judge.agent_id)

        return CollaborationResult(
            mode=CollaborationMode.DEBATE,
            agents=all_agent_ids,
            rounds=rounds + 1,
            final_output=judge.output,
            intermediate=history,
            consensus=0.5 + 0.1 * min(agents, 5),
            duration=time.time() - t0,
        )

    # ══════════════════════════════════════════
    # 2. Vote 投票模式
    # ══════════════════════════════════════════

    async def vote(
        self,
        options: list[str],
        agents: int = 3,
        strategy: VoteStrategy = VoteStrategy.MAJORITY,
        timeout: float | None = None,
    ) -> CollaborationResult:
        """多个Agent投票选择最优方案。

        参数:
            options: 候选选项列表
            agents: 投票Agent数
            strategy: 统计策略
        """
        t0 = time.time()
        option_list = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(options))
        ballots: list[VoteBallot] = []

        vote_tasks = [
            f"You are voter {i+1}/{agents}. {_PERSONAS[i % len(_PERSONAS)]}\n"
            f"Evaluate these options and vote for ONE:\n{option_list}\n"
            f"Format: CHOICE: <number> | CONFIDENCE: <0.0-1.0> | REASONING: <text>"
            for i in range(agents)
        ]
        results = await self._spawn_many(vote_tasks, timeout)

        for r in results:
            c, conf, reason = self._parse_choice(r.output, len(options))
            if c is not None:
                ballots.append(VoteBallot(
                    agent_id=r.agent_id,
                    choice=options[c - 1],
                    confidence=conf,
                    reasoning=reason,
                ))

        _tally: dict[str, int] = {}
        _weighted: dict[str, float] = {}
        for b in ballots:
            _tally[b.choice] = _tally.get(b.choice, 0) + 1
            _weighted[b.choice] = _weighted.get(b.choice, 0) + b.confidence

        if not ballots:
            return CollaborationResult(
                mode=CollaborationMode.VOTE,
                agents=[],
                rounds=1,
                final_output="No valid votes cast.",
                consensus=0.0,
                duration=time.time() - t0,
            )

        if strategy == VoteStrategy.WEIGHTED:
            winner = max(_weighted, key=_weighted.get)
            consensus = _weighted[winner] / sum(_weighted.values())
            summary = f"Weighted winner: {winner} (score: {_weighted[winner]:.2f})"
        elif strategy == VoteStrategy.UNANIMOUS:
            if len(_tally) == 1 and list(_tally.values())[0] == agents:
                winner, consensus = list(_tally.keys())[0], 1.0
                summary = f"Unanimous: {winner}"
            else:
                winner, consensus = "NO CONSENSUS", 0.0
                summary = "Unanimous vote FAILED"
        else:
            winner = max(_tally, key=_tally.get)
            consensus = _tally[winner] / len(ballots)
            summary = f"Majority winner: {winner} ({_tally[winner]}/{len(ballots)} votes)"

        report = f"{summary}\n\nVote details:\n"
        for b in ballots:
            report += f"- [{b.agent_id}] '{b.choice}' (conf={b.confidence:.2f}): {b.reasoning}\n"

        return CollaborationResult(
            mode=CollaborationMode.VOTE,
            agents=[b.agent_id for b in ballots],
            rounds=1,
            final_output=report,
            intermediate=ballots,
            consensus=consensus,
            duration=time.time() - t0,
        )

    # ══════════════════════════════════════════
    # 3. Review 审查模式
    # ══════════════════════════════════════════

    async def review(
        self,
        task: str,
        rounds: int = 2,
        timeout: float | None = None,
    ) -> CollaborationResult:
        """Writer产出 → Reviewer审查 → 多轮迭代。

        流程:
            1. Writer 生成初稿
            2. Reviewer 审查 → 打分 + 反馈
            3. Writer 根据反馈修改
            4. 重复 rounds 次
        """
        t0 = time.time()
        passes: list[ReviewPass] = []
        writer_id = uuid.uuid4().hex[:8]
        reviewer_id = uuid.uuid4().hex[:8]

        draft_result = await self._spawn(
            f"As a writer, complete: {task}", timeout,
        )
        draft = draft_result.output

        for rnd in range(rounds):
            review_result = await self._spawn(
                f"As a reviewer, evaluate this draft (round {rnd+1}):\n{draft}\n"
                f"Provide specific feedback. Format: SCORE: <0-10> | FEEDBACK: <text>",
                timeout,
            )
            feedback = review_result.output
            score = self._parse_score(feedback)

            revise_result = await self._spawn(
                f"As a writer, revise your draft based on this feedback:\n{feedback}\n\n"
                f"Original draft:\n{draft}\n\nProvide the revised version.",
                timeout,
            )
            revised = revise_result.output

            passes.append(ReviewPass(
                round=rnd + 1,
                draft=draft,
                feedback=feedback,
                revised=revised,
                score=score,
            ))
            draft = revised

        return CollaborationResult(
            mode=CollaborationMode.REVIEW,
            agents=[writer_id, reviewer_id],
            rounds=rounds,
            final_output=draft,
            intermediate=passes,
            consensus=passes[-1].score if passes else 0.0,
            duration=time.time() - t0,
        )

    # ══════════════════════════════════════════
    # 4. Pipeline 流水线模式
    # ══════════════════════════════════════════

    async def pipeline(
        self,
        task: str,
        stages: int = 3,
        stage_names: list[str] | None = None,
        timeout: float | None = None,
    ) -> CollaborationResult:
        """多Agent串联处理，前一输出是后一输入。

        参数:
            task: 初始输入
            stages: 流水线段数
            stage_names: 自定义阶段名，默认 ['Analyzer','Processor','Refiner',...]
        """
        t0 = time.time()
        if stage_names is None:
            stage_names = ["Analyzer", "Processor", "Refiner", "Polisher", "Validator"][:stages]

        intermediates: list[str] = []
        agent_ids: list[str] = []
        current_input = task

        for name in stage_names:
            result = await self._spawn(
                f"You are the {name} stage in a processing pipeline.\n"
                f"Input: {current_input}\nProcess and output for the next stage.",
                timeout,
            )
            current_input = result.output
            intermediates.append(current_input)
            agent_ids.append(result.agent_id)

        return CollaborationResult(
            mode=CollaborationMode.PIPELINE,
            agents=agent_ids,
            rounds=stages,
            final_output=current_input,
            intermediate=intermediates,
            consensus=1.0,
            duration=time.time() - t0,
        )

    # ══════════════════════════════════════════
    # 5. Ensemble 集成模式
    # ══════════════════════════════════════════

    async def ensemble(
        self,
        task: str,
        agents: int = 3,
        merge_strategy: str = "best_of",
        timeout: float | None = None,
    ) -> CollaborationResult:
        """多个Agent独立求解，合并最优。

        参数:
            task: 需求描述
            agents: 求解Agent数
            merge_strategy: 'best_of' | 'merge' | 'weighted'
        """
        t0 = time.time()

        tasks = [
            f"You are solver {i+1}/{agents}. {_PERSONAS[i % len(_PERSONAS)]}\n"
            f"Complete: {task}\nAt the end self-evaluate: SELF_SCORE: <0-10>"
            for i in range(agents)
        ]
        results = await self._spawn_many(tasks, timeout)

        scored: list[tuple[float, str, str]] = []
        for r in results:
            s = self._parse_score(r.output) * 10  # 0-10
            scored.append((s, r.output, r.agent_id))
        scored.sort(reverse=True, key=lambda x: x[0])

        if not scored:
            return CollaborationResult(
                mode=CollaborationMode.ENSEMBLE,
                agents=[], rounds=1,
                final_output="No results.",
                duration=time.time() - t0,
            )

        if merge_strategy == "best_of":
            bs, bo, ba = scored[0]
            final = f"Best solution (score: {bs:.1f}/10) from [{ba}]:\n\n{bo}"
        elif merge_strategy == "merge":
            parts = []
            for i, (s, o, a) in enumerate(scored):
                parts.append(f"[Solution {i+1}, score={s:.1f}]:\n{o[:500]}")
            merge_result = await self._spawn(
                f"As a meta-synthesizer, merge these {agents} solutions:\n\n"
                + "\n---\n".join(parts),
                timeout,
            )
            final = merge_result.output
        else:  # weighted
            total = sum(s for s, _, _ in scored)
            weights = [(s / total) if total else 0 for s, _, _ in scored]
            parts = []
            for (s, o, a), w in zip(scored, weights):
                parts.append(f"[{a}] weight={w:.2f}:\n{o[:300]}")
            final = f"Weighted ensemble ({agents} solvers):\n\n" + "\n---\n".join(parts)

        return CollaborationResult(
            mode=CollaborationMode.ENSEMBLE,
            agents=[a for _, _, a in scored],
            rounds=1,
            final_output=final,
            intermediate=scored,
            consensus=scored[0][0] / 10.0,
            duration=time.time() - t0,
        )
