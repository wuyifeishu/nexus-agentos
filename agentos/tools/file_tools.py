"""
文件操作工具集。
"""

from __future__ import annotations

import os
import aiofiles

from agentos.tools.base import BaseTool, PermissionLevel, ToolResult


class ReadFileTool(BaseTool):

    """文件读取工具。"""

    name = "read_file"
    description = "读取文件内容，返回全部文本。"
    permission_level = PermissionLevel.SAFE

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "要读取的文件绝对路径",
                },
            },
            "required": ["file_path"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        file_path = arguments["file_path"]
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            return ToolResult.ok("", output=content)
        except FileNotFoundError:
            return ToolResult.fail("", error=f"File not found: {file_path}")
        except PermissionError:
            return ToolResult.fail("", error=f"Permission denied: {file_path}")
        except Exception as e:
            return ToolResult.fail("", error=str(e))


class WriteFileTool(BaseTool):

    """文件写入工具。"""

    name = "write_file"
    description = "写入文本内容到文件。如果文件已存在则覆盖。"
    permission_level = PermissionLevel.MODERATE

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "要写入的文件路径"},
                "content": {"type": "string", "description": "要写入的文本内容"},
            },
            "required": ["file_path", "content"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        file_path = arguments["file_path"]
        content = arguments["content"]
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)
            return ToolResult.ok("", output=f"Written {len(content)} bytes to {file_path}")
        except Exception as e:
            return ToolResult.fail("", error=str(e))

    def is_write_operation(self, arguments: dict) -> bool:
        return True


class ListDirectoryTool(BaseTool):

    """目录列表工具。"""

    name = "list_directory"
    description = "列出目录下的所有文件和子目录。"
    permission_level = PermissionLevel.SAFE

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要列出的目录路径"},
            },
            "required": ["path"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        path = arguments["path"]
        try:
            entries = os.listdir(path)
            lines = []
            for entry in sorted(entries):
                full_path = os.path.join(path, entry)
                tag = "[DIR]" if os.path.isdir(full_path) else "[FILE]"
                size = os.path.getsize(full_path) if os.path.isfile(full_path) else 0
                lines.append(f"{tag} {entry} ({size} bytes)")
            return ToolResult.ok("", output="\n".join(lines))
        except FileNotFoundError:
            return ToolResult.fail("", error=f"Directory not found: {path}")
        except Exception as e:
            return ToolResult.fail("", error=str(e))
