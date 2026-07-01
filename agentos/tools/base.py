"""
工具基类 — 所有工具的抽象父类。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PermissionLevel(str, Enum):
    """工具权限等级。"""

    SAFE = "safe"
    MODERATE = "moderate"
    SENSITIVE = "sensitive"


@dataclass
class ToolCall:
    """工具调用请求。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """工具调用返回结果。"""

    call_id: str
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None

    @classmethod
    def ok(cls, call_id: str, output: str) -> "ToolResult":
        return cls(call_id=call_id, output=output)

    @classmethod
    def fail(cls, call_id: str, error: str) -> "ToolResult":
        return cls(call_id=call_id, error=error)


class BaseTool(ABC):
    """工具基类 — 所有工具必须实现的接口。"""

    name: str = ""
    description: str = ""
    permission_level: PermissionLevel = PermissionLevel.MODERATE
    concurrent_safe: bool = True  # 是否可与其他工具并行执行

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """返回OpenAI function calling格式的参数schema。"""

    @abstractmethod
    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        """执行工具。"""

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def is_write_operation(self, arguments: dict) -> bool:
        """是否为写操作（用于读写冲突检测）。默认False。"""
        return False

    def is_read_operation(self, arguments: dict) -> bool:
        """是否为读操作。默认True。"""
        return True

    def extract_target_path(self, arguments: dict) -> str | None:
        """提取操作的目标路径（用于冲突检测）。默认None。"""
        return arguments.get("file_path") or arguments.get("path")
