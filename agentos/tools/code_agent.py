"""
CodeAgent 工具 — Agent直接写代码执行，不输出JSON。
基因来源: Smolagents
核心洞察: 代码的表达力远超JSON（循环/条件/异常/变量作用域）。
"""

from __future__ import annotations

import subprocess

from agentos.tools.base import BaseTool, PermissionLevel, ToolResult


class CodeAgentTool(BaseTool):
    """代码执行工具 — Agent不输出JSON，直接写Python代码。"""

    name = "execute_code"
    description = (
        "执行Python代码并返回结果。支持任意Python标准库。"
        "适用场景：数据处理、文件列表、字符串操作、复杂逻辑。"
        "返回值包含stdout/stderr/exit_code。"
    )
    permission_level = PermissionLevel.SENSITIVE

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "要执行的Python代码",
                },
            },
            "required": ["code"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        code = arguments["code"]

        # 如果传入了sandbox则在沙箱中执行
        if sandbox:
            return await sandbox.execute_code(code, "python")

        # 默认在当前进程执行（Python环境）
        try:
            result = subprocess.run(
                ["python3", "-c", code],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return ToolResult(
                call_id="",
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(call_id="", error="Code execution timed out (60s)")
        except Exception as e:
            return ToolResult(call_id="", error=str(e))

    def is_write_operation(self, arguments: dict) -> bool:
        code = arguments.get("code", "")
        write_keywords = ("open(", "write(", "mkdir(", "remove(", "shutil.rmtree")
        return any(kw in code for kw in write_keywords)


class ShellTool(BaseTool):
    """Shell命令执行工具。"""

    name = "shell"
    description = "执行Shell命令并返回结果。用于文件操作、系统查询等。"
    permission_level = PermissionLevel.SENSITIVE

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的Shell命令",
                },
            },
            "required": ["command"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        command = arguments["command"]

        if sandbox:
            return await sandbox.execute_code(command, "shell")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return ToolResult(
                call_id="",
                output=result.stdout or result.stderr,
                error=None if result.returncode == 0 else result.stderr,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(call_id="", error="Command timed out (30s)")
        except Exception as e:
            return ToolResult(call_id="", error=str(e))

    def is_write_operation(self, arguments: dict) -> bool:
        cmd = arguments.get("command", "")
        write_keywords = ("rm ", "rmdir", "mv ", "cp ", "touch ", "mkdir ", ">")
        return any(kw in cmd for kw in write_keywords)
