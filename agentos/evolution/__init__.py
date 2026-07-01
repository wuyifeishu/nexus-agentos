"""Evolution module — Self-evolution system.

Components:
  - EvolutionEngine: Proposal lifecycle management (pending → approved → applied)
  - SignalCollector: User behavior signal collection and analysis
  - Learner: From signals to insights to evolution proposals
"""

from agentos.evolution.engine import (
    EvolutionEngine,
    EvolutionProposal,
    EvolutionStatus,
)
from agentos.evolution.signals import (
    BehaviorSignal,
    SignalCollector,
    SignalSummary,
    SignalType,
    FeedbackPolarity,
)
from agentos.evolution.learner import (
    Learner,
    LearningInsight,
)

__all__ = [
    # Engine
    "EvolutionEngine", "EvolutionProposal", "EvolutionStatus",
    # Signals
    "BehaviorSignal", "SignalCollector", "SignalSummary", "SignalType", "FeedbackPolarity",
    # Learner
    "Learner", "LearningInsight",
]
