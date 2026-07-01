"""v1.10.0: External Evaluation Harness — SWE-bench & GAIA benchmarks."""
from agentos.eval.benchmark import (
    EvalMetric, EvalSuite, EvalCase, EvalSample, EvalResult, EvalReport,
    Scorer, ExactMatchScorer, F1Scorer, ROUGELScorer, get_scorer,
    SWEBenchLoader, GAIALoader,
    EvalRunner, EvalRegistry, evaluate_quick,
)

__all__ = [
    "EvalMetric", "EvalSuite", "EvalCase", "EvalSample", "EvalResult", "EvalReport",
    "Scorer", "ExactMatchScorer", "F1Scorer", "ROUGELScorer", "get_scorer",
    "SWEBenchLoader", "GAIALoader",
    "EvalRunner", "EvalRegistry", "evaluate_quick",
]
