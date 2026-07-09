from dataclasses import dataclass


class ExperimentRunner:
    pass


@dataclass
class ExperimentConfig:
    name: str = ""


@dataclass
class ExperimentReport:
    pass


@dataclass
class PromptVariant:
    name: str = ""


@dataclass
class TrialResult:
    score: float = 0.0


class Evaluator:
    pass
