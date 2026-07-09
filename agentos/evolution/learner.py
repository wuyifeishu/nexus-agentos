"""
Learning Engine — Analyzes behavior signals to generate evolution proposals.

The Learner sits between the SignalCollector and EvolutionEngine:
  1. SignalCollector gathers user behavior signals
  2. Learner analyzes signals, detects patterns, and suggests improvements
  3. EvolutionEngine manages the proposal lifecycle (pending → approved → applied)  # noqa: E501

Learning strategies:
  - Tool recommendation: suggest new tools based on usage patterns
  - Parameter tuning: adjust temperature, max_tokens based on feedback
  - Format adaptation: learn preferred output formats
  - Prompt refinement: improve system prompts based on corrections
  - Workflow optimization: suggest shortcuts for repeated tasks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentos.evolution.engine import EvolutionEngine, EvolutionProposal
from agentos.evolution.signals import (
    BehaviorSignal,
    SignalCollector,
    SignalSummary,
)


@dataclass
class LearningInsight:
    """A single insight derived from behavior signals."""

    category: (
        str  # tool_recommendation, param_tuning, format_adaptation, prompt_refinement, workflow
    )
    title: str
    description: str
    confidence: float  # 0.0 - 1.0
    evidence_count: int
    proposal_id: str = ""
    source_signals: list[str] = field(default_factory=list)


class Learner:
    """Learning engine — from signals to proposals.

    Usage:
        from agentos.evolution import EvolutionEngine, SignalCollector, Learner

        collector = SignalCollector()
        engine = EvolutionEngine()
        learner = Learner(collector, engine)

        # After accumulating signals...
        insights = learner.analyze()
        for insight in insights:
            proposal = learner.propose_from_insight(insight)
            print(f"Proposed: {proposal.description}")
    """

    def __init__(
        self,
        collector: SignalCollector,
        engine: EvolutionEngine,
        min_confidence: float = 0.6,
        auto_propose: bool = False,
    ):
        self._collector = collector
        self._engine = engine
        self._min_confidence = min_confidence
        self._auto_propose = auto_propose
        self._insights: list[LearningInsight] = []
        self._applied_count: int = 0

    # ── Analysis ──

    def analyze(self, hours: float = 168) -> list[LearningInsight]:
        """Analyze recent signals and generate learning insights."""
        summary = self._collector.summarize(hours)
        signals: list[BehaviorSignal] = self._collector._buffer[:]
        insights: list[LearningInsight] = []

        # 1. Tool recommendation
        insights.extend(self._analyze_tool_patterns(summary, signals))

        # 2. Parameter tuning suggestions
        insights.extend(self._analyze_feedback_for_tuning(summary))

        # 3. Format adaptation
        insights.extend(self._analyze_format_preferences(signals))

        # 4. Prompt refinement from corrections
        insights.extend(self._analyze_corrections(signals))

        # 5. Workflow optimization
        insights.extend(self._analyze_workflow_patterns(signals))

        # 6. General health
        insights.extend(self._analyze_health(summary))

        # Filter by confidence
        insights = [i for i in insights if i.confidence >= self._min_confidence]
        self._insights = insights

        # Auto-propose if enabled
        if self._auto_propose:
            for insight in insights:
                self.propose_from_insight(insight)

        return insights

    # ── Insight → Proposal ──

    def propose_from_insight(self, insight: LearningInsight) -> EvolutionProposal | None:
        """Convert a learning insight into an evolution proposal."""
        proposal = self._engine.propose(
            agent_name="marvis",
            change_type=insight.category,
            description=f"{insight.title}: {insight.description}",
            new_value={
                "category": insight.category,
                "title": insight.title,
                "description": insight.description,
                "confidence": insight.confidence,
            },
            confidence=insight.confidence,
            risk_level="medium" if insight.confidence > 0.5 else "low",
            insight_id=id(insight),
        )
        insight.proposal_id = proposal.id
        return proposal

    def approve_all(self) -> int:
        """Approve all pending proposals above confidence threshold."""
        count = 0
        for proposal in self._engine.list_proposals(status="pending"):
            self._engine.approve(proposal.id, approved_by="learner-auto")
            self._engine.apply(proposal.id)
            count += 1
            self._applied_count += 1
        return count

    # ── Private Analyzers ──

    def _analyze_tool_patterns(
        self, summary: SignalSummary, signals: list[BehaviorSignal]
    ) -> list[LearningInsight]:
        """Analyze tool usage to suggest new tools or deprecate unused ones."""
        insights = []

        # Low tool success rate → suggest alternatives
        if summary.tool_success_rate < 0.7 and summary.total_signals > 10:
            failing = [t for t, _ in summary.top_tools[:3]]
            insights.append(
                LearningInsight(
                    category="tool_recommendation",
                    title="Tool Success Rate Low",
                    description=f"Tools {failing} have low success rate ({summary.tool_success_rate:.0%}). Consider alternatives or improve error handling.",  # noqa: E501
                    confidence=0.75,
                    evidence_count=summary.total_signals,
                )
            )

        # High undo rate → tool is confusing
        if summary.undo_count >= 3:
            insights.append(
                LearningInsight(
                    category="tool_recommendation",
                    title="High Undo Rate Detected",
                    description=f"Users undo actions frequently ({summary.undo_count} times). Tool UX may need improvement.",  # noqa: E501
                    confidence=0.65,
                    evidence_count=summary.undo_count,
                )
            )

        return insights

    def _analyze_feedback_for_tuning(self, summary: SignalSummary) -> list[LearningInsight]:
        """Analyze feedback to suggest parameter tuning."""
        insights = []

        total_feedback = summary.positive_feedback + summary.negative_feedback
        if total_feedback < 5:
            return insights

        ratio = summary.positive_feedback / max(total_feedback, 1)

        if ratio < 0.4:
            insights.append(
                LearningInsight(
                    category="param_tuning",
                    title="Low Satisfaction Ratio",
                    description=f"Positive feedback ratio is {ratio:.0%}. Consider adjusting agent temperature or personality.",  # noqa: E501
                    confidence=0.8,
                    evidence_count=total_feedback,
                )
            )

        if ratio > 0.9:
            insights.append(
                LearningInsight(
                    category="param_tuning",
                    title="High Satisfaction — Lock Settings",
                    description=f"Positive feedback ratio is {ratio:.0%}. Current settings work well; consider locking as default.",  # noqa: E501
                    confidence=0.7,
                    evidence_count=total_feedback,
                )
            )

        return insights

    def _analyze_format_preferences(self, signals: list[BehaviorSignal]) -> list[LearningInsight]:
        """Learn preferred output formats."""
        preferences = [s for s in signals if s.type_.value == "format_preference"]
        if not preferences:
            return []

        format_counts = {}
        for s in preferences:
            fmt = s.feedback_type or "unknown"
            format_counts[fmt] = format_counts.get(fmt, 0) + 1

        top = max(format_counts, key=format_counts.get)
        if format_counts[top] >= 3:
            return [
                LearningInsight(
                    category="format_adaptation",
                    title=f"Format Preference: {top}",
                    description=f"User prefers {top} format ({format_counts[top]} signals). Default to this format.",
                    confidence=0.85,
                    evidence_count=format_counts[top],
                )
            ]

        return []

    def _analyze_corrections(self, signals: list[BehaviorSignal]) -> list[LearningInsight]:
        """Analyze corrections to suggest prompt refinements."""
        corrections = [s for s in signals if s.type_.value == "correction"]
        if len(corrections) < 2:
            return []

        # Group corrections by topic
        return [
            LearningInsight(
                category="prompt_refinement",
                title="Frequent Corrections Detected",
                description=f"User made {len(corrections)} corrections. Review agent responses for accuracy improvements.",  # noqa: E501
                confidence=0.7,
                evidence_count=len(corrections),
            )
        ]

    def _analyze_workflow_patterns(self, signals: list[BehaviorSignal]) -> list[LearningInsight]:
        """Detect repeated tool sequences to suggest workflow shortcuts."""
        tool_sequences = []
        current_seq = []

        for s in signals:
            if s.type_.value == "tool_usage" and s.tool_name:
                current_seq.append(s.tool_name)
                if len(current_seq) >= 2:
                    tool_sequences.append(tuple(current_seq[-2:]))

        if len(tool_sequences) < 5:
            return []

        from collections import Counter

        seq_counter = Counter(tool_sequences)
        top_seq = seq_counter.most_common(1)[0]

        if top_seq[1] >= 3:
            return [
                LearningInsight(
                    category="workflow",
                    title="Repeated Tool Sequence",
                    description=f"Sequence {' → '.join(top_seq[0])} repeated {top_seq[1]} times. Consider creating a shortcut or composite tool.",  # noqa: E501
                    confidence=0.65,
                    evidence_count=top_seq[1],
                )
            ]

        return []

    def _analyze_health(self, summary: SignalSummary) -> list[LearningInsight]:
        """General health check insights."""
        insights = []

        if summary.re_prompt_count >= 3:
            insights.append(
                LearningInsight(
                    category="prompt_refinement",
                    title="Clarify Intent Better",
                    description=f"User re-asked {summary.re_prompt_count} times. First responses may not understand user intent.",  # noqa: E501
                    confidence=0.6,
                    evidence_count=summary.re_prompt_count,
                )
            )

        return insights

    # ── Stats ──

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_insights": len(self._insights),
            "total_applied": self._applied_count,
            "auto_propose": self._auto_propose,
            "min_confidence": self._min_confidence,
            "latest_insights": [
                {
                    "category": i.category,
                    "title": i.title,
                    "confidence": i.confidence,
                    "proposal_id": i.proposal_id,
                }
                for i in self._insights[-5:]
            ],
        }
