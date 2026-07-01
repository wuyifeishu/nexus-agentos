"""AgentOS Plugin System — v1.2.7.

- PluginRegistry: 插件注册中心，生命周期管理。
- PluginDiscovery: 自动发现与热加载。
- PluginLoader: 沙箱化插件的 importlib 加载器。
- PluginLifecycle: 安装→启用→暂停→卸载完整生命周期。
"""

from agentos.plugins.registry import PluginRegistry, RegisteredPlugin, PluginStatus
from agentos.plugins.discovery import PluginDiscovery, DiscoveredPlugin
from agentos.plugins.loader import PluginLoader
from agentos.plugins.lifecycle import LifecycleManager

__all__ = [
    "PluginRegistry",
    "RegisteredPlugin",
    "PluginStatus",
    "PluginDiscovery",
    "DiscoveredPlugin",
    "PluginLoader",
    "LifecycleManager",
]
