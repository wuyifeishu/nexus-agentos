"""搜索工具 — 文件内容搜索、文件名匹配、代码符号搜索。"""

from __future__ import annotations

import fnmatch
import os
import re

from agentos.tools.base import BaseTool, ToolResult


class GrepTool(BaseTool):
    """文件内容搜索工具 — 在目录中递归搜索匹配文本。"""

    name = "grep"
    description = "在目录中递归搜索文件内容，支持正则表达式，返回匹配路径和行号"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索的文本或正则表达式"},
                "directory": {"type": "string", "description": "搜索目录，默认当前目录"},
                "file_pattern": {"type": "string", "description": "文件名匹配模式，如 *.py"},
                "max_results": {"type": "integer", "description": "最大结果数，默认 50"},
                "case_sensitive": {"type": "boolean", "description": "是否区分大小写，默认 true"},
            },
            "required": ["pattern"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        pattern = arguments.get("pattern", "")
        directory = arguments.get("directory", ".")
        file_pattern = arguments.get("file_pattern", "*")
        max_results = arguments.get("max_results", 50)
        case_sensitive = arguments.get("case_sensitive", True)

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult.fail(call_id="", error=f"Invalid regex: {e}")

        results = []
        for root, dirs, files in os.walk(os.path.abspath(directory)):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", "__pycache__", "dist", "build", ".git")
            ]
            for filename in files:
                if not fnmatch.fnmatch(filename, file_pattern):
                    continue
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, encoding="utf-8", errors="ignore") as f:
                        for lineno, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append(f"{filepath}:{lineno}: {line.strip()[:200]}")
                                if len(results) >= max_results:
                                    return ToolResult.ok(call_id="", output="\n".join(results))
                except (PermissionError, IsADirectoryError, UnicodeDecodeError):
                    continue

        return ToolResult.ok(
            call_id="", output="\n".join(results) if results else "No matches found"
        )


class FileSearchTool(BaseTool):
    """文件搜索工具 — 按文件名模式搜索。"""

    name = "file_search"
    description = "按文件名模式搜索文件，支持 glob 通配符，返回匹配的文件路径列表"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "文件名匹配模式，如 *.py, report*.pdf",
                },
                "directory": {"type": "string", "description": "搜索目录，默认当前目录"},
                "max_results": {"type": "integer", "description": "最大结果数，默认 100"},
            },
            "required": ["pattern"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        pattern = arguments.get("pattern", "")
        directory = arguments.get("directory", ".")
        max_results = arguments.get("max_results", 100)

        results = []
        for root, dirs, files in os.walk(os.path.abspath(directory)):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", "__pycache__", "dist", "build", ".git")
            ]
            for filename in files:
                if fnmatch.fnmatch(filename, pattern):
                    results.append(os.path.join(root, filename))
                    if len(results) >= max_results:
                        return ToolResult.ok(call_id="", output="\n".join(results))

        return ToolResult.ok(call_id="", output="\n".join(results) if results else "No files found")


class CodeSearchTool(BaseTool):
    """代码符号搜索工具 — 搜索函数/类/导入定义（基于 AST）。"""

    name = "code_search"
    description = "在 Python 代码中搜索函数定义、类定义、导入等符号，返回符号名和位置"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索的函数名或类名"},
                "directory": {"type": "string", "description": "代码目录，默认当前目录"},
                "symbol_type": {
                    "type": "string",
                    "description": "符号类型：function/class/import/all，默认 all",
                },
                "max_results": {"type": "integer", "description": "最大结果数，默认 30"},
            },
            "required": ["query"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        import ast

        query = arguments.get("query", "")
        directory = arguments.get("directory", ".")
        symbol_type = arguments.get("symbol_type", "all")
        max_results = arguments.get("max_results", 30)

        results = []
        for root, dirs, files in os.walk(os.path.abspath(directory)):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", "__pycache__", "dist", "build", ".git")
            ]
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, encoding="utf-8", errors="ignore") as f:
                        source = f.read()
                    tree = ast.parse(source, filename=filepath)
                    for node in ast.walk(tree):
                        if len(results) >= max_results:
                            break
                        name = None
                        stype = None
                        if isinstance(node, ast.FunctionDef) and symbol_type in ("function", "all"):
                            name, stype = node.name, "function"
                        elif isinstance(node, ast.AsyncFunctionDef) and symbol_type in (
                            "function",
                            "all",
                        ):
                            name, stype = node.name, "async_function"
                        elif isinstance(node, ast.ClassDef) and symbol_type in ("class", "all"):
                            name, stype = node.name, "class"
                        elif isinstance(node, ast.Import) and symbol_type in ("import", "all"):
                            for alias in node.names:
                                if query.lower() in alias.name.lower():
                                    results.append(f"{filepath}:{node.lineno}: import {alias.name}")
                        elif isinstance(node, ast.ImportFrom) and symbol_type in ("import", "all"):
                            if query.lower() in (node.module or "").lower():
                                results.append(
                                    f"{filepath}:{node.lineno}: from {node.module} import ..."
                                )

                        if name and stype and query.lower() in name.lower():
                            results.append(f"{filepath}:{node.lineno}: [{stype}] {name}")
                except (SyntaxError, UnicodeDecodeError, PermissionError):
                    continue

        return ToolResult.ok(
            call_id="", output="\n".join(results) if results else "No symbols found"
        )
