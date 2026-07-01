"""
子Agent父子通信 — 状态共享、心跳、生命周期管理。
父Agent通过 ChildHandle 管控子Agent；子Agent通过 ChildContext 向父Agent报告。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable


class ChildStatus(str, Enum):
    """子Agent运行状态。"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class ChildHeartbeat:
    """子Agent心跳包。"""
    agent_id: str
    status: ChildStatus = ChildStatus.RUNNING
    progress: float = 0.0          # 0.0 ~ 1.0
    current_step: str = ""
    message: str = ""
    iteration: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChildInfo:
    """子Agent元信息（父Agent侧）。"""
    agent_id: str
    task: str
    mode: str
    status: ChildStatus = ChildStatus.IDLE
    spawned_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    heartbeat_interval: float = 2.0     # 期望心跳间隔（秒）
    timeout: float | None = None        # 超时（秒），None=无超时
    progress: float = 0.0
    current_step: str = ""
    iterations: int = 0
    error: str | None = None
    output: str = ""


class SharedState:
    """父子共享状态（线程安全）。"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._data: dict[str, Any] = {}

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = value

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            return self._data.get(key, default)

    async def update(self, mapping: dict[str, Any]) -> None:
        async with self._lock:
            self._data.update(mapping)

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return dict(self._data)

    def set_sync(self, key: str, value: Any) -> None:
        """同步写（非协程场景）。"""
        self._data[key] = value

    def get_sync(self, key: str, default: Any = None) -> Any:
        """同步读（非协程场景）。"""
        return self._data.get(key, default)


class ChildContext:
    """子Agent视角 — 向父Agent报告状态、检查控制信号。"""

    def __init__(
        self,
        agent_id: str,
        heartbeat_callback: Callable[[ChildHeartbeat], Awaitable[None]] | None = None,
        on_cancel: Callable[[], bool] | None = None,
        on_pause: Callable[[], Awaitable[None]] | None = None,
        shared_state: SharedState | None = None,
    ):
        self.agent_id = agent_id
        self._heartbeat_cb = heartbeat_callback
        self._cancel_check = on_cancel or (lambda: False)
        self._pause_cb = on_pause or (lambda: asyncio.sleep(0))
        self.shared_state = shared_state or SharedState()
        self._cancelled = False
        self._paused = False
        self._progress = 0.0
        self._current_step = ""
        self._iteration = 0

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def progress(self) -> float:
        return self._progress

    async def report_progress(
        self,
        progress: float,
        step: str = "",
        message: str = "",
    ) -> None:
        """子Agent报告进度。"""
        self._progress = max(0.0, min(1.0, progress))
        self._current_step = step
        if self._heartbeat_cb:
            await self._heartbeat_cb(ChildHeartbeat(
                agent_id=self.agent_id,
                status=ChildStatus.RUNNING,
                progress=self._progress,
                current_step=step,
                message=message,
                iteration=self._iteration,
            ))

    async def step(self, iteration: int, step: str = "") -> None:
        """子Agent标记一个执行步。"""
        self._iteration = iteration
        self._current_step = step

    async def check_control(self) -> ChildStatus:
        """检查父Agent控制信号，返回应执行的操作。"""
        if self._cancel_check():
            self._cancelled = True
            return ChildStatus.CANCELLED
        if self._paused:
            await self._pause_cb()
            return ChildStatus.PAUSED
        return ChildStatus.RUNNING

    async def send_heartbeat(self, message: str = "") -> None:
        """子Agent发送心跳。"""
        if self._heartbeat_cb:
            await self._heartbeat_cb(ChildHeartbeat(
                agent_id=self.agent_id,
                status=ChildStatus.RUNNING,
                progress=self._progress,
                current_step=self._current_step,
                message=message,
                iteration=self._iteration,
            ))

    async def done(self, output: str = "") -> None:
        """子Agent标记完成。"""
        if self._heartbeat_cb:
            await self._heartbeat_cb(ChildHeartbeat(
                agent_id=self.agent_id,
                status=ChildStatus.COMPLETED,
                progress=1.0,
                current_step=self._current_step,
                message=output,
                iteration=self._iteration,
            ))

    async def fail(self, error: str) -> None:
        """子Agent报告失败。"""
        if self._heartbeat_cb:
            await self._heartbeat_cb(ChildHeartbeat(
                agent_id=self.agent_id,
                status=ChildStatus.FAILED,
                progress=self._progress,
                current_step=self._current_step,
                message=error,
                iteration=self._iteration,
            ))


class ChildHandle:
    """父Agent视角 — 管控一个子Agent。"""

    def __init__(
        self,
        agent_id: str,
        task: str,
        mode: str,
        timeout: float | None = None,
        heartbeat_interval: float = 2.0,
    ):
        self.info = ChildInfo(
            agent_id=agent_id,
            task=task,
            mode=mode,
            heartbeat_interval=heartbeat_interval,
            timeout=timeout,
        )
        self._cancel_flag = False
        self._pause_flag = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # 默认未暂停
        self.shared_state = SharedState()
        self.context: ChildContext | None = None

    @property
    def agent_id(self) -> str:
        return self.info.agent_id

    @property
    def status(self) -> ChildStatus:
        return self.info.status

    def create_context(self) -> ChildContext:
        """为子Agent创建 ChildContext。"""
        ctx = ChildContext(
            agent_id=self.agent_id,
            heartbeat_callback=self._receive_heartbeat,
            on_cancel=self._is_cancelled,
            on_pause=self._wait_if_paused,
            shared_state=self.shared_state,
        )
        self.context = ctx
        return ctx

    async def _receive_heartbeat(self, hb: ChildHeartbeat) -> None:
        """接收子Agent心跳。"""
        self.info.last_heartbeat = time.time()
        self.info.status = hb.status
        self.info.progress = hb.progress
        self.info.current_step = hb.current_step
        self.info.iterations = hb.iteration
        if hb.status == ChildStatus.FAILED:
            self.info.error = hb.message
        elif hb.status == ChildStatus.COMPLETED:
            self.info.output = hb.message

    def _is_cancelled(self) -> bool:
        return self._cancel_flag

    async def _wait_if_paused(self) -> None:
        await self._resume_event.wait()

    async def cancel(self) -> None:
        """取消子Agent。"""
        self._cancel_flag = True
        self.info.status = ChildStatus.CANCELLED

    async def pause(self) -> None:
        """暂停子Agent。"""
        self._pause_flag = True
        self._resume_event.clear()
        self.info.status = ChildStatus.PAUSED
        if self.context:
            self.context._paused = True

    async def resume(self) -> None:
        """恢复子Agent。"""
        self._pause_flag = False
        self._resume_event.set()
        self.info.status = ChildStatus.RUNNING
        if self.context:
            self.context._paused = False

    def check_timeout(self) -> bool:
        """检查是否超时，返回 True 表示已超时。"""
        if self.info.timeout is None:
            return False
        elapsed = time.time() - self.info.spawned_at
        return elapsed > self.info.timeout

    def check_heartbeat_timeout(self) -> bool:
        """检查心跳是否超时（3倍心跳间隔无响应视为失联）。"""
        elapsed = time.time() - self.info.last_heartbeat
        return elapsed > self.info.heartbeat_interval * 3

    def get_status(self) -> dict[str, Any]:
        """获取子Agent状态摘要。"""
        return {
            "agent_id": self.info.agent_id,
            "status": self.info.status.value,
            "progress": self.info.progress,
            "current_step": self.info.current_step,
            "iterations": self.info.iterations,
            "elapsed": time.time() - self.info.spawned_at,
            "error": self.info.error,
        }
