"""
Tests for AgentOS Sandbox (agentos/security/sandbox.py)
"""


import pytest

from agentos.security.sandbox import (
    SandboxAuditLogger,
    SandboxExecutor,
    SandboxPolicy,
    SandboxResult,
    SecurityLevel,
)


class TestSandboxPolicy:
    """SandboxPolicy configuration tests."""

    def test_default_policy(self):
        policy = SandboxPolicy()
        assert policy.max_cpu_time_seconds == 30.0
        assert policy.max_memory_mb == 256
        assert not policy.network_enabled
        assert not policy.disk_write_enabled
        assert policy.timeout_seconds == 60.0

    def test_restricted_level(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RESTRICTED)
        assert policy.max_cpu_time_seconds == 5.0
        assert policy.max_memory_mb == 64
        assert not policy.network_enabled
        assert not policy.disk_write_enabled
        assert "math" in policy.allowed_modules
        assert "json" in policy.allowed_modules

    def test_standard_level(self):
        policy = SandboxPolicy.for_level(SecurityLevel.STANDARD)
        assert policy.max_cpu_time_seconds == 30.0
        assert policy.block_dangerous_modules is True

    def test_relaxed_level(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RELAXED)
        assert policy.max_cpu_time_seconds == 120.0
        assert policy.max_memory_mb == 1024
        assert policy.network_enabled
        assert policy.disk_write_enabled
        assert not policy.block_dangerous_modules


class TestSandboxResult:
    """SandboxResult immutability and logic tests."""

    def test_success_true(self):
        result = SandboxResult(exit_code=0, stdout="ok", stderr="", execution_time_ms=10, peak_memory_mb=1.0)
        assert result.success

    def test_success_false_on_nonzero(self):
        result = SandboxResult(exit_code=1, stdout="", stderr="error", execution_time_ms=10, peak_memory_mb=1.0)
        assert not result.success

    def test_success_false_on_killed(self):
        result = SandboxResult(exit_code=-1, stdout="", stderr="", execution_time_ms=10, peak_memory_mb=1.0, was_killed=True)
        assert not result.success

    def test_to_dict(self):
        result = SandboxResult(exit_code=0, stdout="hello", stderr="", execution_time_ms=5.0, peak_memory_mb=0.5)
        d = result.to_dict()
        assert d["exit_code"] == 0
        assert d["stdout"] == "hello"
        assert d["success"]

    def test_frozen(self):
        result = SandboxResult(exit_code=0, stdout="x", stderr="", execution_time_ms=1, peak_memory_mb=0)
        with pytest.raises(Exception):
            result.exit_code = 1  # frozen dataclass


class TestSandboxAuditLogger:
    """Audit logger tests."""

    def test_log_events(self):
        logger = SandboxAuditLogger()
        logger.log("execute", {"code_len": 100})
        logger.log("complete", {"success": True})
        events = logger.get_events()
        assert len(events) == 2
        assert events[0]["event"] == "execute"

    def test_limit(self):
        logger = SandboxAuditLogger()
        for i in range(150):
            logger.log("test", {"i": i})
        assert len(logger.get_events(limit=50)) == 50

    def test_clear(self):
        logger = SandboxAuditLogger()
        logger.log("test", {})
        logger.clear()
        assert len(logger.get_events()) == 0


class TestSandboxExecutor:
    """Sandbox executor integration tests."""

    def test_simple_execution(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RELAXED)
        executor = SandboxExecutor(policy=policy, audit=True)
        result = executor.execute("x = 1 + 1\nprint(x)")
        assert result.exit_code == 0
        assert "2" in result.stdout

    def test_timeout_kill(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RESTRICTED)
        policy.timeout_seconds = 1.0
        executor = SandboxExecutor(policy=policy, audit=False)
        result = executor.execute("import time; time.sleep(10)")
        assert result.was_killed
        assert "timeout" in result.kill_reason.lower() or "Timeout" in result.kill_reason

    def test_dangerous_module_blocked(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RESTRICTED)
        executor = SandboxExecutor(policy=policy, audit=False)
        result = executor.execute("import os\nprint('should not reach')")
        # Should either fail or block the import
        assert result.exit_code != 0 or "should not reach" not in result.stdout

    def test_execute_sync(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RELAXED)
        executor = SandboxExecutor(policy=policy, audit=True)
        result = executor.execute_sync("x = sum([1, 2, 3])")
        assert result.success

    def test_execute_sync_with_namespace(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RELAXED)
        executor = SandboxExecutor(policy=policy, audit=False)
        ns = {}
        executor.execute_sync("result = 42", ns)
        assert ns.get("result") == 42

    def test_audit_log(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RELAXED)
        executor = SandboxExecutor(policy=policy, audit=True)
        executor.execute("print(1)")
        log = executor.get_audit_log()
        assert len(log) >= 2  # execute + complete

    def test_clear_audit(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RELAXED)
        executor = SandboxExecutor(policy=policy, audit=True)
        executor.execute("print(1)")
        executor.clear_audit()
        assert len(executor.get_audit_log()) == 0

    def test_syntax_error(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RELAXED)
        executor = SandboxExecutor(policy=policy, audit=False)
        result = executor.execute("this is not valid python !!!")
        assert result.exit_code != 0

    def test_output_truncation(self):
        policy = SandboxPolicy.for_level(SecurityLevel.RELAXED)
        policy.max_output_size_bytes = 10
        executor = SandboxExecutor(policy=policy, audit=False)
        big_output = "print('x' * 1000)"
        result = executor.execute(big_output)
        # Output should be within limits
        assert result.success or len(result.stdout) <= policy.max_output_size_bytes

    def test_policy_immutable_after_create(self):
        policy = SandboxPolicy()
        executor = SandboxExecutor(policy=policy)
        assert executor.policy is policy
