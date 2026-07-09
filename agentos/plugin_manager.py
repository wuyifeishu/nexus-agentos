"""
AgentOS 插件系统兼容层 — 统一入口，委托到 agentos.plugins 模块。

v1.14.3 版本存在两套并行插件体系（顶层 plugin_manager.py + plugins/ 目录），
v1.14.6 将 plugin_manager.py 改为 plugins/ 的兼容性包装，消除碎片化。
"""

from __future__ import annotations

import warnings

from agentos.plugins import (
    AuditLoggerPlugin,
    BasePlugin,
    HealthCheckPlugin,
    PluginFileWatcher,
    PluginManifest,
    PluginRegistry,
    PluginStatus,
    create_registry_with_builtins,
)

# ── 兼容性导出 ────────────────────────────
# 保留旧 PluginManager 接口但内部委托到 PluginRegistry


class PluginManager:
    """兼容性包装：旧 PluginManager API 委托到 PluginRegistry。

    Deprecated: 请直接使用 agentos.plugins.PluginRegistry。
    """

    def __init__(self, plugin_dirs: list[str] | None = None):
        warnings.warn(
            "agentos.plugin_manager.PluginManager is deprecated. "
            "Use agentos.plugins.PluginRegistry directly.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._registry = PluginRegistry()
        self._plugin_dirs = plugin_dirs or ["./plugins"]

    def discover(self):
        discovered = []
        for d in self._plugin_dirs:
            names = self._registry.discover(d)
            discovered.extend(
                PluginInfo(
                    name=name,
                    version=self._registry._manifests[name].version,
                    description=self._registry._manifests[name].description,
                    entry_point=self._registry._manifests[name].entry_point,
                )
                for name in names
            )
        return discovered

    def register(self, plugin):
        if isinstance(plugin, BasePlugin):
            return self._registry.register(plugin)
        elif isinstance(plugin, PluginInfo):
            manifest = PluginManifest(
                name=plugin.name,
                version=plugin.version,
                description=plugin.description,
                entry_point=plugin.entry_point,
            )
            self._registry._manifests[plugin.name] = manifest
        return True

    def load(self, name: str):
        return self._registry.load(name)

    def unload(self, name: str):
        plugin = self._registry.get_plugin(name)
        if plugin:
            plugin.unload()

    def add_hook(self, hook_name, callback):
        pass  # PluginRegistry uses middleware model instead

    def call_hook(self, hook_name, *args, **kwargs):
        pass  # PluginRegistry uses middleware model instead

    @property
    def loaded_plugins(self) -> list[str]:
        return [n for n, p in self._registry._plugins.items() if p.status == PluginStatus.ACTIVE]


# ── 兼容类型 ───────────────────────────────

from dataclasses import dataclass  # noqa: E402


@dataclass
class PluginInfo:
    """旧版 PluginInfo 兼容类型。"""

    name: str
    version: str
    description: str
    entry_point: str
    author: str = ""
    path: str = ""


# ── 公开 API ───────────────────────────────

__all__ = [
    # 新 API（推荐）
    "PluginRegistry",
    "PluginManifest",
    "PluginStatus",
    "BasePlugin",
    "PluginFileWatcher",
    "AuditLoggerPlugin",
    "HealthCheckPlugin",
    "create_registry_with_builtins",
    # 兼容旧 API
    "PluginManager",
    "PluginInfo",
]
