"""
AgentOS Prompt Manager — Versioned Prompt Templates with A/B Testing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Production-grade prompt management:
  - Versioned prompt templates with semantic versioning
  - Variable interpolation with type validation
  - A/B testing with traffic splitting
  - Prompt lineage and diff history
  - Import/export (JSON, YAML)
  - System/user/assistant role support

Architecture:
  PromptTemplate  → single versioned template
  PromptStore     → registry of templates
  PromptRenderer  → interpolate variables into final prompt
  ABTestManager   → split traffic between template variants
"""

from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Prompt Template
# ---------------------------------------------------------------------------


class PromptRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class PromptTemplate:
    """A versioned prompt template."""

    name: str
    version: int = 1
    content: str = ""
    role: PromptRole = PromptRole.SYSTEM
    variables: set[str] = field(default_factory=set)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    author: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    # Variable pattern: {{variable_name}}
    VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")

    def extract_variables(self) -> set[str]:
        """Extract variable names from template content."""
        return set(self.VAR_PATTERN.findall(self.content))

    def render(self, values: dict[str, str], strict: bool = True) -> str:
        """
        Render the template by substituting variables.

        Args:
            values: Dict of variable_name → value
            strict: If True, raise on missing variables. If False, leave placeholders.

        Raises:
            ValueError: If strict=True and a variable is missing.
        """
        required = self.extract_variables()

        if strict:
            missing = required - set(values.keys())
            if missing:
                raise ValueError(
                    f"Template '{self.name}' v{self.version} missing variables: {missing}"
                )

        result = self.content
        for var_name in required:
            if var_name in values:
                result = result.replace(f"{{{{{var_name}}}}}", values[var_name])
            elif not strict:
                # Leave placeholder intact
                pass

        return result

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate template structure.

        Returns (is_valid, list_of_issues).
        """
        issues = []
        if not self.name:
            issues.append("Name is required")
        if not self.content:
            issues.append("Content is empty")
        if self.VAR_PATTERN.findall(self.content):
            # Variables are OK, just note them
            pass
        return len(issues) == 0, issues

    def diff(self, other: PromptTemplate) -> str:
        """Generate a unified diff between this and another template."""
        a_lines = self.content.splitlines(keepends=True)
        b_lines = other.content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            a_lines,
            b_lines,
            fromfile=f"{self.name} v{self.version}",
            tofile=f"{other.name} v{other.version}",
        )
        return "".join(diff)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "content": self.content,
            "role": self.role.value,
            "variables": sorted(self.variables),
            "description": self.description,
            "tags": self.tags,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_active": self.is_active,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptTemplate:
        return cls(
            name=data["name"],
            version=data.get("version", 1),
            content=data["content"],
            role=PromptRole(data.get("role", "system")),
            variables=set(data.get("variables", [])),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            author=data.get("author", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            is_active=data.get("is_active", True),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Prompt Store
# ---------------------------------------------------------------------------


class PromptStore:
    """
    Registry of prompt templates with versioning.

    Supports:
      - Semantic versioning per template
      - Latest/active version resolution
      - Template lineage tracking
      - Import/export (JSON)
    """

    def __init__(self):
        self._templates: dict[str, dict[int, PromptTemplate]] = defaultdict(dict)
        self._latest: dict[str, int] = {}
        self._active: dict[str, int] = {}
        self._lineage: dict[str, list[int]] = defaultdict(list)

    def add(self, template: PromptTemplate) -> PromptTemplate:
        """
        Add a new template or create a new version.

        Auto-increments version if template name already exists.
        """
        name = template.name

        if name in self._latest:
            # New version
            latest = self._latest[name]
            template.version = latest + 1
        else:
            template.version = template.version or 1

        if not template.variables:
            template.variables = template.extract_variables()

        template.updated_at = datetime.now(UTC).isoformat()
        self._templates[name][template.version] = template
        self._latest[name] = template.version
        self._active[name] = template.version
        self._lineage[name].append(template.version)

        return template

    def get(self, name: str, version: int | None = None) -> PromptTemplate | None:
        """Get a template by name and optional version. Defaults to active version."""
        if name not in self._templates:
            return None

        if version is not None:
            return self._templates[name].get(version)

        active_ver = self._active.get(name) or self._latest[name]
        return self._templates[name].get(active_ver)

    def get_latest(self, name: str) -> PromptTemplate | None:
        """Get the latest version of a template."""
        if name not in self._latest:
            return None
        return self._templates[name].get(self._latest[name])

    def set_active(self, name: str, version: int) -> bool:
        """Set which version is the active one."""
        if name not in self._templates or version not in self._templates[name]:
            return False
        self._active[name] = version
        return True

    def deactivate(self, name: str) -> None:
        """Deactivate a template (no active version)."""
        self._active.pop(name, None)

    def list_templates(self) -> list[dict[str, Any]]:
        """List all templates with their versions."""
        result = []
        for name, versions in self._templates.items():
            latest = self._latest[name]
            active = self._active.get(name, latest)
            result.append(
                {
                    "name": name,
                    "versions": sorted(versions.keys()),
                    "latest": latest,
                    "active": active,
                    "total_versions": len(versions),
                }
            )
        return sorted(result, key=lambda x: x["name"])

    def get_history(self, name: str) -> list[PromptTemplate]:
        """Get all versions of a template in chronological order."""
        if name not in self._templates:
            return []
        return [self._templates[name][v] for v in sorted(self._templates[name].keys())]

    def diff_versions(self, name: str, v1: int, v2: int) -> str | None:
        """Get diff between two versions of a template."""
        t1 = self.get(name, v1)
        t2 = self.get(name, v2)
        if t1 is None or t2 is None:
            return None
        return t1.diff(t2)

    def remove(self, name: str, version: int | None = None) -> int:
        """
        Remove template(s). If version is None, remove all versions.
        Returns number of versions removed.
        """
        if name not in self._templates:
            return 0

        if version is not None:
            if version in self._templates[name]:
                del self._templates[name][version]
                if version == self._latest.get(name):
                    remaining = sorted(self._templates[name].keys())
                    self._latest[name] = remaining[-1] if remaining else 0
                return 1
            return 0

        count = len(self._templates[name])
        del self._templates[name]
        self._latest.pop(name, None)
        self._active.pop(name, None)
        self._lineage.pop(name, None)
        return count

    def export_json(self, names: list[str] | None = None) -> str:
        """Export templates as JSON."""
        templates = []
        target = names or list(self._templates.keys())
        for name in target:
            for t in self._templates.get(name, {}).values():
                templates.append(t.to_dict())
        return json.dumps({"templates": templates}, indent=2, ensure_ascii=False)

    def import_json(self, json_str: str) -> int:
        """Import templates from JSON. Returns count of imported templates."""
        data = json.loads(json_str)
        count = 0
        for td in data.get("templates", []):
            template = PromptTemplate.from_dict(td)
            self.add(template)
            count += 1
        return count


# ---------------------------------------------------------------------------
# A/B Test Manager
# ---------------------------------------------------------------------------


@dataclass
class ABTest:
    """An A/B test comparing two prompt template versions."""

    name: str
    template_name: str
    variant_a_version: int
    variant_b_version: int
    split_ratio: float = 0.5  # 0.5 = 50% each
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def route(self, session_id: str) -> int:
        """Route a session to variant A (0) or B (1)."""
        if not self.is_active:
            return 0  # Default to A if test is inactive

        # Deterministic routing based on session hash
        hash_val = abs(hash(f"{self.name}:{session_id}"))
        bucket = (hash_val % 100) / 100.0
        return 0 if bucket < self.split_ratio else 1


class ABTestManager:
    """Manage A/B tests for prompt templates."""

    def __init__(self, store: PromptStore):
        self._store = store
        self._tests: dict[str, ABTest] = {}
        self._results: dict[str, dict[str, int]] = defaultdict(
            lambda: {"a_served": 0, "b_served": 0}
        )

    def create_test(
        self,
        name: str,
        template_name: str,
        variant_a_version: int,
        variant_b_version: int,
        split_ratio: float = 0.5,
    ) -> ABTest:
        """Create a new A/B test."""
        test = ABTest(
            name=name,
            template_name=template_name,
            variant_a_version=variant_a_version,
            variant_b_version=variant_b_version,
            split_ratio=split_ratio,
        )
        self._tests[name] = test
        return test

    def get_template(self, test_name: str, session_id: str) -> PromptTemplate | None:
        """
        Get the prompt template for a session in an A/B test.

        Returns None if the test doesn't exist or template not found.
        """
        test = self._tests.get(test_name)
        if test is None:
            return None

        variant = test.route(session_id)
        version = test.variant_a_version if variant == 0 else test.variant_b_version

        self._results[test_name][f"{'a' if variant == 0 else 'b'}_served"] += 1

        return self._store.get(test.template_name, version)

    def get_results(self, name: str) -> dict[str, Any]:
        """Get results for an A/B test."""
        test = self._tests.get(name)
        if test is None:
            return {}

        results = dict(self._results[name])
        total = results.get("a_served", 0) + results.get("b_served", 0)
        return {
            "test_name": name,
            "template_name": test.template_name,
            "variant_a_version": test.variant_a_version,
            "variant_b_version": test.variant_b_version,
            "split_ratio": test.split_ratio,
            "is_active": test.is_active,
            **results,
            "total_served": total,
            "a_pct": round(results.get("a_served", 0) / max(1, total) * 100, 1),
            "b_pct": round(results.get("b_served", 0) / max(1, total) * 100, 1),
        }

    def stop_test(self, name: str) -> None:
        """Stop an active A/B test."""
        if name in self._tests:
            self._tests[name].is_active = False

    def list_tests(self) -> list[dict[str, Any]]:
        """List all A/B tests."""
        return [self.get_results(name) for name in self._tests]
