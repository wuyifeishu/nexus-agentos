from dataclasses import dataclass
from enum import Enum


class FeedbackType(Enum):
    RATING = "rating"


@dataclass
class FeedbackRecord:
    feedback: str = ""


class FeedbackCollector:
    pass


class PreferenceLearner:
    pass
