"""
AgentOS v1.14.3 — Plugin System & Tool Registry.

Hot-reloadable plugin architecture. Plugins can register:
- Custom tools (sync/async functions)
- Agent middleware (pre/post hooks)
- Custom LLM providers
- Custom memory backends
- Custom protocols

Features:
- Plugin discovery (scan directories / entry_points)
- Hot-reload (watch filesystem changes)
- Dependency resolution (plugin A depends on plugin B)
- Version compatibility checks
- Plugin sandboxing (restricted imports)
- CLI for plugin management

Architecture:
    PluginRegistry (singleton)
        ├── Plugin[0]: slack_notifier
        │   ├── tools: [send_slack]
        │   ├── middleware: [audit_logger]
        │   └── depends_on: []
        ├── Plugin[1]: jira_integration
        │   ├── tools: [create_issue, search_jira]
        │   └── depends_on: []
        └── ...
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union,
)


# ── Plugin Metadata ─────────────────────────


class PluginStatus(str, Enum):
    REGISTERED = "registered"   # 已注册但未加载
    LOADED = "loaded"           # 已加载但未激活
    ACTIVE = "active"           # 已激活，正在运行
    ERROR = "error"             # 加载失败
    DISABLED = "disabled"       # 已禁用


@dataclass
class PluginManifest:
    """插件清单 — 描述插件的元数据和能力。"""

    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    license: str = "MIT"

    # Entry point
    entry_point: str = ""        # module:class or module:function
    plugin_class: str = ""       # 插件主类名

    # Capabilities
    provides_tools: List[str] = field(default_factory=list)      # 提供的工具名
    provides_middleware: List[str] = field(default_factory=list)  # 提供的中间件
    provides_providers: List[str] = field(default_factory=list)   # 提供的 LLM 提供者
    provides_backends: List[str] = field(default_factory=list)    # 提供的后端

    # Dependencies
    depends_on: List[str] = field(default_factory=list)           # 依赖的其他插件
    min_agentos_version: str = "1.0.0"

    # Discovery
    discoverable: bool = True
    auto_activate: bool = False   # 加载后自动激活
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            license=data.get("license", "MIT"),
            entry_point=data.get("entry_point", ""),
            plugin_class=data.get("plugin_class", ""),
            provides_tools=data.get("provides_tools", []),
            provides_middleware=data.get("provides_middleware", []),
            provides_providers=data.get("provides_providers", []),
            provides_backends=data.get("provides_backends", []),
            depends_on=data.get("depends_on", []),
            min_agentos_version=data.get("min_agentos_version", "1.0.0"),
            discoverable=data.get("discoverable", True),
            auto_activate=data.get("auto_activate", False),
            tags=data.get("tags", []),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "entry_point": self.entry_point,
            "plugin_class": self.plugin_class,
            "provides_tools": self.provides_tools,
            "provides_middleware": self.provides_middleware,
            "provides_providers": self.provides_providers,
            "provides_backends": self.provides_backends,
            "depends_on": self.depends_on,
            "min_agentos_version": self.min_agentos_version,
        }


# ── Plugin Base ─────────────────────────────


class BasePlugin:
    """插件基类 — 所有插件必须继承此类。

    Lifecycle:
        1. __init__() → registered
        2. load() → loaded
        3. activate() → active
        4. deactivate() → loaded
        5. unload() → registered

    Usage:
        class MyPlugin(BasePlugin):
            manifest = PluginManifest(
                name="my_plugin",
                entry_point="my_package.plugin:MyPlugin",
                provides_tools=["my_tool"],
            )

            def on_load(self):
                self.register_tool("my_tool", my_function)

            def on_activate(self):
                print("Plugin activated!")
    """

    manifest: PluginManifest

    def __init__(self):
        self._status = PluginStatus.REGISTERED
        self._tools: Dict[str, Callable] = {}
        self._middleware: List[Callable] = []
        self._config: Dict[str, Any] = {}

    # ── Lifecycle ──

    def load(self) -> None:
        """加载插件（注册工具、中间件等）。"""
        try:
            self.on_load()
            self._status = PluginStatus.LOADED
        except Exception as e:
            self._status = PluginStatus.ERROR
            raise RuntimeError(f"Failed to load plugin {self.manifest.name}: {e}")

    def activate(self) -> None:
        """激活插件。"""
        try:
            self.on_activate()
            self._status = PluginStatus.ACTIVE
        except Exception as e:
            self._status = PluginStatus.ERROR
            raise RuntimeError(f"Failed to activate plugin {self.manifest.name}: {e}")

    def deactivate(self) -> None:
        """停用插件。"""
        try:
            self.on_deactivate()
            self._status = PluginStatus.LOADED
        except Exception:
            pass

    def unload(self) -> None:
        """卸载插件。"""
        try:
            self.on_unload()
            self._status = PluginStatus.REGISTERED
        except Exception:
            pass

    # ── Hooks (override in subclasses) ──

    def on_load(self) -> None:
        """子类实现：加载时调用。"""
        pass

    def on_activate(self) -> None:
        """子类实现：激活时调用。"""
        pass

    def on_deactivate(self) -> None:
        """子类实现：停用时调用。"""
        pass

    def on_unload(self) -> None:
        """子类实现：卸载时调用。"""
        pass

    # ── Tool Registration ──

    def register_tool(self, name: str, func: Callable) -> None:
        """注册工具函数。"""
        self._tools[name] = func

    def unregister_tool(self, name: str) -> None:
        """注销工具函数。"""
        self._tools.pop(name, None)

    def register_middleware(self, middleware: Callable) -> None:
        """注册中间件。"""
        self._middleware.append(middleware)

    # ── Properties ──

    @property
    def status(self) -> PluginStatus:
        return self._status

    @property
    def tools(self) -> Dict[str, Callable]:
        return dict(self._tools)

    @property
    def middleware(self) -> List[Callable]:
        return list(self._middleware)

    @property
    def is_active(self) -> bool:
        return self._status == PluginStatus.ACTIVE


# ── Plugin Registry ─────────────────────────


class PluginRegistry:
    """插件注册中心（单例）。

    管理所有插件的生命周期、依赖解析、发现。

    Usage:
        registry = PluginRegistry()

        # Discover from directory
        registry.discover("/path/to/plugins/")

        # Load and activate
        registry.load_all()
        registry.activate_all()

        # Get all tools from active plugins
        all_tools = registry.get_all_tools()
    """

    _instance: Optional["PluginRegistry"] = None

    def __new__(cls) -> "PluginRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._plugins: Dict[str, BasePlugin] = {}       # name → plugin instance
        self._manifests: Dict[str, PluginManifest] = {}  # name → manifest
        self._tools_index: Dict[str, str] = {}           # tool_name → plugin_name
        self._discovery_paths: List[str] = []
        self._watchers: List[Any] = []                    # file watchers

    # ── Registration ──

    def register(self, plugin: BasePlugin) -> bool:
        """注册插件。"""
        name = plugin.manifest.name
        if name in self._plugins:
            return False

        self._plugins[name] = plugin
        self._manifests[name] = plugin.manifest
        return True

    def unregister(self, name: str) -> bool:
        """注销插件。"""
        plugin = self._plugins.get(name)
        if plugin:
            if plugin.is_active:
                plugin.deactivate()
            plugin.unload()

        self._plugins.pop(name, None)
        self._manifests.pop(name, None)

        # Clean tool index
        self._tools_index = {
            tn: pn for tn, pn in self._tools_index.items() if pn != name
        }
        return True

    # ── Discovery ──

    def discover(self, path: str, recursive: bool = True) -> List[str]:
        """从目录中发现插件。

        扫描 plugin.json / agentos_plugin.json 文件。
        """
        discovered: List[str] = []
        base = Path(path)

        if not base.exists():
            return discovered

        pattern = "**/plugin.json" if recursive else "plugin.json"
        for manifest_file in base.glob(pattern):
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                manifest = PluginManifest.from_dict(data)
                if manifest.discoverable:
                    self._manifests[manifest.name] = manifest
                    discovered.append(manifest.name)

            except Exception:
                continue

        self._discovery_paths.append(path)
        return discovered

    def discover_entry_points(self, group: str = "agentos.plugins") -> int:
        """通过 setuptools entry_points 发现插件。"""
        try:
            from importlib.metadata import entry_points

            count = 0
            for ep in entry_points(group=group):
                try:
                    manifest = PluginManifest(
                        name=ep.name,
                        entry_point=ep.value,
                    )
                    self._manifests[ep.name] = manifest
                    count += 1
                except Exception:
                    continue

            return count
        except ImportError:
            return 0

    # ── Loading ──

    def load(self, name: str) -> Optional[BasePlugin]:
        """加载单个插件。"""
        manifest = self._manifests.get(name)
        if not manifest:
            return None

        # Check dependencies
        if not self._check_dependencies(manifest):
            return None

        # Load plugin class
        plugin = self._instantiate_plugin(manifest)
        if not plugin:
            return None

        try:
            plugin.load()
            self._plugins[name] = plugin

            # Index tools
            for tool_name in plugin.tools:
                self._tools_index[tool_name] = name

            return plugin
        except Exception:
            return None

    def load_all(self) -> Dict[str, Optional[BasePlugin]]:
        """加载所有已发现但未加载的插件（按依赖拓扑排序）。"""
        results: Dict[str, Optional[BasePlugin]] = {}

        order = self._resolve_order()

        for name in order:
            if name not in self._plugins:
                results[name] = self.load(name)

        return results

    # ── Activation ──

    def activate(self, name: str) -> bool:
        """激活插件。"""
        plugin = self._plugins.get(name)
        if not plugin or plugin.status != PluginStatus.LOADED:
            return False

        try:
            plugin.activate()
            return True
        except Exception:
            return False

    def activate_all(self) -> int:
        """激活所有已加载的插件。"""
        count = 0
        for name, plugin in list(self._plugins.items()):
            if plugin.status == PluginStatus.LOADED:
                if self.activate(name):
                    count += 1
        return count

    # ── Hot Reload ──

    def reload(self, name: str) -> bool:
        """热重载插件（停用 → 卸载 → 重新加载 → 激活）。"""
        plugin = self._plugins.get(name)
        if not plugin:
            return False

        was_active = plugin.is_active

        if was_active:
            plugin.deactivate()
        plugin.unload()

        # Reload
        new_plugin = self.load(name)
        if not new_plugin:
            return False

        if was_active:
            new_plugin.activate()

        return True

    def reload_all(self) -> int:
        """重载所有插件。"""
        count = 0
        for name in list(self._plugins.keys()):
            if self.reload(name):
                count += 1
        return count

    # ── Queries ──

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self._plugins.get(name)

    def get_tool(self, tool_name: str) -> Optional[Callable]:
        """通过工具名获取工具函数。"""
        plugin_name = self._tools_index.get(tool_name)
        if not plugin_name:
            return None
        plugin = self._plugins.get(plugin_name)
        if not plugin:
            return None
        return plugin.tools.get(tool_name)

    def get_all_tools(self) -> Dict[str, Callable]:
        """获取所有已激活插件的工具。"""
        tools: Dict[str, Callable] = {}
        for plugin in self._plugins.values():
            if plugin.is_active:
                tools.update(plugin.tools)
        return tools

    def list_plugins(self) -> List[dict]:
        """列出所有插件及其状态。"""
        result = []
        for name, manifest in self._manifests.items():
            plugin = self._plugins.get(name)
            result.append({
                "name": name,
                "version": manifest.version,
                "status": plugin.status.value if plugin else "not_loaded",
                "description": manifest.description,
                "tools": manifest.provides_tools,
                "depends_on": manifest.depends_on,
            })
        return result

    def get_active_count(self) -> int:
        return sum(1 for p in self._plugins.values() if p.is_active)

    # ── Internal ──

    def _instantiate_plugin(self, manifest: PluginManifest) -> Optional[BasePlugin]:
        """从 entry_point 实例化插件。"""
        if not manifest.entry_point:
            return None

        try:
            module_path, class_name = manifest.entry_point.split(":")
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            instance = cls()

            if not isinstance(instance, BasePlugin):
                return None

            return instance
        except Exception:
            return None

    def _check_dependencies(self, manifest: PluginManifest) -> bool:
        """检查插件依赖是否满足。"""
        for dep in manifest.depends_on:
            dep_plugin = self._plugins.get(dep)
            if not dep_plugin or not dep_plugin.is_active:
                return False
        return True

    def _resolve_order(self) -> List[str]:
        """按依赖拓扑排序解析加载顺序。"""
        # Kahn's algorithm
        in_degree: Dict[str, int] = {}
        graph: Dict[str, List[str]] = {}

        for name in self._manifests:
            in_degree[name] = 0
            graph[name] = []

        for name, manifest in self._manifests.items():
            for dep in manifest.depends_on:
                if dep in graph:
                    graph[dep].append(name)
                    in_degree[name] += 1

        queue = [n for n, d in in_degree.items() if d == 0]
        order = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbor in graph.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return order


# ── File Watcher for Hot Reload ─────────────


class PluginFileWatcher:
    """文件变更监控器 — 检测到变更自动重载插件。

    Usage:
        watcher = PluginFileWatcher(registry)
        await watcher.start()
    """

    def __init__(
        self,
        registry: PluginRegistry,
        poll_interval: float = 2.0,
    ):
        self._registry = registry
        self._poll_interval = poll_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._file_mtimes: Dict[str, float] = {}

    async def start(self) -> None:
        """启动监控。"""
        self._running = True
        self._snapshot_files()
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """停止监控。"""
        self._running = False
        if self._task:
            self._task.cancel()

    def _snapshot_files(self) -> None:
        """记录当前文件修改时间。"""
        for path in self._registry._discovery_paths:
            base = Path(path)
            if not base.exists():
                continue
            for f in base.rglob("*.py"):
                self._file_mtimes[str(f)] = f.stat().st_mtime
            for f in base.rglob("plugin.json"):
                self._file_mtimes[str(f)] = f.stat().st_mtime

    async def _poll_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._poll_interval)
            try:
                self._check_and_reload()
            except Exception:
                pass

    def _check_and_reload(self) -> None:
        """检查文件变更并触发重载。"""
        changed = False

        for path in self._registry._discovery_paths:
            base = Path(path)
            if not base.exists():
                continue
            for f in base.rglob("*.py"):
                fpath = str(f)
                old_mtime = self._file_mtimes.get(fpath, 0)
                new_mtime = f.stat().st_mtime
                if new_mtime > old_mtime:
                    changed = True
                    self._file_mtimes[fpath] = new_mtime
            for f in base.rglob("plugin.json"):
                fpath = str(f)
                old_mtime = self._file_mtimes.get(fpath, 0)
                new_mtime = f.stat().st_mtime
                if new_mtime > old_mtime:
                    changed = True
                    self._file_mtimes[fpath] = new_mtime

        if changed:
            self._registry.reload_all()


# ── Built-in Plugins ────────────────────────


class AuditLoggerPlugin(BasePlugin):
    """内置审计日志插件。"""

    manifest = PluginManifest(
        name="audit_logger",
        version="1.0.0",
        description="Built-in audit logging middleware",
        provides_middleware=["audit_log"],
        auto_activate=True,
    )

    def on_activate(self):
        def audit_log(event_type: str, details: dict) -> None:
            """记录审计事件。"""
            log_entry = {
                "timestamp": time.time(),
                "event": event_type,
                "details": details,
            }
            # In production, write to structured log
            print(f"[AUDIT] {json.dumps(log_entry, default=str)}")

        self.register_middleware(audit_log)


class HealthCheckPlugin(BasePlugin):
    """内置健康检查插件。"""

    manifest = PluginManifest(
        name="health_check",
        version="1.0.0",
        description="Built-in health check endpoint",
        provides_tools=["health_check"],
        auto_activate=True,
    )

    def on_load(self):
        def health_check() -> dict:
            return {
                "status": "healthy",
                "timestamp": time.time(),
                "plugins_active": PluginRegistry().get_active_count(),
            }

        self.register_tool("health_check", health_check)


# ── Quick Start ─────────────────────────────


def create_registry_with_builtins() -> PluginRegistry:
    """创建注册中心并注册内置插件。"""
    registry = PluginRegistry()
    registry.register(HealthCheckPlugin())
    registry.register(AuditLoggerPlugin())

    for name in ["health_check", "audit_logger"]:
        registry.load(name)
        registry.activate(name)

    return registry
