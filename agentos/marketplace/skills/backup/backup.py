"""
backup — Simple file/directory backup utility.

Actions: backup, list_backups, restore_latest
Creates timestamped .tar.gz archives.
"""

import glob
import os
import shutil
from datetime import datetime
from typing import Any

BACKUP_DIR = os.path.expanduser("~/.agentos_backups")


def run(action: str = "backup", source: str = "", target_name: str = "", **kwargs: Any) -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)

    if action == "list_backups":
        files = sorted(glob.glob(os.path.join(BACKUP_DIR, "*.tar.gz")), reverse=True)
        if not files:
            return "[backup] No backups found."
        result = f"Backups ({len(files)}):\n"
        for f in files[:20]:
            name = os.path.basename(f)
            size = os.path.getsize(f)
            result += f"  {name} ({size/1024:.1f} KB)\n"
        return result

    if action == "backup":
        if not source:
            return "[backup] Source path required."
        if not os.path.exists(source):
            return f"[backup] Source not found: {source}"

        base_name = target_name or os.path.basename(source.rstrip("/\\"))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{base_name}_{ts}"
        archive_path = os.path.join(BACKUP_DIR, archive_name)

        try:
            shutil.make_archive(
                archive_path, "gztar", os.path.dirname(source), os.path.basename(source)
            )
            final_path = archive_path + ".tar.gz"
            size = os.path.getsize(final_path)
            return f"[backup] Created: {os.path.basename(final_path)} ({size/1024:.1f} KB)"
        except Exception as e:
            return f"[backup] Error: {e}"

    if action == "restore_latest":
        if not source:
            return "[backup] Destination path required for restore."
        files = sorted(glob.glob(os.path.join(BACKUP_DIR, "*.tar.gz")), reverse=True)
        if not files:
            return "[backup] No backups to restore."
        latest = files[0]
        try:
            shutil.unpack_archive(latest, source)
            return f"[backup] Restored {os.path.basename(latest)} to {source}"
        except Exception as e:
            return f"[backup] Restore error: {e}"

    return f"[backup] Unknown action: {action}. Available: backup, list_backups, restore_latest"


__all__ = ["run"]
