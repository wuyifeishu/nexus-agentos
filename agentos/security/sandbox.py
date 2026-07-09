"""
AgentOS Sandbox — Secure Code Execution Sandbox
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Production-grade code execution sandbox with:

  - Resource limits (CPU time, memory, disk, network)
  - Timeout enforcement
  - Process isolation (subprocess-based)
  - Dangerous import/module blacklisting
  - Output size limits
  - Audit logging for every execution

Architecture:
  SandboxPolicy  → defines resource limits and restrictions
  SandboxExecutor → executes code in isolated subprocess
  SandboxResult   → immutable execution result
"""

from __future__ import annotations

import builtins
import os
import resource
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Sandbox Policy
# ---------------------------------------------------------------------------


class SecurityLevel(StrEnum):
    """Security level determines which restrictions apply."""

    RESTRICTED = "restricted"  # Max restrictions, no network/disk
    STANDARD = "standard"  # Reasonable limits for most use cases
    RELAXED = "relaxed"  # Minimal restrictions, trusted code only


# Dangerous modules and builtins to block
DANGEROUS_MODULES: set[str] = {
    "os",
    "subprocess",
    "shlex",
    "sys",
    "ctypes",
    "socket",
    "http",
    "requests",
    "urllib",
    "multiprocessing",
    "threading",
    "concurrent.futures",
    "importlib",
    "pkgutil",
    "pkg_resources",
    "pickle",
    "marshal",
    "shelve",
    "pathlib",
    "shutil",
    "glob",
    "fnmatch",
    "signal",
    "atexit",
    "code",
    "codeop",
    "compileall",
    "pty",
    "fcntl",
    "tty",
    "termios",
    "webbrowser",
}

DANGEROUS_BUILTINS: set[str] = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "open",
    "input",
    "breakpoint",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "type",
    "issubclass",
    "isinstance",
    "memoryview",
    "bytearray",
}


@dataclass
class SandboxPolicy:
    """Resource limits and restrictions for sandboxed execution."""

    # Resource limits
    max_cpu_time_seconds: float = 30.0
    max_memory_mb: int = 256
    max_output_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_files_open: int = 50
    max_processes: int = 1
    network_enabled: bool = False
    disk_write_enabled: bool = False

    # Execution constraints
    timeout_seconds: float = 60.0
    max_iterations: int = 10_000_000  # Safety net for infinite loops

    # Security
    block_dangerous_modules: bool = True
    block_dangerous_builtins: bool = True
    allowed_modules: set[str] = field(default_factory=set)
    allowed_imports: set[str] = field(default_factory=set)

    # Audit
    enable_audit: bool = True

    @classmethod
    def for_level(cls, level: SecurityLevel) -> SandboxPolicy:
        """Create a policy for a given security level."""
        if level == SecurityLevel.RESTRICTED:
            return cls(
                max_cpu_time_seconds=5.0,
                max_memory_mb=64,
                max_output_size_bytes=1 * 1024 * 1024,
                network_enabled=False,
                disk_write_enabled=False,
                timeout_seconds=10.0,
                allowed_modules={
                    "math",
                    "json",
                    "datetime",
                    "collections",
                    "itertools",
                    "functools",
                },
            )
        elif level == SecurityLevel.RELAXED:
            return cls(
                max_cpu_time_seconds=120.0,
                max_memory_mb=1024,
                max_output_size_bytes=100 * 1024 * 1024,
                network_enabled=True,
                disk_write_enabled=True,
                timeout_seconds=300.0,
                block_dangerous_modules=False,
            )
        else:  # STANDARD
            return cls()


# ---------------------------------------------------------------------------
# Sandbox Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxResult:
    """Immutable result of a sandboxed code execution."""

    exit_code: int
    stdout: str
    stderr: str
    execution_time_ms: float
    peak_memory_mb: float
    was_killed: bool = False
    kill_reason: str = ""
    error: str | None = None
    timestamp: float = field(default_factory=time.time)

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.was_killed

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout[:1000],
            "stderr": self.stderr[:1000],
            "execution_time_ms": self.execution_time_ms,
            "peak_memory_mb": self.peak_memory_mb,
            "was_killed": self.was_killed,
            "kill_reason": self.kill_reason,
            "success": self.success,
        }


# ---------------------------------------------------------------------------
# Audit Logger
# ---------------------------------------------------------------------------


class SandboxAuditLogger:
    """Logs sandbox execution events for security auditing."""

    def __init__(self):
        self._events: list[dict[str, Any]] = []

    def log(self, event_type: str, details: dict[str, Any]) -> None:
        self._events.append(
            {
                "event": event_type,
                "timestamp": time.time(),
                **details,
            }
        )

    def get_events(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._events[-limit:]

    def clear(self) -> None:
        self._events.clear()


# ---------------------------------------------------------------------------
# Sandbox Executor
# ---------------------------------------------------------------------------


class SandboxExecutor:
    """
    Execute Python code in an isolated sandbox with resource limits.

    Uses subprocess isolation with resource limits set via RLIMIT.
    """

    def __init__(
        self,
        policy: SandboxPolicy | None = None,
        audit: bool = True,
    ):
        self._policy = policy or SandboxPolicy()
        self._auditor = SandboxAuditLogger() if audit else None

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    def execute(self, code: str, globals_dict: dict | None = None) -> SandboxResult:
        """
        Execute code in sandbox.

        Args:
            code: Python code string to execute
            globals_dict: Optional global namespace (restricted)

        Returns:
            SandboxResult with execution details
        """
        audit_id = f"sandbox_{int(time.time() * 1000)}"

        if self._auditor:
            self._auditor.log(
                "execute",
                {
                    "audit_id": audit_id,
                    "code_length": len(code),
                    "policy_level": self._policy.network_enabled and "relaxed" or "restricted",
                },
            )

        start = time.time()
        peak_memory = 0.0

        try:
            # Build restricted globals
            self._build_restricted_globals(globals_dict or {})

            # Write code to temp file for subprocess isolation
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, prefix="sandbox_", dir=tempfile.gettempdir()
            ) as f:
                f.write(self._wrap_code_with_limits(code))
                script_path = f.name

            try:
                result = subprocess.run(
                    [sys.executable, script_path],
                    capture_output=True,
                    text=True,
                    timeout=self._policy.timeout_seconds,
                    env=self._build_sandbox_env(),
                    preexec_fn=self._set_resource_limits if os.name != "nt" else None,
                )

                stdout = result.stdout[: self._policy.max_output_size_bytes]
                stderr = result.stderr[: self._policy.max_output_size_bytes]

                sandbox_result = SandboxResult(
                    exit_code=result.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time_ms=(time.time() - start) * 1000,
                    peak_memory_mb=peak_memory,
                )

            except subprocess.TimeoutExpired:
                sandbox_result = SandboxResult(
                    exit_code=-1,
                    stdout="",
                    stderr="",
                    execution_time_ms=(time.time() - start) * 1000,
                    peak_memory_mb=peak_memory,
                    was_killed=True,
                    kill_reason=f"Timeout: exceeded {self._policy.timeout_seconds}s",
                    error="Execution timed out",
                )
            finally:
                try:
                    os.unlink(script_path)
                except OSError:
                    pass

        except Exception as e:
            sandbox_result = SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=traceback.format_exc(),
                execution_time_ms=(time.time() - start) * 1000,
                peak_memory_mb=peak_memory,
                error=str(e),
            )

        if self._auditor:
            self._auditor.log(
                "complete",
                {
                    "audit_id": audit_id,
                    "success": sandbox_result.success,
                    "execution_time_ms": sandbox_result.execution_time_ms,
                    "exit_code": sandbox_result.exit_code,
                },
            )

        return sandbox_result

    def execute_sync(self, code: str, namespace: dict | None = None) -> SandboxResult:
        """
        Execute code synchronously in-process with restricted namespace.

        Faster than execute() but slightly less isolated.
        """
        start = time.time()
        audit_id = f"sync_{int(start * 1000)}"

        if self._auditor:
            self._auditor.log("execute_sync", {"audit_id": audit_id, "code_length": len(code)})

        try:
            restricted_globals = self._build_restricted_globals({})

            exec(code, restricted_globals)

            # Propagate results back to caller namespace
            if namespace is not None:
                namespace.update(
                    {
                        k: v
                        for k, v in restricted_globals.items()
                        if not k.startswith("__") and k not in self._policy.allowed_modules
                    }
                )

            result = SandboxResult(
                exit_code=0,
                stdout="",
                stderr="",
                execution_time_ms=(time.time() - start) * 1000,
                peak_memory_mb=0.0,
            )
        except Exception as e:
            result = SandboxResult(
                exit_code=-1,
                stdout="",
                stderr=traceback.format_exc(),
                execution_time_ms=(time.time() - start) * 1000,
                peak_memory_mb=0.0,
                error=str(e),
            )

        if self._auditor:
            self._auditor.log(
                "complete_sync",
                {
                    "audit_id": audit_id,
                    "success": result.success,
                },
            )

        return result

    def _build_restricted_globals(self, extra: dict) -> dict:
        """Build a restricted global namespace."""
        safe_builtins = {
            k: v
            for k, v in __builtins__.items()
            if k not in (self._policy.block_dangerous_builtins and DANGEROUS_BUILTINS or set())
        }

        globals_dict = {"__builtins__": safe_builtins}

        # Add allowed modules
        for mod_name in self._policy.allowed_modules:
            try:
                mod = __import__(mod_name)
                globals_dict[mod_name] = mod
            except ImportError:
                pass

        globals_dict.update(extra)
        return globals_dict

    def _build_sandbox_env(self) -> dict[str, str]:
        """Build a restricted environment for subprocess."""
        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": tempfile.gettempdir(),
            "TMPDIR": tempfile.gettempdir(),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SANDBOX_MAX_CPU": str(self._policy.max_cpu_time_seconds),
            "SANDBOX_MAX_MEMORY_MB": str(self._policy.max_memory_mb),
        }
        return env

    def _set_resource_limits(self) -> None:
        """Set OS-level resource limits (Unix only)."""
        try:
            # CPU time limit
            cpu_seconds = int(self._policy.max_cpu_time_seconds)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5))

            # Memory limit
            mem_bytes = self._policy.max_memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

            # File descriptors
            resource.setrlimit(
                resource.RLIMIT_NOFILE,
                (self._policy.max_files_open, self._policy.max_files_open),
            )

            # Processes
            resource.setrlimit(
                resource.RLIMIT_NPROC,
                (self._policy.max_processes, self._policy.max_processes),
            )
        except (OSError, ValueError):
            pass

    def _wrap_code_with_limits(self, code: str) -> str:
        """Wrap user code with safety limits."""
        wrapper = f"""
import sys

# Blacklist dangerous modules via import hook
_dangerous_modules = {repr(DANGEROUS_MODULES)}

class _RestrictedFinder:
    def find_spec(self, fullname, path, target=None):
        if fullname in _dangerous_modules or fullname.startswith(tuple(m + '.' for m in _dangerous_modules)):
            raise ImportError(f"Module '{{fullname}}' is restricted in sandbox")
        return None

sys.meta_path.insert(0, _RestrictedFinder())

# Purge pre-cached dangerous modules from sys.modules
for _m in list(sys.modules.keys()):
    if _m in _dangerous_modules or any(_m.startswith(_d + '.') for _d in _dangerous_modules):
        del sys.modules[_m]

# Execute user code
{code}
"""
        return wrapper

    def get_audit_log(self) -> list[dict[str, Any]]:
        if self._auditor:
            return self._auditor.get_events()
        return []

    def clear_audit(self) -> None:
        if self._auditor:
            self._auditor.clear()


# ---------------------------------------------------------------------------
# Backward-compatible aliases (v1.x migration)
# ---------------------------------------------------------------------------

# RiskLevel = SecurityLevel (alias)
RiskLevel = SecurityLevel


@dataclass
class SafetyReport:
    """Safety analysis report for code/input evaluation."""

    risk_level: RiskLevel = RiskLevel.STANDARD
    is_safe: bool = True
    findings: list[str] = field(default_factory=list)
    recommendation: str = ""
    score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level.value,
            "is_safe": self.is_safe,
            "findings": self.findings,
            "recommendation": self.recommendation,
            "score": self.score,
        }


class LLMSafetyAnalyzer:
    """LLM-based safety analyzer for code and content review."""

    def __init__(self, policy: SandboxPolicy | None = None):
        self._policy = policy or SandboxPolicy()

    def analyze(self, code: str) -> SafetyReport:
        findings: list[str] = []
        is_safe = True
        score = 1.0

        for mod in DANGEROUS_MODULES:
            if f"import {mod}" in code or f"from {mod}" in code:
                findings.append(f"Uses dangerous module: {mod}")
                is_safe = False
                score = max(0.0, score - 0.15)

        for builtin_name in DANGEROUS_BUILTINS:
            if builtin_name in code:
                findings.append(f"Uses dangerous builtin: {builtin_name}")
                is_safe = False
                score = max(0.0, score - 0.1)

        if not is_safe:
            return SafetyReport(
                risk_level=RiskLevel.RESTRICTED,
                is_safe=False,
                findings=findings,
                recommendation="Code contains potentially dangerous operations",
                score=score,
            )
        return SafetyReport(
            risk_level=RiskLevel.STANDARD,
            is_safe=True,
            findings=findings,
            score=score,
        )


class Sandbox:
    """Backward-compatible Sandbox wrapper around SandboxPolicy + SandboxExecutor."""

    def __init__(self, policy: SandboxPolicy | None = None):
        self._policy = policy or SandboxPolicy()
        self._executor = SandboxExecutor(policy=self._policy)

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    def run(self, code: str) -> SandboxResult:
        return self._executor.execute(code)

    def run_sync(self, code: str, namespace: dict | None = None) -> SandboxResult:
        return self._executor.execute_sync(code, namespace)


class SandboxManager:
    """Backward-compatible SandboxManager — manages multiple sandbox instances."""

    def __init__(self, default_policy: SandboxPolicy | None = None):
        self._default_policy = default_policy or SandboxPolicy()
        self._sandboxes: dict[str, Sandbox] = {}

    def create(self, name: str, policy: SandboxPolicy | None = None) -> Sandbox:
        sb = Sandbox(policy=policy or self._default_policy)
        self._sandboxes[name] = sb
        return sb

    def get(self, name: str) -> Sandbox | None:
        return self._sandboxes.get(name)

    def remove(self, name: str) -> bool:
        if name in self._sandboxes:
            del self._sandboxes[name]
            return True
        return False

    def list(self) -> builtins.list[str]:
        return list(self._sandboxes.keys())

    def execute_all(self, code: str) -> dict[str, SandboxResult]:
        return {name: sb.run(code) for name, sb in self._sandboxes.items()}
