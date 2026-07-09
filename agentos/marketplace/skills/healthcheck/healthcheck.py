"""
healthcheck — System health checks.

Actions: disk, memory, cpu, uptime, processes, all
"""

import shutil
import subprocess
from typing import Any


def run(action: str = "all", **kwargs: Any) -> str:
    results = []

    if action in ("disk", "all"):
        usage = shutil.disk_usage("/")
        pct = usage.used / usage.total * 100
        results.append(f"Disk: {usage.used//(1024**3)}GB / {usage.total//(1024**3)}GB ({pct:.1f}%)")

    if action in ("memory", "all"):
        try:
            r = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
            mem_line = [ln for ln in r.stdout.split("\n") if "Mem:" in ln]
            if mem_line:
                results.append(f"Memory: {mem_line[0].split()[1]}/{mem_line[0].split()[2]}")
        except Exception:
            results.append("Memory: unavailable")

    if action in ("cpu", "all"):
        try:
            r = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5)
            load = r.stdout.strip().split("load average:")[-1].strip() if r.stdout else "unknown"
            results.append(f"CPU Load: {load}")
        except Exception:
            results.append("CPU: unavailable")

    if action in ("uptime", "all"):
        try:
            r = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=5)
            results.append(f"Uptime: {r.stdout.strip()}")
        except Exception:
            results.append("Uptime: unavailable")

    if action in ("processes", "all"):
        try:
            r = subprocess.run(
                ["ps", "aux", "--no-headers"], capture_output=True, text=True, timeout=5
            )
            count = len([ln for ln in r.stdout.split("\n") if ln.strip()])
            results.append(f"Processes: {count}")
        except Exception:
            results.append("Processes: unavailable")

    if action not in ("disk", "memory", "cpu", "uptime", "processes", "all"):
        return f"[healthcheck] Unknown action: {action}"

    return "\n".join(results) if results else "[healthcheck] No checks performed."


__all__ = ["run"]
