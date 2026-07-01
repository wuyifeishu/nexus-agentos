"""
安全沙箱 — Docker隔离 + LLM操作级分析。
基因来源: OpenHands + Claude Code

v1.2.1: SandboxExecutor 提升为一级导出，提供真正的代码隔离执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agentos.security.sandbox_executor import (
    SandboxMode,
    SandboxConfig,
    SandboxResult,
    SandboxExecutor,
    ProcessSandbox,
    DockerSandbox,
)


class RiskLevel(str, Enum):
    """Safety risk classification for sandboxed operations."""
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"


@dataclass
class SafetyReport:
    """Result of a safety analysis for a sandboxed operation.

    Attributes:
        risk: Classified risk level.
        reason: Explanation of the risk assessment.
    """
    risk: RiskLevel
    reason: str


class Sandbox:
    """
    安全沙箱 — 每个Agent会话对应一个隔离环境。
    生产环境使用Docker容器，当前为本地简化实现。
    """

    def __init__(self, session_id: str, workspace: str = "/workspace"):
        self.session_id = session_id
        self.workspace = workspace
        self.allowed_paths: list[str] = [workspace]
        self.blocked_commands: list[str] = [
            "rm -rf /", "mkfs", "dd if=", "> /dev/sda",
            "shutdown", "reboot", "kill -9 1",
        ]

    def is_allowed(self, tool_name: str, arguments: dict) -> bool:
        """检查工具调用是否被允许。"""
        # 检查路径是否在允许范围内
        path = arguments.get("file_path") or arguments.get("path") or ""
        if path and not any(
            path.startswith(allowed) for allowed in self.allowed_paths
        ):
            if not path.startswith("/tmp/"):
                return False

        # 检查命令黑名单
        command = arguments.get("command") or arguments.get("code") or ""
        for blocked in self.blocked_commands:
            if blocked in command:
                return False

        return True

    async def execute_code(self, code: str, language: str = "python") -> Any:
        """在沙箱中执行代码。当前为简化实现。"""
        # 生产环境: docker exec 到容器内执行
        # 当前: subprocess（带安全检查）
        return None


class SandboxManager:
    """沙箱管理器 — 创建和销毁沙箱。"""

    def __init__(self):
        self._sandboxes: dict[str, Sandbox] = {}

    def get_sandbox(self, session_id: str) -> Sandbox:
        if session_id not in self._sandboxes:
            self._sandboxes[session_id] = Sandbox(session_id=session_id)
        return self._sandboxes[session_id]

    def destroy(self, session_id: str):
        self._sandboxes.pop(session_id, None)


class LLMSafetyAnalyzer:
    """
    操作级LLM安全分析 — 执行前用轻量模型评估风险。
    生产环境: 调用轻量模型分析每次代码执行的安全性。
    当前为规则匹配简化实现。
    """

    DANGEROUS_PATTERNS = [
        "rm -rf /", "os.system", "subprocess", "eval(", "exec(",
        "shutil.rmtree('/'", "os.remove('/",
    ]

    MODERATE_PATTERNS = [
        "rm ", "os.remove", "os.unlink", "shutil.rmtree",
        "write(", "open(", "mkdir(",
    ]

    async def analyze(self, code: str) -> SafetyReport:
        code_lower = code.lower()

        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.lower() in code_lower:
                return SafetyReport(
                    risk=RiskLevel.DANGEROUS,
                    reason=f"Blocked dangerous operation: {pattern}",
                )

        for pattern in self.MODERATE_PATTERNS:
            if pattern.lower() in code_lower:
                return SafetyReport(
                    risk=RiskLevel.MODERATE,
                    reason=f"Requires confirmation: write/delete operation detected",
                )

        return SafetyReport(risk=RiskLevel.SAFE, reason="No risky operations detected")
