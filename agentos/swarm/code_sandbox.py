"""
v1.9.5: Isolated Code Sandbox for safe agent code generation & execution.

Runs generated code in subprocess with timeout, memory limits,
test case validation, and structured error extraction for feedback loops.
"""

from __future__ import annotations

import asyncio
import os
import resource
import signal
import subprocess
import tempfile
import traceback
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxResult:
    """Result of a sandbox execution."""

    success: bool = False
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    exception: str = ""
    duration: float = 0.0
    max_memory_mb: float = 0.0
    test_results: list[dict] = field(default_factory=list)  # per-test-case results
    all_passed: bool = False

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:500],
            "stderr": self.stderr[:500],
            "exception": self.exception[:300],
            "duration": f"{self.duration:.2f}s",
            "max_memory_mb": f"{self.max_memory_mb:.1f}",
            "test_results": self.test_results,
            "all_passed": self.all_passed,
        }


@dataclass
class TestCase:
    """A single test case for code validation."""

    name: str
    input_args: tuple = ()
    input_kwargs: dict = field(default_factory=dict)
    expected_output: Any = None
    expected_type: str = ""        # e.g. "int", "str", "list"
    expected_exception: str = ""   # e.g. "ValueError"
    weight: float = 1.0

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "input_args": str(self.input_args)}
        if self.expected_output is not None:
            d["expected_output"] = str(self.expected_output)[:100]
        if self.expected_exception:
            d["expected_exception"] = self.expected_exception
        return d


class CodeSandbox:
    """Isolated execution environment for agent-generated code.

    Usage:
        sandbox = CodeSandbox(timeout=30, max_memory_mb=256)
        result = sandbox.run(
            code="def add(a, b): return a + b",
            func_name="add",
            test_cases=[TestCase(name="1+2", args=(1, 2), expected=3)]
        )
    """

    def __init__(
        self,
        timeout: float = 30.0,
        max_memory_mb: int = 256,
        allow_imports: bool = True,
        forbidden_modules: list[str] | None = None,
    ):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.allow_imports = allow_imports
        self.forbidden_modules = forbidden_modules or [
            "os.system", "subprocess", "shutil", "socket",
            "requests", "urllib", "http", "ftp",
        ]

    def run(
        self,
        code: str,
        func_name: str = "",
        test_cases: list[TestCase] | None = None,
        setup_code: str = "",
    ) -> SandboxResult:
        """Execute code in sandbox with test cases.

        Args:
            code: The code to execute
            func_name: Name of the function to test
            test_cases: List of test cases to run against func_name
            setup_code: Setup code to run before tests (imports, fixtures)

        Returns:
            SandboxResult with execution details and test outcomes
        """
        test_cases = test_cases or []

        # Security check
        security_issues = self._check_security(code)
        if security_issues:
            return SandboxResult(
                success=False,
                stderr=f"SECURITY VIOLATION: {security_issues}",
                exception="Security check failed",
            )

        # Syntactic check
        syntax_ok, syntax_err = self._check_syntax(code)
        if not syntax_ok:
            return SandboxResult(
                success=False,
                stderr=syntax_err,
                exception=f"Syntax error: {syntax_err}",
            )

        # Write code to temp file and execute
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False,
            prefix="sandbox_"
        ) as f:
            script = self._build_script(code, func_name, test_cases, setup_code)
            f.write(script)
            script_path = f.name

        try:
            result = self._execute_script(script_path)
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

        return result

    def _check_security(self, code: str) -> str:
        """Check for forbidden patterns."""
        issues = []
        code_lower = code.lower()

        # Check forbidden modules
        for mod in self.forbidden_modules:
            import_pattern = mod.replace(".", ".")
            if f"import {import_pattern}" in code_lower:
                issues.append(f"Forbidden import: {mod}")
            if f"from {import_pattern}" in code_lower:
                issues.append(f"Forbidden import: {mod}")

        # Check dangerous builtins
        dangerous = [
            ("eval(", "eval() is forbidden"),
            ("exec(", "exec() is forbidden"),
            ("__import__(", "__import__() is forbidden"),
            ("open(", "File I/O blocked in sandbox"),
        ]
        for pattern, msg in dangerous:
            if pattern in code_lower:
                issues.append(msg)

        return "; ".join(issues) if issues else ""

    def _check_syntax(self, code: str) -> tuple[bool, str]:
        """Check Python syntax."""
        try:
            compile(code, "<sandbox>", "exec")
            return True, ""
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"

    def _build_script(
        self,
        code: str,
        func_name: str,
        test_cases: list[TestCase],
        setup_code: str,
    ) -> str:
        """Build the full sandbox execution script."""

        tc_defs = []
        tc_names = []
        for tc in test_cases:
            tc_names.append(tc.name)
            tc_defs.append(
                f'    "{tc.name}": {{'
                f'"args": {list(tc.input_args)}, '
                f'"kwargs": {tc.input_kwargs}, '
                f'"expected": {repr(tc.expected_output) if tc.expected_output is not None else None}, '
                f'"expected_type": "{tc.expected_type}", '
                f'"expected_exception": "{tc.expected_exception}"'
                f"}}"
            )

        tc_dict = ",\n".join(tc_defs)
        tc_list = ", ".join(f'"{n}"' for n in tc_names)

        return f'''#!/usr/bin/env python3
"""Sandbox execution script — auto-generated by CodeSandbox."""
import json
import sys
import time
import traceback
import os

# Limit memory
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, ({self.max_memory_mb} * 1024 * 1024, {self.max_memory_mb} * 1024 * 1024))
except Exception:
    pass

# Setup code
{setup_code}

# User code
{code}

# Test runner
test_cases = {{
{tc_dict}
}}

func_name = "{func_name}"
has_func = func_name and func_name in dir()

results = []
total = 0
passed = 0

if not has_func and len(test_cases) == 0:
    print("__SANDBOX_OK__")
    print(json.dumps({{"status": "executed", "message": "Code executed, no tests"}}))
    sys.exit(0)

if not has_func and len(test_cases) > 0:
    print("__SANDBOX_ERR__")
    print(json.dumps({{"error": f"Function '{{func_name}}' not found in code"}}))
    sys.exit(1)

func = eval(func_name)
all_test_order = [{tc_list}]

for tc_name in all_test_order:
    tc = test_cases[tc_name]
    total += 1
    start = time.time()
    try:
        output = func(*tc["args"], **tc["kwargs"])
        elapsed = time.time() - start

        expected = tc.get("expected")
        expected_type = tc.get("expected_type")
        expected_exc = tc.get("expected_exception")

        if expected_exc:
            passed_ = False
            detail = f"Expected exception {{expected_exc}} but none raised"
        elif expected_type and not isinstance(output, eval(expected_type)):
            passed_ = False
            detail = f"Type mismatch: got {{type(output).__name__}}, expected {{expected_type}}"
        elif expected is not None and output != expected:
            passed_ = False
            detail = f"Expected {{repr(expected)}}, got {{repr(output)}}"
        else:
            passed_ = True
            detail = "OK"

        if passed_:
            passed += 1

        results.append({{
            "name": tc_name,
            "passed": passed_,
            "output": repr(output)[:200],
            "expected": repr(expected)[:200],
            "detail": detail,
            "duration_ms": round(elapsed * 1000, 2),
        }})
    except Exception as e:
        exc_name = type(e).__name__
        expected_exc = tc.get("expected_exception", "")

        if expected_exc and exc_name == expected_exc:
            passed_ = True
            detail = f"Expected exception {{exc_name}} raised"
            passed += 1
        else:
            passed_ = False
            detail = f"{{exc_name}}: {{str(e)[:200]}}"

        results.append({{
            "name": tc_name,
            "passed": passed_,
            "output": "",
            "expected": repr(tc.get("expected"))[:200],
            "detail": detail,
            "duration_ms": 0,
        }})

print("__SANDBOX_RESULTS__")
print(json.dumps({{
    "status": "complete",
    "total": total,
    "passed": passed,
    "failed": total - passed,
    "all_passed": total > 0 and passed == total,
    "test_results": results,
}}))
'''

    def _execute_script(self, script_path: str) -> SandboxResult:
        """Execute the sandbox script as subprocess."""
        try:
            start = time_module()
            proc = subprocess.run(
                ["python3", script_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd="/tmp",
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": "",
                    "SANDBOX_MODE": "1",
                },
            )
            duration = time_module() - start
        except subprocess.TimeoutExpired as e:
            return SandboxResult(
                success=False,
                exit_code=-1,
                stderr=str(e.stdout or "") if e.stdout else "",
                exception=f"Timeout after {self.timeout}s",
                duration=self.timeout,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                exception=str(e),
                stderr=traceback.format_exc(),
            )

        result = SandboxResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration=duration,
        )

        # Parse test results
        if "__SANDBOX_RESULTS__" in proc.stdout:
            try:
                lines = proc.stdout.split("\n")
                json_start = False
                json_text = ""
                for line in lines:
                    if json_start:
                        json_text += line
                        try:
                            data = json.loads(json_text)
                            break
                        except json.JSONDecodeError:
                            continue
                    if "__SANDBOX_RESULTS__" in line:
                        json_start = True

                if data:
                    result.test_results = data.get("test_results", [])
                    result.all_passed = data.get("all_passed", False)
                    passed = data.get("passed", 0)
                    total = data.get("total", 0)
                    result.success = total > 0 and passed == total
            except Exception:
                pass

        elif proc.returncode == 0 and not proc.stderr:
            result.success = True

        # Extract meaningful error info for feedback
        if not result.success and result.stderr:
            lines = result.stderr.strip().split("\n")
            # Get last 3 lines (most relevant error info)
            result.exception = "\n".join(lines[-5:]) if len(lines) > 5 else result.stderr

        return result


def time_module() -> float:
    """Get current time in seconds."""
    import time as _time
    return _time.time()


class CodeFeedbackExtractor:
    """Extracts actionable feedback from sandbox failures for retry loops."""

    ERROR_PATTERNS = {
        "NameError": "Variable or function not defined. Check spelling and scope.",
        "TypeError": "Wrong type passed to function. Check argument types.",
        "ValueError": "Invalid value for operation. Check parameter constraints.",
        "IndexError": "List index out of range. Check bounds.",
        "KeyError": "Dictionary key not found. Check key existence.",
        "AttributeError": "Object has no such attribute. Check method/attribute name.",
        "ImportError": "Missing import. Add 'import X' or 'from X import Y'.",
        "SyntaxError": "Python syntax error. Check indentation, brackets, colons.",
        "ZeroDivisionError": "Division by zero. Add guard for zero denominator.",
        "RecursionError": "Recursion depth exceeded. Add base case or switch to iteration.",
        "TimeoutError": "Code timed out. Check for infinite loops or optimize.",
    }

    @classmethod
    def extract(cls, sandbox_result: SandboxResult) -> list[str]:
        """Extract actionable feedback suggestions from sandbox result."""
        suggestions: list[str] = []

        # Check for security issues
        if "SECURITY" in sandbox_result.stderr:
            suggestions.append("Code violates sandbox security rules; avoid system calls and I/O.")
            return suggestions

        # Check test failures
        for tc in sandbox_result.test_results:
            if not tc.get("passed", True):
                detail = tc.get("detail", "")
                name = tc.get("name", "unknown")
                suggestions.append(f"Test '{name}' failed: {detail}")

        # Check error patterns
        for error_type, suggestion in cls.ERROR_PATTERNS.items():
            if error_type in sandbox_result.stderr or error_type in sandbox_result.exception:
                if suggestion not in suggestions:
                    suggestions.append(suggestion)

        # Add specific output mismatch advice
        if not sandbox_result.success and not suggestions:
            suggestions.append("Code failed to execute. Check logic and edge cases.")
            if sandbox_result.stderr:
                suggestions.append(f"Error: {sandbox_result.stderr.strip()[:200]}")

        return suggestions
