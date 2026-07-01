"""
v1.10.0: Prompt Hub — versioned prompt templates with Jinja2 rendering.

Features:
- PromptTemplate: Jinja2 template with metadata
- PromptVersion: version-tracked prompt with diff
- PromptHub: central registry with search/rollback
- Role templates: system, few-shot, chain-of-thought presets
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ── Enums & Data Classes ──────────────────────────────────────────

class PromptType(str, Enum):
    SYSTEM = "system"               # System prompt
    USER = "user"                   # User message template
    ASSISTANT = "assistant"         # Assistant response template
    FEW_SHOT = "few_shot"           # Few-shot example template
    CHAIN_OF_THOUGHT = "cot"        # Chain-of-thought template
    TOOL_CALL = "tool_call"         # Tool-calling template
    EVAL = "eval"                   # Evaluation rubric template
    CUSTOM = "custom"


class PromptTag(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"
    A_B_TEST = "a_b_test"


@dataclass
class PromptVersion:
    """A versioned instance of a prompt template."""
    version: int
    content: str
    rendered_example: str = ""
    created_at: str = ""
    author: str = ""
    change_summary: str = ""
    performance: dict[str, float] = field(default_factory=dict)  # e.g. {"accuracy": 0.92}

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class PromptTemplate:
    """A prompt template with versioning, tags, and Jinja2 rendering.

    Usage:
        tpl = PromptTemplate(
            name="code-review",
            type=PromptType.SYSTEM,
            content="You are a code reviewer. Review: {{ code }}",
            variables={"code": "python code here"},
        )
        rendered = tpl.render(code="def foo(): pass")
    """

    name: str
    type: PromptType
    content: str                          # Jinja2 template string
    variables: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    current_version: int = 1
    versions: list[PromptVersion] = field(default_factory=list)

    def __post_init__(self):
        if not self.versions:
            self.versions = [PromptVersion(
                version=1,
                content=self.content,
                change_summary="Initial version",
            )]

    def render(self, **kwargs) -> str:
        """Render the template with Jinja2 variables."""
        try:
            from jinja2 import Template, StrictUndefined
            tpl = Template(self.content, undefined=StrictUndefined)
            return tpl.render(**{**self.variables, **kwargs})
        except ImportError:
            # Fallback: simple {{ var }} substitution
            result = self.content
            all_vars = {**self.variables, **kwargs}
            for key, value in all_vars.items():
                result = result.replace(f"{{{{ {key} }}}}", str(value))
            return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "content": self.content,
            "variables": self.variables,
            "description": self.description,
            "tags": self.tags,
            "current_version": self.current_version,
        }

    def update(
        self,
        content: str,
        change_summary: str = "",
        rendered_example: str = "",
        author: str = "",
    ) -> PromptVersion:
        """Create a new version. Bumps current_version."""
        self.current_version += 1
        version = PromptVersion(
            version=self.current_version,
            content=content,
            rendered_example=rendered_example,
            author=author,
            change_summary=change_summary,
        )
        self.content = content
        self.versions.append(version)
        return version

    def rollback(self, target_version: int) -> PromptVersion | None:
        """Rollback to a previous version."""
        for v in self.versions:
            if v.version == target_version:
                self.content = v.content
                return v
        return None

    def diff(self, v1: int, v2: int) -> str:
        """Return a simple diff between two versions."""
        ver1 = next((v for v in self.versions if v.version == v1), None)
        ver2 = next((v for v in self.versions if v.version == v2), None)
        if not ver1 or not ver2:
            return ""

        lines1 = ver1.content.split("\n")
        lines2 = ver2.content.split("\n")
        diff_lines = []
        max_len = max(len(lines1), len(lines2))

        for i in range(max_len):
            l1 = lines1[i] if i < len(lines1) else ""
            l2 = lines2[i] if i < len(lines2) else ""
            if l1 != l2:
                if l1:
                    diff_lines.append(f"- {l1}")
                if l2:
                    diff_lines.append(f"+ {l2}")
        return "\n".join(diff_lines)

    def hash(self) -> str:
        """Content hash for cache-busting."""
        return hashlib.md5(self.content.encode()).hexdigest()[:12]


# ── Prompt Hub ────────────────────────────────────────────────────

class PromptHub:
    """Central prompt registry with search, import/export, A/B testing.

    Usage:
        hub = PromptHub()
        hub.register(PromptTemplate(name="greet", type=PromptType.SYSTEM, content="Hello {{ name }}"))
        rendered = hub.render("greet", name="World")
    """

    def __init__(self, storage_path: str | Path | None = None):
        self._prompts: dict[str, PromptTemplate] = {}
        self.storage_path = Path(storage_path) if storage_path else None
        self._ab_active: dict[str, str] = {}  # prompt_name → variant_name

        # Load from storage if available
        if self.storage_path and self.storage_path.exists():
            self._load()

    def register(self, template: PromptTemplate) -> None:
        """Register a prompt template."""
        self._prompts[template.name] = template

    def get(self, name: str) -> PromptTemplate:
        """Get a prompt by name."""
        if name not in self._prompts:
            raise KeyError(f"Prompt not found: {name}")
        return self._prompts[name]

    def render(self, name: str, **kwargs) -> str:
        """Render a prompt by name with variables."""
        return self.get(name).render(**kwargs)

    def search(self, query: str) -> list[PromptTemplate]:
        """Search prompts by name, description, content, or tags."""
        q = query.lower()
        results = []
        for tpl in self._prompts.values():
            score = 0
            if q in tpl.name.lower():
                score += 10
            if q in tpl.description.lower():
                score += 5
            if q in tpl.content.lower():
                score += 3
            if any(q in tag.lower() for tag in tpl.tags):
                score += 2
            if score > 0:
                results.append((score, tpl))
        return [t for _, t in sorted(results, key=lambda x: -x[0])]

    def list_by_type(self, ptype: PromptType) -> list[PromptTemplate]:
        """List all prompts of a given type."""
        return [t for t in self._prompts.values() if t.type == ptype]

    def list_by_tag(self, tag: str) -> list[PromptTemplate]:
        """List all prompts with a given tag."""
        return [t for t in self._prompts.values() if tag in t.tags]

    def export_json(self, path: str | Path) -> None:
        """Export all prompts to JSON."""
        data = {name: tpl.to_dict() for name, tpl in self._prompts.items()}
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def import_json(self, path: str | Path) -> int:
        """Import prompts from JSON. Returns count of imported prompts."""
        data = json.loads(Path(path).read_text())
        count = 0
        for name, pdata in data.items():
            tpl = PromptTemplate(
                name=name,
                type=PromptType(pdata.get("type", "custom")),
                content=pdata["content"],
                variables=pdata.get("variables", {}),
                description=pdata.get("description", ""),
                tags=pdata.get("tags", []),
            )
            self.register(tpl)
            count += 1
        return count

    def _load(self) -> None:
        """Load prompts from storage directory."""
        if not self.storage_path:
            return
        for fpath in self.storage_path.glob("*.json"):
            self.import_json(fpath)

    def _save(self, name: str) -> None:
        """Save a single prompt to storage."""
        if not self.storage_path:
            return
        self.storage_path.mkdir(parents=True, exist_ok=True)
        tpl = self._prompts.get(name)
        if tpl:
            (self.storage_path / f"{name}.json").write_text(
                json.dumps({name: tpl.to_dict()}, indent=2, ensure_ascii=False)
            )

    def ab_test_set(self, prompt_name: str, variant_a: str, variant_b: str, active: str = "a") -> None:
        """Set up A/B test between two prompt variants."""
        self._ab_active[prompt_name] = active

    @property
    def count(self) -> int:
        return len(self._prompts)


# ── Built-in Prompt Presets ────────────────────────────────────────

BUILTIN_PROMPTS: dict[str, dict[str, Any]] = {
    "system/reasoning": {
        "type": PromptType.SYSTEM,
        "content": (
            "You are an expert reasoning assistant. "
            "Before answering, think step by step:\n"
            "1. Understand the problem\n"
            "2. Break it into sub-problems\n"
            "3. Solve each sub-problem\n"
            "4. Synthesize the final answer\n\n"
            "{{ extra_instructions }}"
        ),
        "variables": {"extra_instructions": ""},
        "tags": ["reasoning", "system"],
    },
    "system/code-assistant": {
        "type": PromptType.SYSTEM,
        "content": (
            "You are a senior software engineer. "
            "Write clean, efficient, well-documented code. "
            "Use {{ language }}. Follow these conventions: {{ conventions }}."
        ),
        "variables": {"language": "Python", "conventions": "PEP 8"},
        "tags": ["code", "system"],
    },
    "few-shot/classification": {
        "type": PromptType.FEW_SHOT,
        "content": (
            "Classify the following text into categories: {{ categories }}\n\n"
            "Example 1:\nText: {{ example_1_text }}\nCategory: {{ example_1_label }}\n\n"
            "Example 2:\nText: {{ example_2_text }}\nCategory: {{ example_2_label }}\n\n"
            "Now classify:\nText: {{ input_text }}\nCategory:"
        ),
        "variables": {
            "categories": "positive/negative/neutral",
            "example_1_text": "I love this product!",
            "example_1_label": "positive",
            "example_2_text": "This is terrible.",
            "example_2_label": "negative",
            "input_text": "",
        },
        "tags": ["few-shot", "classification"],
    },
    "cot/math": {
        "type": PromptType.CHAIN_OF_THOUGHT,
        "content": (
            "Solve this math problem step by step. Show all your work.\n\n"
            "Problem: {{ problem }}\n\n"
            "Let's solve this step by step:\n"
            "Step 1: Understand what we're asked to find.\n"
            "Step 2: Identify the relevant formulas or concepts.\n"
            "Step 3: Apply them and solve.\n"
            "Step 4: Verify the answer.\n\n"
            "Final Answer:"
        ),
        "variables": {"problem": ""},
        "tags": ["cot", "math", "reasoning"],
    },
    "eval/accuracy": {
        "type": PromptType.EVAL,
        "content": (
            "You are an evaluator. Grade the following response on a scale of 0-10.\n\n"
            "Criteria: {{ criteria }}\n\n"
            "Question: {{ question }}\n"
            "Expected Answer: {{ expected }}\n"
            "Generated Answer: {{ generated }}\n\n"
            "Score (0-10):\n"
            "Justification:"
        ),
        "variables": {"criteria": "accuracy", "question": "", "expected": "", "generated": ""},
        "tags": ["eval", "scoring"],
    },
}


def create_default_hub() -> PromptHub:
    """Create a prompt hub pre-loaded with built-in templates."""
    hub = PromptHub()
    for name, cfg in BUILTIN_PROMPTS.items():
        hub.register(PromptTemplate(
            name=name,
            type=cfg["type"],
            content=cfg["content"],
            variables=cfg.get("variables", {}),
            tags=cfg.get("tags", []),
        ))
    return hub
