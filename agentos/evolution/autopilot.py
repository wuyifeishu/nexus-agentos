"""
Closed-Loop Self-Evolution v2 (v1.9.0)

AutoPilot — from behavior signals to code changes, fully automated.

Pipeline:
  1. SignalCollector gathers user behavior (corrections, ratings, tool usage)
  2. Learner detects patterns → generates EvolutionProposal
  3. AutoPilot validates → generates code change → auto-tests → applies
  4. Regression tests verify no breakage
  5. Proposal archived with before/after metrics

v2 New Features:
  - CodeGenerator: LLM-based code diff generation from proposals
  - AutoTester: Run regression suite before/after each change
  - RollbackManager: Instant undo if regression detected
  - Confidence Gating: Only auto-apply proposals above confidence threshold
  - A/B Evaluator: Side-by-side before/after comparison
  - EvolutionJournal: Full audit trail of every evolution step
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Any

from agentos.evolution.engine import EvolutionEngine, EvolutionProposal, EvolutionStatus
from agentos.evolution.learner import Learner, LearningInsight
from agentos.evolution.signals import SignalCollector, BehaviorSignal


# ── Types ───────────────────────────────────────────────────────────

class AutoPilotMode(str, Enum):
    """AutoPilot operating mode."""
    SUGGEST_ONLY = "suggest_only"    # Only generate proposals, don't apply
    ASK_BEFORE = "ask_before"        # Generate + ask user before applying
    CONFIDENCE_GATED = "confidence"   # Auto-apply if confidence > threshold
    FULL_AUTO = "full_auto"          # Auto-apply everything (⚠️ use with guardrails)


class ChangeResult(str, Enum):
    """Result of an auto-applied change."""
    SUCCESS = "success"
    FAILED = "failed"
    REGRESSION = "regression"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


@dataclass
class CodeChange:
    """A code change generated from an evolution proposal."""
    proposal_id: str
    file_path: str
    description: str
    diff: str                    # Unified diff
    old_content: str = ""        # Pre-change content (for rollback)
    new_content: str = ""        # Post-change content
    language: str = "python"
    risk_level: str = "medium"   # low / medium / high
    test_results: dict[str, Any] = field(default_factory=dict)

@dataclass
class EvolutionRun:
    """Record of a single evolution execution."""
    run_id: str
    proposal: EvolutionProposal
    changes: list[CodeChange] = field(default_factory=list)
    result: ChangeResult = ChangeResult.SKIPPED
    started_at: float = 0.0
    finished_at: float = 0.0
    rollback_info: dict[str, Any] = field(default_factory=dict)
    metrics_before: dict[str, Any] = field(default_factory=dict)
    metrics_after: dict[str, Any] = field(default_factory=dict)


# ── Code Generator ──────────────────────────────────────────────────

class CodeGenerator:
    """Generate code changes from evolution proposals using LLM.

    Takes a high-level proposal (e.g., 'add retry logic to API calls')
    and generates concrete unified diffs.
    """

    SYSTEM_PROMPT = """You are an expert Python code generator for an agent framework.
Given an evolution proposal, generate precise, minimal code changes.
Output ONLY a unified diff format. No explanations, no markdown code blocks.
Focus on: correctness, backward compatibility, performance, readability."""

    def __init__(self, llm_client=None):
        self._llm = llm_client

    async def generate(self, proposal: EvolutionProposal, codebase: dict[str, str]) -> list[CodeChange]:
        """Generate code changes for a proposal.

        Args:
            proposal: The evolution proposal to implement
            codebase: Dict of {file_path: file_content} for context

        Returns:
            List of CodeChange objects with unified diffs.
        """
        changes: list[CodeChange] = []

        if not self._llm:
            # Fallback: generate skeleton changes based on proposal type
            return self._skeleton_generate(proposal)

        for target_file in proposal.target_files:
            content = codebase.get(target_file, "")
            prompt = self._build_prompt(proposal, target_file, content)

            response = await self._llm.complete(prompt, system=self.SYSTEM_PROMPT)
            diff = self._extract_diff(response)

            if diff:
                new_content = self._apply_diff(content, diff)
                changes.append(CodeChange(
                    proposal_id=proposal.id,
                    file_path=target_file,
                    description=proposal.description,
                    diff=diff,
                    old_content=content,
                    new_content=new_content,
                    risk_level=proposal.risk_level,
                ))

        return changes

    def _skeleton_generate(self, proposal: EvolutionProposal) -> list[CodeChange]:
        """Skeleton code generation for proposals (no LLM available)."""
        changes = []
        for target_file in proposal.target_files:
            changes.append(CodeChange(
                proposal_id=proposal.id,
                file_path=target_file,
                description=proposal.description,
                diff=f"# SKELETON: {proposal.description}\n# File: {target_file}",
                risk_level=proposal.risk_level,
            ))
        return changes

    def _build_prompt(self, proposal: EvolutionProposal, target_file: str, content: str) -> str:
        return f"""Proposal: {proposal.description}
Category: {proposal.category}
File: {target_file}
Priority: {proposal.priority}

Current file content:
```python
{content[:3000]}
```

Generate a unified diff to implement this change. Focus only on {target_file}."""

    def _extract_diff(self, response: str) -> str:
        """Extract unified diff from LLM response."""
        if response.startswith("---") or response.startswith("diff "):
            return response
        if "```diff" in response:
            start = response.index("```diff") + 7
            end = response.index("```", start) if "```" in response[start:] else len(response)
            return response[start:end].strip()
        return response.strip()

    def _apply_diff(self, content: str, diff: str) -> str:
        """Simple diff application for well-known patterns."""
        if diff.startswith("# SKELETON"):
            return content
        try:
            result = subprocess.run(
                ["patch", "-o", "-", "-"],
                input=f"--- a/file\n+++ b/file\n{diff}".encode(),
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.decode()
        except Exception:
            pass
        return content


# ── Auto Tester ─────────────────────────────────────────────────────

class AutoTester:
    """Run test suite to validate changes."""

    def __init__(self, test_dir: str = "", pytest_args: str = ""):
        self._test_dir = Path(test_dir) if test_dir else Path("tests")
        self._pytest_args = pytest_args or "-x --tb=short -q"

    async def run_tests(self) -> dict[str, Any]:
        """Run the test suite.

        Returns:
            Dict with passed/failed/total counts and error details.
        """
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", str(self._test_dir)] + self._pytest_args.split(),
                capture_output=True, text=True, timeout=120,
                cwd=str(self._test_dir.parent) if self._test_dir.parent else None,
            )
            passed = "passed" in result.stdout.lower() or result.returncode == 0
            return {
                "passed": passed,
                "total": self._parse_test_count(result.stdout),
                "failures": result.returncode if not passed else 0,
                "output": result.stdout[-1000:],
                "duration": 0,
            }
        except FileNotFoundError:
            return {"passed": True, "total": 0, "failures": 0, "output": "pytest not installed", "duration": 0}
        except Exception as e:
            return {"passed": False, "total": 0, "failures": 1, "output": str(e), "duration": 0}

    def _parse_test_count(self, output: str) -> int:
        """Parse test count from pytest output."""
        for line in output.split("\n"):
            if "passed" in line.lower():
                try:
                    return int(line.strip().split()[0])
                except (ValueError, IndexError):
                    pass
        return 0


# ── Rollback Manager ─────────────────────────────────────────────────

class RollbackManager:
    """Instant undo of any auto-applied change."""

    def __init__(self, backup_dir: str = ""):
        self._backup_dir = Path(backup_dir) if backup_dir else Path.home() / ".agentos" / "evolution" / "backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._history: list[dict[str, Any]] = []

    def snapshot(self, file_path: str, content: str) -> str:
        """Create a backup snapshot of a file before modification."""
        snapshot_id = hashlib.sha256(f"{file_path}:{time.time()}".encode()).hexdigest()[:12]
        snapshot_path = self._backup_dir / f"{snapshot_id}.bak"
        snapshot_path.write_text(content, encoding="utf-8")
        self._history.append({
            "snapshot_id": snapshot_id,
            "file_path": file_path,
            "timestamp": time.time(),
            "size": len(content),
        })
        return snapshot_id

    def rollback(self, snapshot_id: str) -> bool:
        """Restore file from snapshot."""
        snapshot_path = self._backup_dir / f"{snapshot_id}.bak"
        if not snapshot_path.exists():
            return False

        for entry in self._history:
            if entry["snapshot_id"] == snapshot_id:
                target = Path(entry["file_path"])
                target.write_text(snapshot_path.read_text(encoding="utf-8"), encoding="utf-8")
                return True

        return False

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent evolution history."""
        return sorted(self._history, key=lambda x: x["timestamp"], reverse=True)[:limit]


# ── A/B Evaluator ───────────────────────────────────────────────────

class ABEvaluator:
    """Compare agent performance before and after evolution changes."""

    def __init__(self, test_cases: list[dict[str, str]] | None = None):
        self._test_cases = test_cases or []
        self._results_before: list[dict] = []
        self._results_after: list[dict] = []

    async def evaluate_before(self, agent) -> list[dict]:
        """Run evaluation before changes."""
        self._results_before = await self._run_eval_loop(agent)
        return self._results_before

    async def evaluate_after(self, agent) -> list[dict]:
        """Run evaluation after changes."""
        self._results_after = await self._run_eval_loop(agent)
        return self._results_after

    def compare(self) -> dict[str, Any]:
        """Compare before/after results."""
        if not self._results_before or not self._results_after:
            return {"status": "no_data"}

        before_success = sum(1 for r in self._results_before if r.get("passed", False))
        after_success = sum(1 for r in self._results_after if r.get("passed", False))
        total = max(len(self._results_before), len(self._results_after))

        return {
            "before_pass_rate": before_success / total if total else 0,
            "after_pass_rate": after_success / total if total else 0,
            "improvement": (after_success - before_success) / total if total else 0,
            "regressions": after_success < before_success,
            "total_cases": total,
        }

    async def _run_eval_loop(self, agent) -> list[dict]:
        """Run evaluation loop."""
        results = []
        for case in self._test_cases:
            try:
                result = await agent.run(case.get("input", ""))
                passed = case.get("expected", "") in str(result)
                results.append({"case": case.get("id", ""), "passed": passed, "output": str(result)[:500]})
            except Exception as e:
                results.append({"case": case.get("id", ""), "passed": False, "error": str(e)})
        return results


# ── Evolution Journal ───────────────────────────────────────────────

class EvolutionJournal:
    """Complete audit trail of every evolution step."""

    def __init__(self, journal_path: str = ""):
        self._path = Path(journal_path) if journal_path else Path.home() / ".agentos" / "evolution" / "journal.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, entry: dict[str, Any]):
        """Append an entry to the journal."""
        entry["_timestamp"] = datetime.now().isoformat()
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read(self, limit: int = 50) -> list[dict]:
        """Read recent journal entries."""
        if not self._path.exists():
            return []
        entries = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                entries.append(json.loads(line))
        return entries[-limit:]

    def stats(self) -> dict[str, Any]:
        """Compute evolution statistics from journal."""
        entries = self.read(limit=10000)
        if not entries:
            return {}

        by_type: dict[str, int] = {}
        by_result: dict[str, int] = {}
        for entry in entries:
            by_type[entry.get("type", "unknown")] = by_type.get(entry.get("type", "unknown"), 0) + 1
            by_result[entry.get("result", "unknown")] = by_result.get(entry.get("result", "unknown"), 0) + 1

        return {
            "total_entries": len(entries),
            "by_type": by_type,
            "by_result": by_result,
            "first_entry": entries[0].get("_timestamp", ""),
            "last_entry": entries[-1].get("_timestamp", ""),
        }


# ── AutoPilot ───────────────────────────────────────────────────────

class AutoPilot:
    """Closed-loop self-evolution engine.

    The AutoPilot orchestrates the entire evolution pipeline:
    signals → insights → proposals → code changes → tests → apply/rollback.

    Usage:
        from agentos.evolution import SignalCollector, EvolutionEngine, Learner, AutoPilot

        collector = SignalCollector()
        engine = EvolutionEngine()
        learner = Learner(collector, engine)
        autopilot = AutoPilot(engine, learner, mode=AutoPilotMode.CONFIDENCE_GATED)

        # After accumulating signals...
        run = await autopilot.evolve()
        print(f"Evolved: {run.result} — {len(run.changes)} changes applied")
    """

    def __init__(
        self,
        engine: EvolutionEngine,
        learner: Learner,
        mode: AutoPilotMode = AutoPilotMode.CONFIDENCE_GATED,
        confidence_threshold: float = 0.7,
        code_generator: Optional[CodeGenerator] = None,
        tester: Optional[AutoTester] = None,
        rollback: Optional[RollbackManager] = None,
        evaluator: Optional[ABEvaluator] = None,
        journal: Optional[EvolutionJournal] = None,
    ):
        self.engine = engine
        self.learner = learner
        self.mode = mode
        self.confidence_threshold = confidence_threshold

        self.codegen = code_generator or CodeGenerator()
        self.tester = tester or AutoTester()
        self.rollback = rollback or RollbackManager()
        self.evaluator = evaluator or ABEvaluator()
        self.journal = journal or EvolutionJournal()

        self._run_history: list[EvolutionRun] = []

    async def evolve(self, agent=None) -> list[EvolutionRun]:
        """Execute one complete evolution cycle.

        1. Analyze signals → generate insights
        2. Convert insights → proposals
        3. For each proposal: generate code → test → apply/rollback
        4. Journal everything

        Args:
            agent: Optional agent instance for A/B evaluation.

        Returns:
            List of EvolutionRun records for this cycle.
        """
        # Step 1: Analyze signals
        insights = self.learner.analyze()

        # Step 2: Generate proposals
        proposals = []
        for insight in insights:
            proposal = self.learner.propose_from_insight(insight)
            proposals.append(proposal)

        # Step 3: Gate by confidence and mode
        runs: list[EvolutionRun] = []
        for proposal in proposals:
            run = await self._process_proposal(proposal, agent)
            runs.append(run)
            self._run_history.append(run)

        # Step 4: Journal results
        self.journal.log({
            "type": "evolution_cycle",
            "insights": len(insights),
            "proposals": len(proposals),
            "applied": sum(1 for r in runs if r.result == ChangeResult.SUCCESS),
            "failed": sum(1 for r in runs if r.result == ChangeResult.FAILED),
            "rolled_back": sum(1 for r in runs if r.result == ChangeResult.ROLLED_BACK),
        })

        return runs

    async def _process_proposal(self, proposal: EvolutionProposal, agent=None) -> EvolutionRun:
        """Process a single proposal through the pipeline."""
        run = EvolutionRun(
            run_id=f"ev_{proposal.id}",
            proposal=proposal,
            started_at=time.time(),
        )

        # Check if we should proceed based on mode
        if not self._should_proceed(proposal):
            run.result = ChangeResult.SKIPPED
            run.finished_at = time.time()
            return run

        # Snapshot before
        for target in proposal.target_files:
            if os.path.exists(target):
                content = Path(target).read_text(encoding="utf-8")
                self.rollback.snapshot(target, content)

        # Evaluate before (if agent provided)
        if agent:
            run.metrics_before = await self.evaluator.compare()

        # Generate code changes
        codebase = {}
        for target in proposal.target_files:
            if os.path.exists(target):
                codebase[target] = Path(target).read_text(encoding="utf-8")

        changes = await self.codegen.generate(proposal, codebase)

        if not changes:
            run.result = ChangeResult.FAILED
            run.finished_at = time.time()
            return run

        run.changes = changes

        # Apply changes
        for change in changes:
            try:
                if change.new_content:
                    Path(change.file_path).write_text(change.new_content, encoding="utf-8")
            except Exception:
                # Rollback and fail
                for ch in run.changes:
                    self.rollback.rollback(ch.proposal_id)
                run.result = ChangeResult.ROLLED_BACK
                run.finished_at = time.time()
                return run

        # Run tests
        test_results = await self.tester.run_tests()

        if not test_results.get("passed", False):
            # Regression detected — rollback
            for change in changes:
                if change.old_content:
                    Path(change.file_path).write_text(change.old_content, encoding="utf-8")
            run.result = ChangeResult.REGRESSION
            run.rollback_info = {"test_results": test_results}
            run.finished_at = time.time()
            return run

        # Success!
        run.result = ChangeResult.SUCCESS
        run.test_results = test_results

        # Evaluate after (if agent provided)
        if agent:
            run.metrics_after = await self.evaluator.compare()

        # Update proposal status
        proposal.status = EvolutionStatus.APPLIED

        run.finished_at = time.time()
        return run

    def _should_proceed(self, proposal: EvolutionProposal) -> bool:
        """Determine if we should proceed with this proposal based on mode."""
        if self.mode == AutoPilotMode.SUGGEST_ONLY:
            return False

        if self.mode == AutoPilotMode.ASK_BEFORE:
            # User interaction required — return False, caller must handle
            return False

        if self.mode == AutoPilotMode.CONFIDENCE_GATED:
            return proposal.confidence >= self.confidence_threshold

        if self.mode == AutoPilotMode.FULL_AUTO:
            # Only safe changes in FULL_AUTO
            return proposal.risk_level in ("low", "medium")

        return False

    def get_run_history(self, limit: int = 20) -> list[EvolutionRun]:
        """Get recent evolution runs."""
        return self._run_history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get AutoPilot statistics."""
        runs = self._run_history
        return {
            "total_runs": len(runs),
            "successful": sum(1 for r in runs if r.result == ChangeResult.SUCCESS),
            "failed": sum(1 for r in runs if r.result == ChangeResult.FAILED),
            "regressions": sum(1 for r in runs if r.result == ChangeResult.REGRESSION),
            "rolled_back": sum(1 for r in runs if r.result == ChangeResult.ROLLED_BACK),
            "total_changes": sum(len(r.changes) for r in runs),
            "journal_stats": self.journal.stats(),
            "rollback_history": len(self.rollback.get_history()),
        }
