"""
AgentOS v0.70 — 插件生命周期管理器。
基因来源: Kubernetes Pod Lifecycle + Spring Boot Actuator

生命周期钩子:
- on_load()       → 插件加载完成
- on_init(config) → 初始化配置
- on_start()      → 开始工作
- on_stop()       → 优雅关闭
- on_error(e)     → 异常处理
- health_check()  → 健康检查
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agentos.plugins.registry import PluginRegistry, RegisteredPlugin, PluginStatus


# ── Abstract Plugin Base ─────────────────────────

class LifecyclePlugin(ABC):
    """插件基类 — 实现标准生命周期钩子。"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._started_at: float = 0.0
        self._error_count: int = 0

    @property
    def uptime_seconds(self) -> float:
        if self._started_at == 0:
            return 0.0
        return time.time() - self._started_at

    async def on_load(self):
        """插件加载后调用。"""

    async def on_init(self, config: dict):
        """初始化配置后调用。"""
        self.config = config

    async def on_start(self):
        """开始工作时调用。"""
        self._started_at = time.time()

    async def on_stop(self):
        """优雅关闭时调用。"""
        self._started_at = 0.0

    async def on_error(self, error: Exception) -> bool:
        """
        异常处理钩子。返回True表示已处理（可恢复），False表示致命错误。
        """
        self._error_count += 1
        return False

    async def health_check(self) -> HealthStatus:
        """健康检查 — 子类可覆盖。"""
        return HealthStatus.HEALTHY


@dataclass
class PluginHealth:
    """插件健康状态摘要。"""
    plugin_name: str
    status: str
    uptime_seconds: float
    error_count: int
    last_error: str


class HealthStatus:
    """插件健康状态。"""
    status: str = "healthy"  # healthy | degraded | unhealthy
    details: dict = field(default_factory=dict)
    uptime_seconds: float = 0.0
    error_count: int = 0

    @property
    def is_healthy(self) -> bool:
        return self.status == "healthy"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "details": self.details,
            "uptime_seconds": self.uptime_seconds,
            "error_count": self.error_count,
        }


from dataclasses import dataclass, field


@dataclass
class LifecycleReport:
    """插件生命周期报告。"""

    plugin_name: str
    status: PluginStatus
    load_time_ms: float = 0.0
    init_time_ms: float = 0.0
    uptime_seconds: float = 0.0
    health: HealthStatus | None = None
    error: str | None = None


# ── Lifecycle Manager ────────────────────────────

class LifecycleManager:
    """
    生命周期管理器 — 协调所有插件的init/start/stop。
    支持: 批量初始化、健康检查轮询、优雅降级。
    """

    def __init__(self, registry: PluginRegistry):
        self.registry = registry
        self._reports: dict[str, LifecycleReport] = {}
        self._health_check_task: asyncio.Task | None = None

    async def init_all(self, configs: dict[str, dict] | None = None):
        """初始化所有已注册的LOADED状态插件。"""
        configs = configs or {}
        plugins = self.registry.by_status(PluginStatus.LOADED)

        for rp in plugins:
            if rp.instance and isinstance(rp.instance, LifecyclePlugin):
                start = time.time()
                try:
                    cfg = configs.get(rp.manifest.name, {})
                    await rp.instance.on_init(cfg)
                    rp.status = PluginStatus.INITIALIZED
                    init_ms = (time.time() - start) * 1000
                    self._reports[rp.manifest.name] = LifecycleReport(
                        plugin_name=rp.manifest.name,
                        status=PluginStatus.INITIALIZED,
                        load_time_ms=rp.load_time_ms,
                        init_time_ms=init_ms,
                    )
                except Exception as e:
                    rp.status = PluginStatus.ERROR
                    rp.error = str(e)
                    await self._handle_error(rp, e)

    async def start_all(self):
        """启动所有INITIALIZED状态的插件。"""
        plugins = self.registry.by_status(PluginStatus.INITIALIZED)

        for rp in plugins:
            await self.start_one(rp.manifest.name)

    async def start_one(self, name: str) -> LifecycleReport:
        rp = self.registry.get(name)
        if not rp:
            raise KeyError(f"Plugin '{name}' not found")
        if rp.status not in (PluginStatus.INITIALIZED, PluginStatus.STOPPED):
            raise RuntimeError(f"Cannot start plugin '{name}' in status {rp.status}")

        try:
            if rp.instance and isinstance(rp.instance, LifecyclePlugin):
                await rp.instance.on_start()
            rp.status = PluginStatus.ACTIVE
            rp.error = None
            report = self._reports.get(name, LifecycleReport(plugin_name=name, status=PluginStatus.ACTIVE))
            report.status = PluginStatus.ACTIVE
            report.uptime_seconds = rp.instance.uptime_seconds if rp.instance and isinstance(rp.instance, LifecyclePlugin) else 0
            self._reports[name] = report
            return report
        except Exception as e:
            rp.status = PluginStatus.ERROR
            rp.error = str(e)
            return LifecycleReport(plugin_name=name, status=PluginStatus.ERROR, error=str(e))

    async def stop_all(self, graceful: bool = True):
        """停止所有ACTIVE插件。"""
        plugins = self.registry.by_status(PluginStatus.ACTIVE)

        for rp in plugins:
            await self.stop_one(rp.manifest.name, graceful)

    async def stop_one(self, name: str, graceful: bool = True):
        rp = self.registry.get(name)
        if not rp:
            return

        rp.status = PluginStatus.STOPPING
        try:
            if rp.instance and isinstance(rp.instance, LifecyclePlugin):
                await rp.instance.on_stop()
        except Exception as e:
            rp.error = str(e)
        finally:
            rp.status = PluginStatus.STOPPED
            if name in self._reports:
                self._reports[name].status = PluginStatus.STOPPED

    async def health_check_all(self) -> dict[str, HealthStatus]:
        """对所有ACTIVE插件执行健康检查。"""
        results = {}
        plugins = self.registry.by_status(PluginStatus.ACTIVE)

        for rp in plugins:
            if rp.instance and isinstance(rp.instance, LifecyclePlugin):
                try:
                    health = await rp.instance.health_check()
                except Exception as e:
                    health = HealthStatus(
                        status="unhealthy",
                        details={"error": str(e)},
                        error_count=rp.instance._error_count if rp.instance else 0,
                    )
                health.uptime_seconds = rp.instance.uptime_seconds if rp.instance else 0
                results[rp.manifest.name] = health

        return results

    def start_health_polling(self, interval_seconds: float = 30.0):
        """启动后台健康检查轮询。"""
        async def _poll():
            while True:
                try:
                    await self.health_check_all()
                except Exception:
                    pass
                await asyncio.sleep(interval_seconds)

        self._health_check_task = asyncio.ensure_future(_poll())

    def stop_health_polling(self):
        if self._health_check_task:
            self._health_check_task.cancel()
            self._health_check_task = None

    def report(self) -> list[LifecycleReport]:
        """获取所有插件的生命周期报告。"""
        reports = list(self._reports.values())
        # Add any not tracked in _reports
        tracked = {r.plugin_name for r in reports}
        for rp in self.registry.list_all():
            if rp.manifest.name not in tracked:
                reports.append(LifecycleReport(
                    plugin_name=rp.manifest.name,
                    status=rp.status,
                    load_time_ms=rp.load_time_ms,
                    error=rp.error,
                ))
        return reports

    def summary(self) -> str:
        reports = self.report()
        lines = [f"共 {len(reports)} 个插件"]
        for r in reports:
            lines.append(f"  [{r.status.value}] {r.plugin_name} (load:{r.load_time_ms:.0f}ms, init:{r.init_time_ms:.0f}ms)")
            if r.error:
                lines.append(f"    error: {r.error}")
        return "\n".join(lines)

    async def _handle_error(self, rp: RegisteredPlugin, error: Exception):
        if rp.instance and isinstance(rp.instance, LifecyclePlugin):
            try:
                handled = await rp.instance.on_error(error)
                if handled:
                    rp.error = None
            except Exception:
                pass
