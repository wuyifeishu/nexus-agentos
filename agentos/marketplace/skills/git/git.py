"""
git — Git version control operations.

Actions: status, log, branch, diff, commit (dry-run)
"""

import subprocess
from typing import Any


def run(action: str = "status", repo_path: str = ".", message: str = "", **kwargs: Any) -> str:
    actions = {
        "status": ["git", "-C", repo_path, "status", "--short"],
        "log": ["git", "-C", repo_path, "log", "--oneline", "-20"],
        "branch": ["git", "-C", repo_path, "branch", "--all"],
        "diff": ["git", "-C", repo_path, "diff", "--stat"],
        "diff_unstaged": ["git", "-C", repo_path, "diff", "--stat", "HEAD"],
        "remote": ["git", "-C", repo_path, "remote", "-v"],
        "stash_list": ["git", "-C", repo_path, "stash", "list"],
    }

    if action == "commit_dry_run":
        stat = _run(["git", "-C", repo_path, "diff", "--cached", "--stat"])
        if not stat.strip():
            return "[git] No staged changes to commit."
        return f"[git] Would commit with message: '{message or '(empty)'}'\nStaged changes:\n{stat}"
    if action not in actions:
        return f"[git] Unknown action: {action}. Available: {', '.join(actions.keys())}, commit_dry_run"

    return _run(actions[action])


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.stdout or r.stderr or "[git] No output."
    except FileNotFoundError:
        return "[git] Git not installed."
    except Exception as e:
        return f"[git] Error: {e}"


__all__ = ["run"]
