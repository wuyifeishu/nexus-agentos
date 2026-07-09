"""plugins.py - backward compatibility shim for agentos.plugins

All actual implementation has moved to agentos.plugin_manager.
This module re-exports for existing import paths.
"""

from agentos.plugin_manager import PluginInfo, PluginManager

__all__ = ["PluginInfo", "PluginManager"]


# ── Auto-generated compat stubs ──


class PluginRegistry:
    pass


class RegisteredPlugin:
    pass


class PluginStatus:
    pass


class PluginDiscovery:
    pass


class DiscoveredPlugin:
    pass


class PluginLoader:
    pass


class LifecycleManager:
    pass
