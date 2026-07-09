"""
Plugin Discovery — entry_points based plugin auto-discovery for AgentOS.

Scans installed packages for entry_points registered under the
'agentos.plugins' group and loads them without manual registration.
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class PluginProtocol(Protocol):
    """Minimal protocol that discovered plugins must satisfy."""

    name: str
    version: str

    def initialize(self) -> None: ...
    def shutdown(self) -> None: ...


@dataclass
class DiscoveredPlugin:
    """Represents a plugin discovered via entry_points."""

    name: str
    version: str
    entry_point_group: str
    entry_point_name: str
    package_name: str
    module_path: str
    metadata: dict[str, Any] = field(default_factory=dict)
    instance: Any | None = field(default=None, repr=False)

    @property
    def is_loaded(self) -> bool:
        return self.instance is not None


@dataclass
class DiscoveryResult:
    """Result of a plugin discovery scan."""

    plugins: list[DiscoveredPlugin]
    total_found: int
    total_loaded: int
    errors: list[str] = field(default_factory=list)
    scan_duration_ms: float = 0.0


class PluginDiscovery:
    """Scans installed packages for AgentOS plugins via entry_points."""

    DEFAULT_GROUPS = [
        "agentos.plugins",
        "agentos.tools",
        "agentos.models",
        "agentos.middleware",
    ]

    def __init__(self, groups: list[str] | None = None):
        self._groups = groups or self.DEFAULT_GROUPS
        self._discovered: dict[str, DiscoveredPlugin] = {}
        self._loaders: dict[str, Callable] = {}

    @property
    def discovered(self) -> dict[str, DiscoveredPlugin]:
        return dict(self._discovered)

    @property
    def groups(self) -> list[str]:
        return list(self._groups)

    def register_loader(self, group: str, loader: Callable) -> None:
        """Register a custom loader for a specific entry_point group."""
        self._loaders[group] = loader

    def scan(self, groups: list[str] | None = None) -> DiscoveryResult:
        """Scan for plugins across specified (or all registered) groups."""
        import time

        start = time.perf_counter()
        target_groups = groups or self._groups
        plugins: list[DiscoveredPlugin] = []
        errors: list[str] = []

        for group in target_groups:
            try:
                entry_points = importlib.metadata.entry_points(group=group)
            except TypeError:
                # Python 3.11 fallback
                all_eps = importlib.metadata.entry_points()
                entry_points = []
                for ep in all_eps:
                    if ep.group == group:
                        entry_points.append(ep)

            for ep in entry_points:
                try:
                    pkg = ep.dist.name if ep.dist else "unknown"
                    plugin = DiscoveredPlugin(
                        name=ep.name,
                        version=ep.dist.version if ep.dist else "0.0.0",
                        entry_point_group=group,
                        entry_point_name=ep.name,
                        package_name=pkg,
                        module_path=ep.value,
                        metadata={"group": group},
                    )
                    plugins.append(plugin)
                    self._discovered[f"{group}:{ep.name}"] = plugin
                except Exception as e:
                    errors.append(f"Failed to parse {ep.name} in {group}: {e}")

        elapsed = (time.perf_counter() - start) * 1000
        return DiscoveryResult(
            plugins=plugins,
            total_found=len(plugins),
            total_loaded=0,
            errors=errors,
            scan_duration_ms=elapsed,
        )

    def load_plugin(self, name: str, group: str = "agentos.plugins") -> DiscoveredPlugin | None:
        """Load a specific discovered plugin by name and group."""
        key = f"{group}:{name}"
        plugin = self._discovered.get(key)
        if plugin is None:
            logger.warning(f"Plugin '{key}' not found in discovered set.")
            return None

        try:
            loader = self._loaders.get(group, _default_plugin_loader)
            instance = loader(plugin.module_path)
            plugin.instance = instance
            if hasattr(instance, "initialize"):
                instance.initialize()
            return plugin
        except Exception as e:
            logger.error(f"Failed to load plugin '{key}': {e}")
            return None

    def load_all(self, group: str | None = None) -> dict[str, DiscoveredPlugin]:
        """Load all discovered plugins, optionally scoped to one group."""
        loaded: dict[str, DiscoveredPlugin] = {}
        for key, plugin in self._discovered.items():
            if group and not key.startswith(f"{group}:"):
                continue
            result = self.load_plugin(plugin.name, plugin.entry_point_group)
            if result and result.is_loaded:
                loaded[key] = result
        return loaded

    def get_by_package(self, package_name: str) -> list[DiscoveredPlugin]:
        """Get all discovered plugins from a specific package."""
        return [p for p in self._discovered.values() if p.package_name == package_name]

    def get_by_group(self, group: str) -> list[DiscoveredPlugin]:
        """Get all discovered plugins in a specific group."""
        return [p for p in self._discovered.values() if p.entry_point_group == group]

    def summary(self) -> dict[str, Any]:
        """Return a summary of all discovered plugins."""
        groups_summary: dict[str, int] = {}
        for p in self._discovered.values():
            groups_summary[p.entry_point_group] = groups_summary.get(p.entry_point_group, 0) + 1
        return {
            "total_plugins": len(self._discovered),
            "by_group": groups_summary,
            "loaded": sum(1 for p in self._discovered.values() if p.is_loaded),
        }

    def clear(self) -> None:
        """Clear all discovered plugins."""
        self._discovered.clear()


def _default_plugin_loader(module_path: str) -> Any:
    """Default loader: import the module and look for a Plugin class."""
    import importlib

    module = importlib.import_module(module_path)
    # Try common class names
    for attr_name in ("Plugin", "AgentOSPlugin", "plugin", "__plugin__"):
        if hasattr(module, attr_name):
            return getattr(module, attr_name)
    return module
