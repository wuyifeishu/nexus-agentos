"""
Version Rollback — Safe rollback to any previous version.

Keeps a local archive of all pushed wheels (.agentos/wheels/)
and provides CLI for instant rollback.

Usage:
    agentos rollback 1.7.4          # Rollback to 1.7.4
    agentos rollback --list         # List available versions
    agentos rollback --verify 1.7.5 # Verify a version's wheel integrity
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# ── Models ──


@dataclass
class VersionEntry:
    """Record of a pushed version."""

    version: str
    pushed_at: str
    wheel_path: str
    wheel_size: int
    sha256: str
    active: bool = True  # False if rolled back from

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "pushed_at": self.pushed_at,
            "wheel_path": self.wheel_path,
            "wheel_size": self.wheel_size,
            "sha256": self.sha256,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, d: dict) -> VersionEntry:
        return cls(**d)


# ── Rollback Manager ──


class RollbackManager:
    """Safe version rollback with local wheel archive.

    Archive: ~/.agentos/rollback/
      ├── history.json         # Version records
      └── wheels/              # Archived .whl files
          ├── nexus_agentos-1.7.4-py3-none-any.whl
          └── nexus_agentos-1.7.5-py3-none-any.whl
    """

    def __init__(self, archive_dir: str = ""):
        self._root = Path(archive_dir) if archive_dir else Path.home() / ".agentos" / "rollback"
        self._history_path = self._root / "history.json"
        self._wheels_dir = self._root / "wheels"
        self._root.mkdir(parents=True, exist_ok=True)
        self._wheels_dir.mkdir(parents=True, exist_ok=True)

        self._history: list[VersionEntry] = self._load_history()

    # ── Archive ──

    def archive(self, wheel_path: str | Path) -> VersionEntry:
        """Archive a wheel after pushing to PyPI. Call after twine upload."""
        src = Path(wheel_path)
        if not src.exists():
            raise FileNotFoundError(f"Wheel not found: {src}")

        # Parse version from filename
        filename = src.name
        version = self._parse_version(filename)
        if not version:
            raise ValueError(f"Cannot parse version from {filename}")

        # Copy to archive
        dest = self._wheels_dir / filename
        import shutil

        shutil.copy2(src, dest)

        # Compute hash
        sha = hashlib.sha256(dest.read_bytes()).hexdigest()
        pushed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        entry = VersionEntry(
            version=version,
            pushed_at=pushed_at,
            wheel_path=str(dest),
            wheel_size=dest.stat().st_size,
            sha256=sha,
            active=True,
        )

        # Update history
        self._history.append(entry)
        self._save_history()

        return entry

    # ── Rollback ──

    def rollback(self, target_version: str, dry_run: bool = False) -> bool:
        """Rollback to a previously archived version.

        Steps:
          1. Find the target version's wheel in archive
          2. Verify SHA256 integrity
          3. pip install the archived wheel
          4. Mark current as inactive, target as active

        Args:
            target_version: e.g. '1.7.3' or '1.7.4'
            dry_run: If True, validate only, don't install.

        Returns:
            True if rollback succeeded (or would succeed in dry_run).
        """
        # Find target
        target = None
        for entry in self._history:
            if entry.version == target_version and entry.active is False:
                target = entry
            elif entry.version == target_version and Path(entry.wheel_path).exists():
                target = entry

        if not target:
            available = [e.version for e in self._history if Path(e.wheel_path).exists()]
            print(f"Version {target_version} not found in archive. Available: {available}")
            return False

        # Verify integrity
        wheel = Path(target.wheel_path)
        if not wheel.exists():
            print(f"Wheel file missing: {target.wheel_path}")
            return False

        actual_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if actual_sha != target.sha256:
            print(f"SHA256 mismatch! Expected: {target.sha256[:16]}..., Got: {actual_sha[:16]}...")
            return False

        current_version = self._get_installed_version()

        print(f"Rollback: {current_version} → {target_version}")
        print(f"  Wheel: {wheel}")
        print(f"  SHA256: {target.sha256[:16]}... (verified)")
        print(f"  Size: {target.wheel_size / 1024:.0f} KB")

        if dry_run:
            print("  [DRY RUN — no changes made]")
            return True

        # pip install
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(wheel)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"pip install failed:\n{result.stderr}")
            return False

        # Mark current as inactive
        for entry in self._history:
            if entry.version == current_version:
                entry.active = False

        # Mark target as active
        target.active = True
        self._save_history()

        new_version = self._get_installed_version()
        print(f"Rollback successful: {current_version} → {new_version}")
        return True

    # ── List ──

    def list_versions(self) -> list[dict]:
        """List all archived versions with status."""
        installed = self._get_installed_version()
        result = []
        for entry in sorted(self._history, key=lambda e: e.pushed_at, reverse=True):
            result.append(
                {
                    "version": entry.version,
                    "pushed_at": entry.pushed_at,
                    "wheel_size_kb": entry.wheel_size // 1024,
                    "active": entry.active,
                    "current": entry.version == installed,
                    "wheel_exists": Path(entry.wheel_path).exists(),
                }
            )
        return result

    def list_pypi_versions(self) -> list[str]:
        """List all versions available on PyPI."""
        import json
        import urllib.request

        try:
            url = "https://pypi.org/pypi/nexus-agentos/json"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return sorted(data.get("releases", {}).keys(), reverse=True)
        except Exception:
            return []

    # ── Verify ──

    def verify(self, version: str = "") -> dict:
        """Verify a specific version's wheel integrity, or all."""
        results = {}
        entries = [e for e in self._history if e.version == version] if version else self._history

        pyapi_versions = self.list_pypi_versions()

        for entry in entries:
            wheel = Path(entry.wheel_path)
            issues = []

            if not wheel.exists():
                issues.append("wheel file missing")
            else:
                actual_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
                if actual_sha != entry.sha256:
                    issues.append("SHA256 mismatch")

            if entry.version not in pyapi_versions:
                issues.append("not on PyPI")

            results[entry.version] = {
                "sha256_ok": not any("sha256" in i.lower() for i in issues),
                "wheel_exists": wheel.exists(),
                "on_pypi": entry.version in pyapi_versions,
                "issues": issues,
            }

        return results

    # ── Clean ──

    def prune(self, keep_versions: int = 5) -> list[str]:
        """Remove old wheel files, keeping the N most recent."""
        removed = []
        entries = sorted(self._history, key=lambda e: e.pushed_at, reverse=True)
        for entry in entries[keep_versions:]:
            wheel = Path(entry.wheel_path)
            if wheel.exists():
                wheel.unlink()
                removed.append(entry.version)
        self._history = entries[:keep_versions]
        self._save_history()
        return removed

    # ── Internal ──

    def _load_history(self) -> list[VersionEntry]:
        if self._history_path.exists():
            try:
                data = json.loads(self._history_path.read_text())
                return [VersionEntry.from_dict(d) for d in data]
            except (json.JSONDecodeError, KeyError):
                pass
        return []

    def _save_history(self) -> None:
        self._history_path.write_text(
            json.dumps([e.to_dict() for e in self._history], indent=2, ensure_ascii=False)
        )

    @staticmethod
    def _parse_version(filename: str) -> str:
        """Extract version from wheel filename: nexus_agentos-1.7.5-py3-none-any.whl → 1.7.5"""
        parts = filename.replace(".whl", "").split("-")
        if len(parts) >= 2:
            return parts[1].replace(".post", ".")  # Normalize .postN suffix
        return ""

    @staticmethod
    def _get_installed_version() -> str:
        try:
            import agentos

            return agentos.__version__
        except Exception:
            return "unknown"


# ── CLI Entry ──


def rollback_cli(args: list[str]) -> int:
    """CLI entry for agentos rollback command.

    Usage:
        agentos rollback 1.7.4          # Rollback
        agentos rollback --list         # List versions
        agentos rollback --verify       # Verify all
        agentos rollback --verify 1.7.5 # Verify one
        agentos rollback --prune        # Keep last 5 versions
        agentos rollback --archive dist/nexus_agentos-1.7.5-py3-none-any.whl
    """
    mgr = RollbackManager()

    if "--list" in args:
        versions = mgr.list_versions()
        if not versions:
            print("No versions in rollback archive. Archive a wheel first.")
            return 0
        print(f"{'Version':<12} {'Pushed':<22} {'Size':>8} {'Status':<10} {'On PyPI'}")
        print("-" * 70)
        for v in versions:
            status = "✓ current" if v["current"] else "  active" if v["active"] else "  inactive"
            size = f"{v['wheel_size_kb']} KB"
            pypi = "✓" if v.get("on_pypi", True) else ""
            print(f"  {v['version']:<10} {v['pushed_at']:<22} {size:>8} {status:<10} {pypi:^6}")
        return 0

    if "--verify" in args:
        idx = args.index("--verify")
        target = args[idx + 1] if idx + 1 < len(args) else ""
        results = mgr.verify(target)
        for ver, r in results.items():
            ok = "✓" if not r["issues"] else "✗"
            issues = ", ".join(r["issues"]) if r["issues"] else "clean"
            print(f"  {ok} {ver}: {issues}")
        return 0 if all(not r["issues"] for r in results.values()) else 1

    if "--prune" in args:
        removed = mgr.prune()
        print(f"Pruned {len(removed)} old wheels: {removed}")
        return 0

    if "--archive" in args:
        idx = args.index("--archive")
        wheel = args[idx + 1] if idx + 1 < len(args) else ""
        if not wheel:
            print("Usage: agentos rollback --archive <wheel_path>")
            return 1
        entry = mgr.archive(wheel)
        print(f"Archived: {entry.version} ({entry.wheel_size / 1024:.0f} KB)")
        return 0

    # Default: rollback
    if not args:
        print("Usage: agentos rollback <version> [--list|--verify|--prune|--archive]")
        return 1

    target = args[0]
    success = mgr.rollback(target)
    return 0 if success else 1
