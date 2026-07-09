"""
spreadsheet — CSV-based spreadsheet operations.

Actions: read, filter, sort, aggregate, columns
Lightweight CSV manipulation without pandas.
"""

import csv
import os
from typing import Any


def run(
    action: str = "read",
    file_path: str = "",
    column: str = "",
    condition: str = "",
    sort_by: str = "",
    aggregate: str = "",
    delimiter: str = ",",
    **kwargs: Any,
) -> str:
    if not file_path or not os.path.exists(file_path):
        return f"[spreadsheet] File not found: {file_path}"

    try:
        with open(file_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            rows = list(reader)
    except Exception as e:
        return f"[spreadsheet] Read error: {e}"

    headers = reader.fieldnames or []

    if action == "columns":
        return f"Columns ({len(headers)}): {', '.join(headers)}"

    if action == "read":
        return _format(rows[:20], headers)

    if action == "filter":
        if not column or column not in headers:
            return f"[spreadsheet] Column '{column}' not found. Available: {headers}"
        filtered = [r for r in rows if condition.lower() in r.get(column, "").lower()]
        return _format(filtered[:30], headers)

    if action == "sort":
        if not sort_by or sort_by not in headers:
            return f"[spreadsheet] Column '{sort_by}' not found."
        descending = kwargs.get("desc", False)
        sorted_rows = sorted(rows, key=lambda r: r.get(sort_by, ""), reverse=descending)
        return _format(sorted_rows[:30], headers)

    if action == "aggregate":
        if column not in headers:
            return f"[spreadsheet] Column '{column}' not found."
        values = []
        for r in rows:
            try:
                values.append(float(r.get(column, 0)))
            except (ValueError, TypeError):
                pass
        if not values:
            return f"[spreadsheet] No numeric values in '{column}'."
        if aggregate == "sum":
            return f"Sum of {column}: {sum(values)}"
        if aggregate == "avg":
            return f"Average of {column}: {sum(values)/len(values):.2f}"
        if aggregate == "min":
            return f"Min of {column}: {min(values)}"
        if aggregate == "max":
            return f"Max of {column}: {max(values)}"
        if aggregate == "count":
            return f"Count of {column}: {len(values)}"
        return f"Sum: {sum(values)}, Avg: {sum(values)/len(values):.2f}, Min: {min(values)}, Max: {max(values)}, Count: {len(values)}"  # noqa: E501

    return (
        f"[spreadsheet] Unknown action: {action}. Available: read, filter, sort, aggregate, columns"
    )


def _format(rows, headers):
    if not rows:
        return "[spreadsheet] No matching rows."
    result = "\t".join(headers) + "\n"
    result += "\n".join("\t".join(str(r.get(h, "")) for h in headers) for r in rows)
    return result


__all__ = ["run"]
