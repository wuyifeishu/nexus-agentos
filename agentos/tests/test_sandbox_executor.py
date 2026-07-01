"""测试 sandbox_executor — 进程级和 Docker 沙箱执行。"""

import os
import tempfile
import pytest
from agentos.security.sandbox import SandboxExecutor, SandboxConfig, SandboxMode, SandboxResult


class TestProcessSandbox:
    def test_basic_python_execution(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS, timeout_seconds=5)
        sb = SandboxExecutor(config)
        result = sb._sandbox.execute_code("print('hello from sandbox')")
        assert result.success
        assert result.exit_code == 0
        assert "hello from sandbox" in result.stdout
        sb._sandbox.cleanup()

    def test_basic_bash_execution(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS, timeout_seconds=5)
        sb = SandboxExecutor(config)
        result = sb._sandbox.execute_code("echo 'bash test'", language="bash")
        assert result.success
        assert "bash test" in result.stdout
        sb._sandbox.cleanup()

    def test_code_with_error(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS, timeout_seconds=5)
        sb = SandboxExecutor(config)
        result = sb._sandbox.execute_code("raise ValueError('test error')")
        assert not result.success
        assert result.exit_code != 0
        sb._sandbox.cleanup()

    def test_timeout(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS, timeout_seconds=0.2)
        sb = SandboxExecutor(config)
        result = sb._sandbox.execute_code("import time; time.sleep(10)")
        assert not result.success
        assert result.exit_code == -1
        assert "Timeout" in (result.error or "")
        sb._sandbox.cleanup()

    def test_stdout_truncation(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS, max_output_bytes=50, timeout_seconds=5)
        sb = SandboxExecutor(config)
        result = sb._sandbox.execute_code("print('A' * 200)")
        assert result.truncated
        assert len(result.stdout) <= 50 + len("\n... [stdout truncated]")
        sb._sandbox.cleanup()

    def test_input_files(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS, timeout_seconds=5)
        sb = SandboxExecutor(config)

        # create a temp input file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("input data")
            input_path = f.name

        result = sb._sandbox.execute_code(
            "with open('input.txt') as f: print(f.read())",
            input_files={"input.txt": input_path},
        )
        assert result.success
        assert "input data" in result.stdout

        os.unlink(input_path)
        sb._sandbox.cleanup()

    def test_output_collection(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS, timeout_seconds=5)
        sb = SandboxExecutor(config)

        result = sb._sandbox.execute_code(
            "with open('output.txt', 'w') as f: f.write('generated'); "
            "import json; json.dump({'a': 1}, open('data.json', 'w'))"
        )
        assert result.success

        files = sb._sandbox.collect_output_files([".txt", ".json"])
        assert "output.txt" in files
        assert "data.json" in files
        assert os.path.exists(files["output.txt"])
        assert os.path.exists(files["data.json"])

        # verify content
        with open(files["output.txt"]) as f:
            assert f.read() == "generated"
        sb._sandbox.cleanup()

    def test_execute_command(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS, timeout_seconds=5)
        sb = SandboxExecutor(config)
        result = sb._sandbox.execute_command("echo cmd_test && ls")
        assert result.success
        assert "cmd_test" in result.stdout
        sb._sandbox.cleanup()

    def test_context_manager(self):
        config = SandboxConfig(mode=SandboxMode.PROCESS)
        sb = SandboxExecutor(config)
        result = None
        with sb:
            result = sb._sandbox.execute_code("x = 1 + 1; print(x)")
        assert result is not None
        assert result.success
        assert "2" in result.stdout


class TestSandboxConfig:
    def test_defaults(self):
        config = SandboxConfig()
        assert config.mode == SandboxMode.PROCESS
        assert config.memory_limit_mb == 256
        assert config.timeout_seconds == 30

    def test_custom(self):
        config = SandboxConfig(
            mode=SandboxMode.DOCKER,
            memory_limit_mb=512,
            timeout_seconds=10,
            network_enabled=True,
        )
        assert config.mode == SandboxMode.DOCKER
        assert config.memory_limit_mb == 512
        assert config.timeout_seconds == 10
        assert config.network_enabled


class TestDockerFallback:
    """Docker 不可用时自动降级到 Process 模式。"""

    def test_docker_fallback_when_no_docker(self):
        # 该环境可能没有 Docker，应自动降级
        config = SandboxConfig(mode=SandboxMode.DOCKER, timeout_seconds=3)
        executor = SandboxExecutor(config)
        # 内部已将 mode 调整或降级
        result = executor._sandbox.execute_code("print('fallback works')")
        assert result.success
        executor._sandbox.cleanup()
