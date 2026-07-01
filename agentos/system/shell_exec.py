"""
Shell 执行模块 — 带权限检查和安全沙箱的命令执行。

分层策略:
- SHELL_READONLY:  只允许预定义安全命令白名单
- SHELL_STANDARD:  允许任意命令，超时+沙箱目录限制
- SHELL_FULL:      无限制（需二次确认）
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import shlex
from dataclasses import dataclass, field
from typing import Optional

from agentos.system.permissions import (
    SystemPermissionManager,
    PermissionTier,
    PermissionDenied,
)


# ── Shell 策略 ─────────────────────────────────────────────────


@dataclass
class ShellPolicy:
    """Shell 执行策略。"""
    allowed_commands: list[str] = field(default_factory=list)   # 命令白名单
    blocked_commands: list[str] = field(default_factory=list)   # 命令黑名单
    blocked_patterns: list[str] = field(default_factory=list)   # 参数黑名单模式
    timeout_seconds: int = 30                                    # 超时时间
    max_output_bytes: int = 1024 * 100                           # 最大输出字节
    sandbox_dir: str = ""                                        # 沙箱工作目录
    allow_pipes: bool = False                                    # 是否允许管道
    allow_redirects: bool = False                                # 是否允许重定向


@dataclass
class ShellResult:
    """Shell 执行结果。"""
    success: bool
    command: str
    stdout: str
    stderr: str
    exit_code: int = -1
    duration_ms: float = 0
    timeout: bool = False
    permission_denied: bool = False
    error: str = ""


# ── 预设策略 ───────────────────────────────────────────────────

READONLY_POLICY = ShellPolicy(
    allowed_commands=[
        "ls", "cat", "head", "tail", "find", "ps", "df", "du",
        "whoami", "pwd", "env", "echo", "date", "wc", "stat",
        "file", "which", "uname", "uptime", "id", "groups",
        "free", "top", "grep", "awk", "sed", "sort", "uniq",
        "cut", "tr", "tee", "xargs", "basename", "dirname",
        "readlink", "realpath", "md5sum", "sha256sum", "diff",
        "curl", "wget", "ping", "hostname", "ip", "ss",
        "python3", "python", "pip", "pip3", "git", "node", "npm",
    ],
    timeout_seconds=30,
    allow_pipes=True,
    allow_redirects=False,
)

STANDARD_POLICY = ShellPolicy(
    blocked_commands=[
        "rm", "shutdown", "reboot", "halt", "poweroff",
        "mkfs", "dd", "fdisk", "parted", "mount", "umount",
        "chmod", "chown", "useradd", "userdel", "passwd",
        "iptables", "ufw", "systemctl", "service",
    ],
    blocked_patterns=[
        r"rm\s+(-rf?|--recursive)\s+/",     # rm -rf /
        r">\s*/dev/",                          # 覆盖设备
        r"mkfs\.",                            # 格式化
        r"dd\s+if=",                          # dd 操作
        r"curl.*\|.*sh",                      # curl pipe sh
        r"wget.*\|.*sh",                      # wget pipe sh
        r">\s*/etc/",                         # 写入 /etc/
    ],
    timeout_seconds=60,
    max_output_bytes=1024 * 500,
    allow_pipes=True,
    allow_redirects=True,
)

FULL_POLICY = ShellPolicy(
    timeout_seconds=300,
    max_output_bytes=1024 * 1024 * 10,
    allow_pipes=True,
    allow_redirects=True,
)


# ── Shell 沙箱 ─────────────────────────────────────────────────


class ShellSandbox:
    """Shell 沙箱 — 隔离命令执行环境。

    特性:
    - 临时工作目录隔离
    - 环境变量过滤（移除敏感变量）
    - 资源限制（超时、输出大小）
    - 进程组管理（确保超时时子进程也被杀死）
    """

    def __init__(self, work_dir: str | None = None):
        self._work_dir = work_dir or tempfile.mkdtemp(prefix="agentos_shell_")

    @property
    def work_dir(self) -> str:
        return self._work_dir

    def filtered_env(self) -> dict[str, str]:
        """返回过滤后的环境变量（移除敏感变量）。"""
        blocked = {"AWS_", "SECRET_", "TOKEN", "PASSWORD", "PASSWD",
                    "KEY", "CREDENTIAL", "PRIVATE", "CERT", "AUTH"}
        env = {}
        for k, v in os.environ.items():
            if not any(b in k.upper() for b in blocked):
                env[k] = v
        # 设置安全默认值
        env["HOME"] = self._work_dir
        env["PATH"] = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        return env

    def cleanup(self) -> None:
        """清理沙箱目录。"""
        import shutil
        try:
            shutil.rmtree(self._work_dir, ignore_errors=True)
        except Exception:
            pass


# ── Shell 执行器 ────────────────────────────────────────────────


class ShellExecutor:
    """Shell 执行器 — 带策略和权限检查的命令执行。"""

    def __init__(self, perm_manager: SystemPermissionManager, session_id: str):
        self._pm = perm_manager
        self._sid = session_id
        self._sandboxes: dict[str, ShellSandbox] = {}

    # ── 沙箱管理 ──

    def create_sandbox(self, name: str = "default") -> ShellSandbox:
        """创建命名沙箱。"""
        sb = ShellSandbox()
        self._sandboxes[name] = sb
        return sb

    def get_sandbox(self, name: str = "default") -> ShellSandbox:
        """获取或创建沙箱。"""
        if name not in self._sandboxes:
            return self.create_sandbox(name)
        return self._sandboxes[name]

    def cleanup_sandbox(self, name: str = "default") -> None:
        """清理指定沙箱。"""
        sb = self._sandboxes.pop(name, None)
        if sb:
            sb.cleanup()

    def cleanup_all(self) -> None:
        for sb in list(self._sandboxes.values()):
            sb.cleanup()
        self._sandboxes.clear()

    # ── 命令执行 ──

    def execute(self, command: str, sandbox_name: str = "default") -> ShellResult:
        """执行 Shell 命令，自动选择策略。"""
        # 选择策略
        try:
            self._pm.require(self._sid, PermissionTier.SHELL_FULL, command)
            policy = FULL_POLICY
            tier = PermissionTier.SHELL_FULL
        except PermissionDenied:
            try:
                self._pm.require(self._sid, PermissionTier.SHELL_STANDARD, command)
                policy = STANDARD_POLICY
                tier = PermissionTier.SHELL_STANDARD
            except PermissionDenied:
                try:
                    self._pm.require(self._sid, PermissionTier.SHELL_READONLY, command)
                    policy = READONLY_POLICY
                    tier = PermissionTier.SHELL_READONLY
                except PermissionDenied as e:
                    return ShellResult(
                        success=False, command=command,
                        stdout="", stderr="", permission_denied=True, error=str(e),
                    )

        return self._execute_with_policy(command, policy, sandbox_name)

    def execute_checked(self, command: str, required_tier: PermissionTier,
                        sandbox_name: str = "default") -> ShellResult:
        """以指定权限级别执行命令。"""
        self._pm.require(self._sid, required_tier, command)
        if required_tier == PermissionTier.SHELL_READONLY:
            policy = READONLY_POLICY
        elif required_tier == PermissionTier.SHELL_STANDARD:
            policy = STANDARD_POLICY
        else:
            policy = FULL_POLICY
        return self._execute_with_policy(command, policy, sandbox_name)

    # ── 内部实现 ──

    def _execute_with_policy(self, command: str, policy: ShellPolicy,
                              sandbox_name: str) -> ShellResult:
        """按策略执行命令。"""
        import time

        # 安全检查
        safety_check = self._safety_check(command, policy)
        if safety_check:
            return ShellResult(
                success=False, command=command,
                stdout="", stderr=safety_check, error=safety_check,
            )

        sandbox = self.get_sandbox(sandbox_name)

        try:
            t0 = time.time()
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=sandbox.work_dir,
                env=sandbox.filtered_env(),
                preexec_fn=os.setsid,  # 创建新进程组，便于超时杀子进程
                text=True,
            )

            try:
                stdout, stderr = proc.communicate(timeout=policy.timeout_seconds)
                exit_code = proc.returncode
                timeout = False
            except subprocess.TimeoutExpired:
                # 杀死整个进程组
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    stdout, stderr = proc.communicate()
                exit_code = -1
                timeout = True

            duration_ms = (time.time() - t0) * 1000

            # 截断过大的输出
            stdout = self._truncate(stdout, policy.max_output_bytes)
            stderr = self._truncate(stderr, policy.max_output_bytes)

            return ShellResult(
                success=(exit_code == 0 and not timeout),
                command=command,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=duration_ms,
                timeout=timeout,
            )

        except Exception as e:
            return ShellResult(
                success=False, command=command,
                stdout="", stderr="", error=str(e),
            )

    def _safety_check(self, command: str, policy: ShellPolicy) -> str:
        """安全检查，返回错误信息或空字符串。"""
        # 提取主命令
        cmd_parts = shlex.split(command) if command else []
        if not cmd_parts:
            return "空命令"

        main_cmd = os.path.basename(cmd_parts[0])

        # 白名单检查
        if policy.allowed_commands:
            if main_cmd not in policy.allowed_commands and cmd_parts[0] not in policy.allowed_commands:
                return f"命令 '{main_cmd}' 不在允许列表中。允许的命令: {', '.join(policy.allowed_commands[:20])}"

        # 黑名单检查
        if policy.blocked_commands:
            if main_cmd in policy.blocked_commands or cmd_parts[0] in policy.blocked_commands:
                return f"命令 '{main_cmd}' 已被阻止。被阻止的命令: {', '.join(policy.blocked_commands)}"

        # 危险模式检查
        for pattern in policy.blocked_patterns:
            if re.search(pattern, command):
                return f"命令包含危险模式: {pattern}"

        # 管道检查
        if not policy.allow_pipes and "|" in command:
            return "管道操作不被允许"

        # 重定向检查
        if not policy.allow_redirects and re.search(r"[<>]", command):
            return "重定向操作不被允许"

        return ""

    @staticmethod
    def _truncate(text: str, max_bytes: int) -> str:
        """截断文本到指定字节数。"""
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
        return truncated + f"\n... [截断: {len(encoded)} → {max_bytes} 字节]"
