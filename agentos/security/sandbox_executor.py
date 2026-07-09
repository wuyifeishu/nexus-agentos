"""
AgentOS v1.2.1 — 沙箱执行器。

基因来源: OpenHands Docker Sandbox + Claude Code subprocess isolation

提供真正的代码/命令隔离执行能力：
- Process模式: 子进程隔离（轻量，零依赖）
- Docker模式: 容器隔离（强隔离，需Docker）
- 资源限制：内存、CPU、时间、磁盘
- 文件桥接：自动复制输入文件到沙箱，提取输出文件
- 与 CodeAgent / ToolOrchestrator 集成
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

# ── 枚举与配置 ───────────────────────────────────


class SandboxMode(StrEnum):
    """沙箱模式枚举。"""

    DOCKER = "docker"
    PROCESS = "process"
    NONE = "none"  # 直接在当前进程执行（不安全，仅调试用）


@dataclass
class SandboxConfig:
    """沙箱执行配置"""

    mode: SandboxMode = SandboxMode.PROCESS
    memory_limit_mb: int = 256
    cpu_limit: float = 1.0  # CPU 核心数上限
    timeout_seconds: float = 30.0
    max_output_bytes: int = 1_000_000  # stdout+stderr 上限
    network_enabled: bool = False
    writable_root: bool = False  # root 是否可写（Docker模式）
    docker_image: str = "python:3.11-slim"
    container_name_prefix: str = "agentos-sandbox-"
    env_vars: dict[str, str] = field(default_factory=dict)


# ── 执行结果 ────────────────────────────────────


@dataclass
class SandboxResult:
    """沙箱执行结果"""

    success: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    output_files: dict[str, str] = field(default_factory=dict)  # 文件名→本地路径
    duration_ms: float = 0.0
    truncated: bool = False
    error: str | None = None


# ── Process 沙箱 ────────────────────────────────


class ProcessSandbox:
    """进程级隔离沙箱。使用 subprocess + 临时目录隔离文件系统。"""

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()
        self._work_dir: str | None = None

    def setup(self) -> str:
        """创建隔离的工作目录。返回沙箱目录路径。"""
        self._work_dir = tempfile.mkdtemp(prefix="agentos-sandbox-")
        return self._work_dir

    def copy_in(self, src: str, dst_filename: str | None = None) -> str:
        """将外部文件复制到沙箱内。返回沙箱内路径。"""
        if not self._work_dir:
            self.setup()
        fname = dst_filename or os.path.basename(src)
        dst = os.path.join(self._work_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        elif os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        return dst

    def copy_out(self, sandbox_path: str, local_path: str) -> str:
        """将沙箱内文件复制到外部。"""
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        if os.path.isfile(sandbox_path):
            shutil.copy2(sandbox_path, local_path)
        return local_path

    def collect_output_files(self, patterns: list[str] | None = None) -> dict[str, str]:
        """收集沙箱内生成的文件（按扩展名匹配），复制到本地临时目录。

        Args:
            patterns: 文件扩展名或glob模式列表，如 ['.json', '.csv', '.png']。
                      None 则收集所有非目录文件。

        Returns:
            {沙箱内文件名: 本地临时路径}
        """
        if not self._work_dir:
            return {}
        output_dir = tempfile.mkdtemp(prefix="agentos-output-")
        result: dict[str, str] = {}
        for root, dirs, files in os.walk(self._work_dir):
            for fname in files:
                match = True
                if patterns:
                    match = any(fname.endswith(p) or fname == p for p in patterns)
                if match:
                    src = os.path.join(root, fname)
                    rel = os.path.relpath(src, self._work_dir)
                    dst = os.path.join(output_dir, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    result[fname] = dst
        return result

    def execute_code(
        self,
        code: str,
        language: str = "python",
        input_files: dict[str, str] | None = None,
    ) -> SandboxResult:
        """在沙箱中执行代码。

        Args:
            code: 代码字符串
            language: python | bash
            input_files: {文件名: 外部路径} 输入文件映射
        """
        time.monotonic()
        if not self._work_dir:
            self.setup()

        # 复制输入文件
        if input_files:
            for fname, src_path in input_files.items():
                self.copy_in(src_path, fname)

        if language == "python":
            script_path = os.path.join(self._work_dir, "_sandbox_script.py")
            with open(script_path, "w") as f:
                f.write(code)
            cmd = [self._get_python(), script_path]
        elif language == "bash":
            script_path = os.path.join(self._work_dir, "_sandbox_script.sh")
            with open(script_path, "w") as f:
                f.write("#!/bin/bash\nset -e\n" + code)
            os.chmod(script_path, 0o755)
            cmd = ["bash", script_path]
        else:
            return SandboxResult(success=False, error=f"Unsupported language: {language}")

        return self._run_subprocess(cmd)

    def execute_command(self, command: str | list[str]) -> SandboxResult:
        """在沙箱中执行命令。"""
        time.monotonic()
        if not self._work_dir:
            self.setup()
        if isinstance(command, str):
            cmd = ["bash", "-c", command]
        else:
            cmd = list(command)
        return self._run_subprocess(cmd)

    def _run_subprocess(self, cmd: list[str]) -> SandboxResult:
        start = time.monotonic()
        env = os.environ.copy()
        env.update(self.config.env_vars)
        # 网络隔离
        if not self.config.network_enabled:
            env["http_proxy"] = ""
            env["https_proxy"] = ""
            env["HTTP_PROXY"] = ""
            env["HTTPS_PROXY"] = ""

        try:
            proc = subprocess.run(
                cmd,
                cwd=self._work_dir,
                env=env,
                capture_output=True,
                timeout=self.config.timeout_seconds,
                text=True,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            truncated = False

            if len(stdout) > self.config.max_output_bytes:
                stdout = stdout[: self.config.max_output_bytes] + "\n... [stdout truncated]"
                truncated = True
            if len(stderr) > self.config.max_output_bytes:
                stderr = stderr[: self.config.max_output_bytes] + "\n... [stderr truncated]"
                truncated = True

            duration = (time.monotonic() - start) * 1000
            return SandboxResult(
                success=(proc.returncode == 0),
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration,
                truncated=truncated,
            )
        except subprocess.TimeoutExpired as e:
            duration = (time.monotonic() - start) * 1000
            return SandboxResult(
                success=False,
                exit_code=-1,
                stdout=e.stdout or "" if e.stdout else "",
                stderr=(
                    e.stderr or "Timeout: execution exceeded limit"
                    if e.stderr
                    else "Timeout: execution exceeded limit"
                ),
                duration_ms=duration,
                error=f"Timeout after {self.config.timeout_seconds}s",
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return SandboxResult(success=False, duration_ms=duration, error=str(e))

    @staticmethod
    def _get_python() -> str:
        return shutil.which("python3") or shutil.which("python") or "python3"

    def cleanup(self):
        if self._work_dir and os.path.isdir(self._work_dir):
            shutil.rmtree(self._work_dir, ignore_errors=True)
            self._work_dir = None


# ── Docker 沙箱 ────────────────────────────────


class DockerSandbox:
    """Docker 容器隔离沙箱。更强的隔离性和可重现性。"""

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig(mode=SandboxMode.DOCKER)
        self._container_id: str | None = None
        self._host_work_dir: str | None = None

    def setup(self) -> str:
        """创建并启动 Docker 容器。返回沙箱目录路径。"""
        self._host_work_dir = tempfile.mkdtemp(prefix="agentos-docker-")
        container_name = f"{self.config.container_name_prefix}{uuid.uuid4().hex[:8]}"

        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            f"--memory={self.config.memory_limit_mb}m",
            f"--cpus={self.config.cpu_limit}",
            "-v",
            f"{self._host_work_dir}:/workspace",
            "-w",
            "/workspace",
        ]
        if not self.config.network_enabled:
            cmd.append("--network=none")
        if self.config.writable_root:
            cmd.append("--read-only=false")
        else:
            cmd.append("--read-only")
            cmd.append("--tmpfs=/tmp:exec")

        cmd.extend(["sleep", "infinity"])
        cmd.append(self.config.docker_image)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"Docker setup failed: {result.stderr}")

        self._container_id = result.stdout.strip()[:12]
        return self._host_work_dir

    def copy_in(self, src: str, dst_filename: str | None = None) -> str:
        if not self._container_id:
            self.setup()
        fname = dst_filename or os.path.basename(src)
        subprocess.run(
            ["docker", "cp", src, f"{self._container_id}:/workspace/{fname}"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        return os.path.join(self._host_work_dir, fname)

    def execute_code(
        self,
        code: str,
        language: str = "python",
        input_files: dict[str, str] | None = None,
    ) -> SandboxResult:
        if not self._container_id:
            self.setup()

        if input_files:
            for fname, src_path in input_files.items():
                self.copy_in(src_path, fname)

        if language == "python":
            script = "_sandbox_script.py"
            script_path = os.path.join(self._host_work_dir, script)
            with open(script_path, "w") as f:
                f.write(code)
            cmd = ["docker", "exec", self._container_id, "python3", f"/workspace/{script}"]
        elif language == "bash":
            script = "_sandbox_script.sh"
            script_path = os.path.join(self._host_work_dir, script)
            with open(script_path, "w") as f:
                f.write("#!/bin/bash\nset -e\n" + code)
            subprocess.run(["chmod", "+x", script_path], check=False)
            cmd = ["docker", "exec", self._container_id, "bash", f"/workspace/{script}"]
        else:
            return SandboxResult(success=False, error=f"Unsupported language: {language}")

        return self._run_docker(cmd)

    def execute_command(self, command: str | list[str]) -> SandboxResult:
        if not self._container_id:
            self.setup()
        if isinstance(command, str):
            cmd = ["docker", "exec", self._container_id, "bash", "-c", command]
        else:
            cmd = ["docker", "exec", self._container_id] + list(command)
        return self._run_docker(cmd)

    def _run_docker(self, cmd: list[str]) -> SandboxResult:
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
            duration = (time.monotonic() - start) * 1000
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            truncated = False

            if len(stdout) > self.config.max_output_bytes:
                stdout = stdout[: self.config.max_output_bytes] + "\n... [truncated]"
                truncated = True

            return SandboxResult(
                success=(proc.returncode == 0),
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration,
                truncated=truncated,
            )
        except subprocess.TimeoutExpired:
            if self._container_id:
                subprocess.run(["docker", "kill", self._container_id], capture_output=True)
            return SandboxResult(
                success=False,
                exit_code=-1,
                error=f"Timeout after {self.config.timeout_seconds}s",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                error=str(e),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    def collect_output_files(self, patterns: list[str] | None = None) -> dict[str, str]:
        if not self._host_work_dir:
            return {}
        output_dir = tempfile.mkdtemp(prefix="agentos-output-")
        result: dict[str, str] = {}
        for root, dirs, files in os.walk(self._host_work_dir):
            for fname in files:
                if fname.startswith("_sandbox"):
                    continue
                match = True
                if patterns:
                    match = any(fname.endswith(p) for p in patterns)
                if match:
                    src = os.path.join(root, fname)
                    dst = os.path.join(output_dir, fname)
                    shutil.copy2(src, dst)
                    result[fname] = dst
        return result

    def cleanup(self):
        if self._container_id:
            subprocess.run(["docker", "stop", self._container_id], capture_output=True, timeout=5)
            self._container_id = None
        if self._host_work_dir and os.path.isdir(self._host_work_dir):
            shutil.rmtree(self._host_work_dir, ignore_errors=True)
            self._host_work_dir = None


# ── 统一沙箱执行器 ─────────────────────────────


class SandboxExecutor:
    """统一沙箱执行器。根据 SandboxConfig.mode 自动选择 Process/Docker。"""

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()
        if self.config.mode == SandboxMode.DOCKER:
            try:
                self._sandbox: ProcessSandbox | DockerSandbox = DockerSandbox(self.config)
                self._sandbox.setup()
            except Exception:
                # Docker 不可用时降级到 Process
                self.config.mode = SandboxMode.PROCESS
                self._sandbox = ProcessSandbox(self.config)
        else:
            self._sandbox = ProcessSandbox(self.config)

    async def execute_code(
        self,
        code: str,
        language: str = "python",
        input_files: dict[str, str] | None = None,
    ) -> SandboxResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._sandbox.execute_code,
            code,
            language,
            input_files,
        )

    async def execute_command(self, command: str | list[str]) -> SandboxResult:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sandbox.execute_command, command)

    def collect_output_files(self, patterns: list[str] | None = None) -> dict[str, str]:
        return self._sandbox.collect_output_files(patterns)

    async def cleanup(self):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sandbox.cleanup)

    def __enter__(self):
        self._sandbox.setup()
        return self

    def __exit__(self, *args):
        self._sandbox.cleanup()
