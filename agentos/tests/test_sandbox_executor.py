"""测试 sandbox_executor — 沙箱代码执行。"""

from agentos.security.sandbox import SandboxExecutor, SandboxPolicy, SandboxResult


class TestProcessSandbox:
    def test_basic_python_execution(self):
        sb = SandboxExecutor()
        result = sb.execute("print('hello from sandbox')")
        assert isinstance(result, SandboxResult)
        assert result.exit_code == 0
        assert "hello from sandbox" in result.stdout

    def test_code_with_error(self):
        sb = SandboxExecutor()
        result = sb.execute("raise ValueError('test error')")
        assert result.exit_code != 0
        assert "ValueError" in (result.stderr or "")

    def test_custom_policy(self):
        policy = SandboxPolicy(max_output_size_bytes=100, timeout_seconds=5)
        sb = SandboxExecutor(policy=policy)
        result = sb.execute("x = 1 + 1; print(x)")
        assert result.exit_code == 0
        assert "2" in result.stdout

    def test_namespace_isolation(self):
        """Verify sandbox does not pollute caller's namespace."""
        caller_ns = {}
        sb = SandboxExecutor()
        result = sb.execute("y = 42", globals_dict=caller_ns)
        assert result.exit_code == 0
        # Caller dict should be safe from mutation
        assert "y" not in caller_ns


class TestSandboxPolicy:
    def test_defaults(self):
        policy = SandboxPolicy()
        assert policy.timeout_seconds > 0
        assert policy.max_memory_mb is not None

    def test_custom(self):
        policy = SandboxPolicy(
            timeout_seconds=10,
            max_memory_mb=256,
            network_enabled=False,
        )
        assert policy.timeout_seconds == 10
        assert policy.max_memory_mb == 256
        assert policy.network_enabled is False


class TestSandboxResult:
    def test_result_fields(self):
        result = SandboxResult(
            exit_code=0,
            stdout="hello",
            stderr="",
            execution_time_ms=100,
            peak_memory_mb=12.5,
        )
        assert result.exit_code == 0
        assert result.stdout == "hello"
        assert result.success is True
        assert result.peak_memory_mb == 12.5
