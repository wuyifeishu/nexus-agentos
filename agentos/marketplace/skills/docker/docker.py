"""
docker — Docker container/image operations via CLI.

Actions: ps, images, logs, inspect, stats
"""

import subprocess
from typing import Any


def run(action: str = "ps", container: str = "", image: str = "", **kwargs: Any) -> str:
    """Docker operations.

    Args:
        action: ps | images | logs | inspect | stats | version
        container: container name/id (for logs, inspect, stats)
        image: image name/id (for inspect on images)
    """
    cmds = {
        "ps": ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
        "ps_all": ["docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
        "images": ["docker", "images", "--format", "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"],
        "version": ["docker", "version", "--format", "{{.Server.Version}}"],
    }

    if action == "logs" and container:
        return _run(["docker", "logs", "--tail", "50", container])
    if action == "inspect" and container:
        return _run(["docker", "inspect", container])
    if action == "stats":
        return _run(["docker", "stats", "--no-stream", "--all"])
    if action in cmds:
        return _run(cmds[action])

    return f"[docker] Unknown action: {action}. Available: ps, ps_all, images, logs, inspect, stats, version"


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.stdout or r.stderr or "[docker] No output."
    except FileNotFoundError:
        return "[docker] Docker not installed."
    except Exception as e:
        return f"[docker] Error: {e}"


__all__ = ["run"]
