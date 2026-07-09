"""
task-manager — Local JSON-based task manager.

Actions: add, list, done, delete, clear_done, search
Data stored in ~/.agentos_tasks.json
"""

import json
import os
from datetime import datetime
from typing import Any

DB = os.path.expanduser("~/.agentos_tasks.json")


def _load():
    if not os.path.exists(DB):
        return []
    with open(DB) as f:
        return json.load(f)


def _save(tasks):
    with open(DB, "w") as f:
        json.dump(tasks, f, indent=2)


def run(action: str = "list", title: str = "", query: str = "", **kwargs: Any) -> str:
    tasks = _load()

    if action == "add":
        if not title:
            return "[task-manager] Title required for add."
        task = {
            "id": len(tasks) + 1,
            "title": title,
            "done": False,
            "created": datetime.now().isoformat()[:19],
        }
        tasks.append(task)
        _save(tasks)
        return f"[task-manager] Added: #{task['id']} {title}"

    if action == "list":
        if not tasks:
            return "[task-manager] No tasks."
        pending = [t for t in tasks if not t["done"]]
        done_list = [t for t in tasks if t["done"]]
        result = f"Tasks: {len(pending)} pending, {len(done_list)} done\n"
        for t in pending:
            result += f"  [#{t['id']}] [ ] {t['title']}\n"
        for t in done_list[-5:]:
            result += f"  [#{t['id']}] [x] {t['title']}\n"
        return result

    if action == "done":
        task_id = kwargs.get("task_id", 0) or (int(title) if title.isdigit() else 0)
        if not task_id:
            return "[task-manager] task_id required."
        for t in tasks:
            if t["id"] == task_id:
                t["done"] = True
                t["completed"] = datetime.now().isoformat()[:19]
                _save(tasks)
                return f"[task-manager] Done: #{task_id} {t['title']}"
        return f"[task-manager] Task #{task_id} not found."

    if action == "delete":
        task_id = int(title) if title.isdigit() else 0
        if not task_id:
            return "[task-manager] task_id required."
        tasks = [t for t in tasks if t["id"] != task_id]
        _save(tasks)
        return f"[task-manager] Deleted #{task_id}."

    if action == "clear_done":
        count = sum(1 for t in tasks if t["done"])
        tasks = [t for t in tasks if not t["done"]]
        _save(tasks)
        return f"[task-manager] Cleared {count} completed tasks. {len(tasks)} remaining."

    if action == "search":
        q = (title or query).lower()
        matches = [t for t in tasks if q in t["title"].lower()]
        if not matches:
            return f"[task-manager] No tasks matching '{q}'."
        return "\n".join(
            f"  [#{t['id']}] [{'x' if t['done'] else ' '}] {t['title']}" for t in matches
        )

    return f"[task-manager] Unknown action: {action}. Available: add, list, done, delete, clear_done, search"


__all__ = ["run"]
