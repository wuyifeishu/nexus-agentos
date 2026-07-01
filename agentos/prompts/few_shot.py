"""
Few-Shot Example Management — intelligent few-shot selection strategies.

Supports similarity-based, random, diversity-maximizing, and
custom selection algorithms for constructing optimal few-shot prompts.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence
import hashlib
import random
import re


class SelectionStrategy(str, Enum):
    """Strategy for selecting few-shot examples."""

    RANDOM = "random"
    SIMILARITY = "similarity"
    DIVERSITY = "diversity"
    RECENCY = "recency"
    LABEL_BALANCED = "label_balanced"
    ACTIVE_LEARNING = "active_learning"


@dataclass
class Example:
    """A single training example for few-shot learning."""

    input: str
    output: str
    id: str = ""
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = hashlib.md5(
                f"{self.input}{self.output}".encode()
            ).hexdigest()[:12]


class FewShotSelector:
    """Selects and formats the best few-shot examples for a given query.

    Usage::

        examples = [
            Example(input="What is 2+2?", output="4", label="math"),
            Example(input="Capital of France?", output="Paris", label="geo"),
        ]
        selector = FewShotSelector(examples, strategy=SelectionStrategy.SIMILARITY)
        prompt = selector.build_prompt("What is 3+5?", base_instruction="Answer:")
    """

    DEFAULT_FORMAT = "Q: {input}\nA: {output}"
    MAX_TOKEN_ESTIMATE = 4096

    def __init__(
        self,
        examples: Sequence[Example],
        strategy: SelectionStrategy = SelectionStrategy.SIMILARITY,
        max_examples: int = 5,
        example_format: str = "",
        seed: int = 42,
    ):
        self.examples = list(examples)
        self.strategy = strategy
        self.max_examples = max_examples
        self.example_format = example_format or self.DEFAULT_FORMAT
        random.seed(seed)

    def select(self, query: str, k: Optional[int] = None) -> list[Example]:
        """Select top-k examples for the given query."""
        k = k or self.max_examples
        if not self.examples:
            return []

        strategy_map = {
            SelectionStrategy.RANDOM: self._select_random,
            SelectionStrategy.SIMILARITY: self._select_similarity,
            SelectionStrategy.DIVERSITY: self._select_diversity,
            SelectionStrategy.RECENCY: self._select_recency,
            SelectionStrategy.LABEL_BALANCED: self._select_label_balanced,
        }
        selector_fn = strategy_map.get(self.strategy, self._select_similarity)
        return selector_fn(query, k)

    def build_prompt(
        self,
        query: str,
        base_instruction: str = "",
        k: Optional[int] = None,
    ) -> str:
        """Build a complete few-shot prompt string."""
        selected = self.select(query, k)
        parts: list[str] = []
        if base_instruction:
            parts.append(base_instruction)
        for ex in selected:
            parts.append(self.example_format.format(input=ex.input, output=ex.output))
        parts.append(self.example_format.format(input=query, output=""))
        return "\n\n".join(parts)

    def add_example(self, example: Example):
        """Add a new example to the pool."""
        self.examples.append(example)

    def remove_example(self, example_id: str):
        """Remove an example by ID."""
        self.examples = [e for e in self.examples if e.id != example_id]

    def set_score(self, example_id: str, score: float):
        """Update the utility score for an example."""
        for ex in self.examples:
            if ex.id == example_id:
                ex.score = score
                break

    def _select_random(self, _query: str, k: int) -> list[Example]:
        return random.sample(self.examples, min(k, len(self.examples)))

    def _select_similarity(self, query: str, k: int) -> list[Example]:
        """Jaccard-based token similarity for fast selection."""
        query_tokens = set(_tokenize(query))
        scored = [
            (ex, self._jaccard(query_tokens, ex))
            for ex in self.examples
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [ex for ex, _ in scored[:k]]

    def _select_diversity(self, _query: str, k: int) -> list[Example]:
        """Maximize diversity via greedy farthest-first."""
        if k >= len(self.examples):
            return list(self.examples)
        # Start with a random seed
        selected = [random.choice(self.examples)]
        remaining = [e for e in self.examples if e not in selected]
        while len(selected) < k and remaining:
            # Pick the example least similar to any already selected
            best = max(
                remaining,
                key=lambda ex: min(
                    self._jaccard(set(_tokenize(ex.input)), s)
                    for s in selected
                ),
            )
            selected.append(best)
            remaining.remove(best)
        return selected

    def _select_recency(self, _query: str, k: int) -> list[Example]:
        """Most recent examples first (assumes append order = recency)."""
        return list(reversed(self.examples[-k:]))

    def _select_label_balanced(self, _query: str, k: int) -> list[Example]:
        """Balance selection across unique labels."""
        by_label: dict[str, list[Example]] = {}
        for ex in self.examples:
            by_label.setdefault(ex.label or "_unlabeled", []).append(ex)
        labels = list(by_label.keys())
        result: list[Example] = []
        idx = 0
        while len(result) < k and any(by_label.values()):
            label = labels[idx % len(labels)]
            pool = by_label[label]
            if pool:
                result.append(pool.pop(random.randrange(len(pool))))
            idx += 1
        return result

    @staticmethod
    def _jaccard(tokens_a: set[str], example: Example) -> float:
        tokens_b = set(_tokenize(example.input))
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)


def build_examples(
    pairs: Iterable[tuple[str, str]],
    labels: Iterable[str] | None = None,
    metadata: list[dict] | None = None,
) -> list[Example]:
    """Convenience factory to build a list of Example objects.

    Args:
        pairs: Iterable of (input, output) tuples.
        labels: Optional labels for each example.
        metadata: Optional metadata dicts.

    Returns:
        List of ``Example`` objects.
    """
    examples: list[Example] = []
    label_list = list(labels) if labels else []
    meta_list = list(metadata) if metadata else []
    for i, (inp, out) in enumerate(pairs):
        ex = Example(
            input=inp,
            output=out,
            label=label_list[i] if i < len(label_list) else "",
            metadata=meta_list[i] if i < len(meta_list) else {},
        )
        examples.append(ex)
    return examples


def _tokenize(text: str) -> list[str]:
    """Simple whitespace+punctuation tokenizer."""
    return re.findall(r"\w+", text.lower())
