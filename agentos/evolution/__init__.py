"""Evolution module — Self-evolution system v2.

Components:
  - EvolutionEngine: Proposal lifecycle management (pending → approved → applied)
  - SignalCollector: User behavior signal collection and analysis
  - Learner: From signals to insights to evolution proposals
  - AutoPilot: Closed-loop self-evolution pipeline (v2, auto-generate/appply/validate diffs)
"""

from agentos.evolution.autopilot import (
    ABEvaluator,
    AutoPilot,
    AutoPilotMode,
    AutoTester,
    CodeGenerator,
    EvolutionJournal,
    EvolutionRun,
    RollbackManager,
)
from agentos.evolution.engine import (
    EvolutionEngine,
    EvolutionProposal,
    EvolutionStatus,
)
from agentos.evolution.learner import (
    Learner,
    LearningInsight,
)
from agentos.evolution.signals import (
    BehaviorSignal,
    FeedbackPolarity,
    SignalCollector,
    SignalSummary,
    SignalType,
)

__all__ = [
    # Engine
    "EvolutionEngine",
    "EvolutionProposal",
    "EvolutionStatus",
    # Signals
    "BehaviorSignal",
    "SignalCollector",
    "SignalSummary",
    "SignalType",
    "FeedbackPolarity",
    # Learner
    "Learner",
    "LearningInsight",
    # AutoPilot v2
    "AutoPilot",
    "AutoPilotMode",
    "CodeGenerator",
    "AutoTester",
    "RollbackManager",
    "ABEvaluator",
    "EvolutionJournal",
    "EvolutionRun",
]
