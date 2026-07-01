"""数据处理工具 — JSON/CSV 解析、格式化、查询。"""

from __future__ import annotations

import csv
import json
import os
from io import StringIO
from typing import Any

from agentos.tools.base import BaseTool, ToolResult


class JsonTool(BaseTool):
    """JSON 处理工具 — 解析、格式化、JSONPath 查询、验证。"""

    name = "json_tool"
    description = "JSON 解析、格式化、JSONPath 查询、Schema 验证。输入 JSON 字符串或 .json 文件路径"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "操作类型：parse/format/query/validate", "enum": ["parse", "format", "query", "validate"]},
                "input": {"type": "string", "description": "JSON 字符串或 .json 文件路径"},
                "jsonpath": {"type": "string", "description": "JSONPath 查询表达式（仅 query），如 $.store.book[0].title"},
                "indent": {"type": "integer", "description": "缩进空格数，默认 2"},
            },
            "required": ["action", "input"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        action = arguments.get("action", "parse")
        input_data = arguments.get("input", "")
        jsonpath = arguments.get("jsonpath", "$")
        indent = arguments.get("indent", 2)

        # Read file if path
        if os.path.isfile(input_data):
            try:
                with open(input_data, "r", encoding="utf-8") as f:
                    data_str = f.read()
            except Exception as e:
                return ToolResult.fail(call_id="", error=f"File read error: {e}")
        else:
            data_str = input_data

        # Parse
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError as e:
            return ToolResult.fail(call_id="", error=f"JSON parse error: {e}")

        if action == "parse":
            info = f"Type: {type(data).__name__}\n"
            if isinstance(data, dict):
                info += f"Keys: {list(data.keys())[:20]}\n"
            if isinstance(data, (list, dict)):
                info += f"Length: {len(data)}\n"
            info += f"Sample: {json.dumps(data, indent=indent, ensure_ascii=False)[:1000]}"
            return ToolResult.ok(call_id="", output=info)

        elif action == "format":
            formatted = json.dumps(data, indent=indent, ensure_ascii=False)
            return ToolResult.ok(call_id="", output=formatted)

        elif action == "query":
            result = self._jsonpath_query(data, jsonpath)
            output = json.dumps(result, indent=indent, ensure_ascii=False) if result is not None else "null"
            return ToolResult.ok(call_id="", output=output)

        elif action == "validate":
            return ToolResult.ok(
                call_id="",
                output=f"Valid JSON. Type: {type(data).__name__}. "
                f"Size: {len(data_str)} chars. "
                f"{'Keys: ' + str(list(data.keys())[:20]) if isinstance(data, dict) else ''}",
            )

        return ToolResult.fail(call_id="", error=f"Unknown action: {action}")

    def _jsonpath_query(self, data: Any, path: str) -> Any:
        if path == "$":
            return data
        parts = path.replace("[", ".").replace("]", "").split(".")
        current = data
        for part in parts:
            if not part or part == "$":
                continue
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current


class CsvTool(BaseTool):
    """CSV 处理工具 — 读取、查询、统计。"""

    name = "csv_tool"
    description = "CSV 文件读取、列提取、基本统计。输入 .csv 文件路径"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "操作类型：read/stats/query", "enum": ["read", "stats", "query"]},
                "input": {"type": "string", "description": ".csv 文件路径"},
                "columns": {"type": "string", "description": "要提取的列名，逗号分隔（仅 query）"},
                "limit": {"type": "integer", "description": "最大行数，默认 50"},
            },
            "required": ["action", "input"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        action = arguments.get("action", "read")
        input_data = arguments.get("input", "")
        columns = arguments.get("columns", "")
        limit = arguments.get("limit", 50)

        # Try as file path
        if os.path.isfile(input_data):
            try:
                with open(input_data, "r", encoding="utf-8", errors="ignore") as f:
                    data_str = f.read()
            except Exception as e:
                return ToolResult.fail(call_id="", error=f"File read error: {e}")
        else:
            data_str = input_data

        try:
            reader = csv.DictReader(StringIO(data_str))
            col_names = reader.fieldnames or []
            rows = [row for i, row in enumerate(reader) if i < limit]
        except Exception as e:
            return ToolResult.fail(call_id="", error=f"CSV parse error: {e}")

        if action == "read":
            output = f"Columns: {col_names}\nRows: {len(rows)}\n\n"
            for row in rows[:20]:
                output += str(row) + "\n"
            return ToolResult.ok(call_id="", output=output)

        elif action == "stats":
            output = f"Columns: {col_names}\nTotal rows loaded: {len(rows)}\n\n"
            for col in col_names:
                values = [row[col] for row in rows if row.get(col)]
                unique = len(set(values))
                output += f"  {col}: {unique} unique values, sample={values[:3]}\n"
            return ToolResult.ok(call_id="", output=output)

        elif action == "query":
            target_cols = [c.strip() for c in columns.split(",")] if columns else col_names
            output = f"Columns: {target_cols}\n\n"
            for row in rows:
                output += ", ".join(f"{c}={row.get(c, '')}" for c in target_cols if c in row) + "\n"
            return ToolResult.ok(call_id="", output=output)

        return ToolResult.fail(call_id="", error=f"Unknown action: {action}")
