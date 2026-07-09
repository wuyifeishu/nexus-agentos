"""
AgentOS v0.70 — 插件系统: 注册中心。
基因来源: Docker插件体系 + VSCode扩展市场

插件清单格式:
- manifest.json: 插件元数据
- 入口点: Python类路径
- 依赖声明: 插件间依赖
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PluginType(StrEnum):
    """插件类型枚举。"""

    PROVIDER = "provider"  # 模型provider (如GeminiAdapter)
    TOOL = "tool"  # 工具扩展
    MIDDLEWARE = "middleware"  # 请求/响应拦截器
    SINK = "sink"  # 输出后端 (观测/日志/存储)
    HOOK = "hook"  # 生命周期钩子
    CUSTOM = "custom"  # 自定义


class PluginStatus(StrEnum):
    """插件状态。"""

    LOADED = "loaded"
    INITIALIZED = "initialized"
    ACTIVE = "active"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class PluginManifest:
    """插件清单 — 描述插件能力与依赖。"""

    name: str
    version: str
    description: str = ""
    author: str = ""
    plugin_type: PluginType = PluginType.CUSTOM
    entry_point: str = ""  # fully qualified class path
    dependencies: list[str] = field(default_factory=list)
    optional_dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    config_schema: dict = field(default_factory=dict)
    priority: int = 50  # 0=最高, 100=最低
    homepage: str = ""
    license: str = "MIT"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "plugin_type": self.plugin_type.value,
            "entry_point": self.entry_point,
            "dependencies": self.dependencies,
            "tags": self.tags,
        }


@dataclass
class RegisteredPlugin:
    """已注册的插件实例。"""

    manifest: PluginManifest
    instance: Any = None
    status: PluginStatus = PluginStatus.LOADED
    load_time_ms: float = 0.0
    error: str | None = None


class PluginRegistry:
    """
    插件注册中心 — 统一管理所有已注册插件。
    支持: CRUD、查询、按标签/类型检索、依赖解析。
    """

    def __init__(self):
        self._plugins: dict[str, RegisteredPlugin] = {}
        self._hooks: dict[str, list[Callable]] = {}  # event → list of callbacks

    # ── CRUD ─────────────────────────────────────

    def register(self, manifest: PluginManifest, instance: Any = None) -> RegisteredPlugin:
        """注册插件（覆盖已有同名插件）。"""
        registered = RegisteredPlugin(manifest=manifest, instance=instance)
        self._plugins[manifest.name] = registered
        return registered

    def unregister(self, name: str) -> bool:
        if name in self._plugins:
            del self._plugins[name]
            return True
        return False

    def get(self, name: str) -> RegisteredPlugin | None:
        return self._plugins.get(name)

    def get_instance(self, name: str) -> Any:
        """获取插件实例。"""
        registered = self._plugins.get(name)
        return registered.instance if registered else None

    # ── Query ────────────────────────────────────

    def list_all(self) -> list[RegisteredPlugin]:
        return list(self._plugins.values())

    def list_names(self) -> list[str]:
        return list(self._plugins.keys())

    def by_type(self, plugin_type: PluginType) -> list[RegisteredPlugin]:
        return [p for p in self._plugins.values() if p.manifest.plugin_type == plugin_type]

    def by_tag(self, tag: str) -> list[RegisteredPlugin]:
        return [p for p in self._plugins.values() if tag in p.manifest.tags]

    def by_status(self, status: PluginStatus) -> list[RegisteredPlugin]:
        return [p for p in self._plugins.values() if p.status == status]

    # ── Dependency Resolution ────────────────────

    def resolve_order(self, names: list[str]) -> list[str]:
        """拓扑排序解析插件加载顺序。"""
        adj: dict[str, list[str]] = {n: [] for n in names}
        for name in names:
            p = self._plugins.get(name)
            if p:
                adj[name] = [d for d in p.manifest.dependencies if d in names]

        # Kahn's algorithm
        in_degree = {n: 0 for n in names}
        for deps in adj.values():
            for d in deps:
                in_degree[d] += 1

        queue = [n for n in names if in_degree[n] == 0]
        order = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for dep in adj.get(n, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if len(order) != len(names):
            missing = set(names) - set(order)
            raise DependencyCycleError(f"循环依赖或缺失依赖: {missing}")

        return order

    def check_requirements(self, name: str) -> list[str]:
        """检查某插件的依赖是否满足。返回缺失的依赖列表。"""
        p = self._plugins.get(name)
        if not p:
            return [name]
        missing = []
        for dep in p.manifest.dependencies:
            if dep not in self._plugins:
                missing.append(dep)
        return missing

    # ── Hook System ──────────────────────────────

    def register_hook(self, event: str, callback: Callable):
        """注册事件钩子。"""
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)

    async def emit_hook(self, event: str, **kwargs) -> list[Any]:
        """触发事件钩子，返回所有回调结果。"""
        results = []
        for cb in self._hooks.get(event, []):
            try:
                import asyncio

                if asyncio.iscoroutinefunction(cb):
                    results.append(await cb(**kwargs))
                else:
                    results.append(cb(**kwargs))
            except Exception as e:
                results.append({"error": str(e)})
        return results

    def hook_names(self) -> list[str]:
        return list(self._hooks.keys())

    # ── Info ─────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._plugins)

    def summary(self) -> str:
        by_type = {}
        for p in self._plugins.values():
            t = p.manifest.plugin_type.value
            by_type[t] = by_type.get(t, 0) + 1
        lines = [f"共 {self.count} 个插件"]
        for t, c in sorted(by_type.items()):
            lines.append(f"  {t}: {c}")
        return "\n".join(lines)


class DependencyCycleError(Exception):
    """插件依赖循环异常。"""

