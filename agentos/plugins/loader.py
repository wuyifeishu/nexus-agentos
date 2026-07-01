"""
AgentOS v0.70 — 插件发现与加载器。
基因来源: Python entry_points + Docker plugin discovery

加载策略:
1. 入口点扫描 (entry_points.txt / pyproject.toml)
2. 目录扫描 (plugins/ 下的 manifest.json)
3. 环境变量指定 (AGENTOS_PLUGINS)
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from agentos.plugins.registry import (
    PluginRegistry, RegisteredPlugin, PluginManifest, PluginType, PluginStatus,
    DependencyCycleError,
)



class PluginLoadError(Exception):

    """插件加载错误。"""

    def __init__(self, plugin_name, reason=''):
        self.plugin_name = plugin_name
        self.reason = reason
        super().__init__(f"Failed to load plugin '{plugin_name}': {reason}" if reason else f"Failed to load plugin '{plugin_name}'")


DEFAULT_PLUGIN_DIRS = [
    "plugins",
    os.path.expanduser("~/.agentos/plugins"),
    "/etc/agentos/plugins",
]


class PluginLoader:
    """插件加载器 — 发现、验证、实例化、热加载。"""

    def __init__(
        self,
        registry: PluginRegistry | None = None,
        search_dirs: list[str] | None = None,
    ):
        self.registry = registry or PluginRegistry()
        self.search_dirs = search_dirs or DEFAULT_PLUGIN_DIRS

    # ── Discovery ────────────────────────────────

    def discover(self) -> list[PluginManifest]:
        """扫描所有搜索路径，发现可用插件。"""
        manifests: list[PluginManifest] = []
        seen: set[str] = set()

        for search_dir in self.search_dirs:
            if not os.path.isdir(search_dir):
                continue
            for entry in Path(search_dir).iterdir():
                manifest = self._load_manifest(entry)
                if manifest and manifest.name not in seen:
                    manifests.append(manifest)
                    seen.add(manifest.name)

        # Also check AGENTOS_PLUGINS env
        env_plugins = os.environ.get("AGENTOS_PLUGINS", "")
        if env_plugins:
            for plugin_dir in env_plugins.split(":"):
                plugin_dir = plugin_dir.strip()
                if not plugin_dir or not os.path.isdir(plugin_dir):
                    continue
                manifest = self._load_manifest(Path(plugin_dir))
                if manifest and manifest.name not in seen:
                    manifests.append(manifest)
                    seen.add(manifest.name)

        return manifests

    def _load_manifest(self, entry: Path) -> PluginManifest | None:
        """从目录或.py文件加载插件清单。"""
        if entry.is_dir():
            manifest_file = entry / "manifest.json"
        elif entry.suffix == ".py":
            # Single-file plugin: infer manifest from __doc__ and filename
            return self._manifest_from_pyfile(entry)
        else:
            return None

        if not manifest_file.exists():
            return None

        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        return PluginManifest(
            name=data.get("name", entry.name),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            plugin_type=PluginType(data.get("plugin_type", "custom")),
            entry_point=data.get("entry_point", ""),
            dependencies=data.get("dependencies", []),
            optional_dependencies=data.get("optional_dependencies", []),
            tags=data.get("tags", []),
            config_schema=data.get("config_schema", {}),
            priority=data.get("priority", 50),
            homepage=data.get("homepage", ""),
            license=data.get("license", "MIT"),
        )

    def _manifest_from_pyfile(self, pyfile: Path) -> PluginManifest | None:
        """从单文件Python插件推断清单。"""
        try:
            spec = importlib.util.spec_from_file_location(pyfile.stem, str(pyfile))
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            return None

        name = getattr(mod, "PLUGIN_NAME", pyfile.stem)
        version = getattr(mod, "PLUGIN_VERSION", "0.1.0")
        desc = getattr(mod, "PLUGIN_DESCRIPTION", mod.__doc__ or "")
        entry_point = getattr(mod, "PLUGIN_ENTRY_POINT", "")

        return PluginManifest(
            name=name,
            version=version,
            description=desc.strip(),
            plugin_type=PluginType.CUSTOM,
            entry_point=entry_point,
        )

    # ── Loading ──────────────────────────────────

    def load_all(
        self,
        manifests: list[PluginManifest] | None = None,
        auto_start: bool = False,
    ) -> PluginRegistry:
        """
        加载所有插件到注册中心。
        - 若未传manifests则先discover
        - 按依赖拓扑排序加载
        - 可选auto_start时初始化并激活
        """
        if manifests is None:
            manifests = self.discover()

        if not manifests:
            return self.registry

        names = [m.name for m in manifests]
        order = self._topological_sort(manifests)

        for name in order:
            manifest = next(m for m in manifests if m.name == name)
            start = time.time()
            try:
                instance = self._instantiate(manifest)
                registered = self.registry.register(manifest, instance)
                registered.load_time_ms = (time.time() - start) * 1000
                registered.status = PluginStatus.LOADED
            except Exception as e:
                registered = RegisteredPlugin(
                    manifest=manifest,
                    status=PluginStatus.ERROR,
                    error=str(e),
                    load_time_ms=(time.time() - start) * 1000,
                )
                self.registry.register(manifest)

        if auto_start:
            for name in order:
                self.registry._plugins[name].status = PluginStatus.ACTIVE

        return self.registry

    def load_one(self, manifest: PluginManifest, auto_start: bool = True) -> RegisteredPlugin:
        """加载单个插件。"""
        # Check deps
        missing = self.registry.check_requirements(manifest.name)
        if missing:
            raise DependencyCycleError(f"Plugin '{manifest.name}': missing deps {missing}")

        start = time.time()
        try:
            instance = self._instantiate(manifest)
            registered = self.registry.register(manifest, instance)
            registered.load_time_ms = (time.time() - start) * 1000
            registered.status = PluginStatus.ACTIVE if auto_start else PluginStatus.LOADED
            return registered
        except Exception as e:
            registered = RegisteredPlugin(
                manifest=manifest,
                status=PluginStatus.ERROR,
                error=str(e),
                load_time_ms=(time.time() - start) * 1000,
            )
            self.registry.register(manifest)
            return registered

    def hot_reload(self, name: str) -> RegisteredPlugin:
        """热重载插件：停止→重新加载→启动。"""
        old = self.registry.get(name)
        if not old:
            raise KeyError(f"Plugin '{name}' not registered")

        manifest = old.manifest
        # stop
        old.status = PluginStatus.STOPPING
        if hasattr(old.instance, "stop"):
            try:
                import asyncio
                if asyncio.iscoroutinefunction(old.instance.stop):
                    asyncio.get_event_loop().run_until_complete(old.instance.stop())
                else:
                    old.instance.stop()
            except Exception:
                pass
        old.status = PluginStatus.STOPPED

        # reload
        return self.load_one(manifest, auto_start=True)

    # ── Internal ─────────────────────────────────

    def _instantiate(self, manifest: PluginManifest) -> Any:
        """从entry_point实例化插件类。"""
        if not manifest.entry_point:
            # Static plugin (no executable code, just manifest declaration)
            return None

        parts = manifest.entry_point.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid entry_point: {manifest.entry_point}")

        module_path, class_name = parts
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            # Try reloading if already imported
            if module_path in sys.modules:
                mod = importlib.reload(sys.modules[module_path])
            else:
                raise

        cls = getattr(mod, class_name, None)
        if cls is None:
            raise AttributeError(f"Class '{class_name}' not in module '{module_path}'")

        return cls()

    def _topological_sort(self, manifests: list[PluginManifest]) -> list[str]:
        """依赖拓扑排序。"""
        names = {m.name for m in manifests}
        adj: dict[str, set[str]] = {m.name: set() for m in manifests}
        in_degree: dict[str, int] = {m.name: 0 for m in manifests}

        for m in manifests:
            for dep in m.dependencies:
                if dep in names:
                    adj[dep].add(m.name)  # dep → m
                    in_degree[m.name] += 1

        queue = [n for n in names if in_degree[n] == 0]
        order = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for successor in adj[n]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        if len(order) != len(manifests):
            raise DependencyCycleError("循环依赖")

        return order
