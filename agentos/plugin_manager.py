"""
AgentOS v0.20 插件系统。
支持动态加载第三方工具、Agent、工作流。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PluginInfo:
    """插件信息。"""
    name: str
    version: str
    description: str
    entry_point: str
    author: str = ""
    path: str = ""


class PluginManager:
    """插件管理器 — 动态发现、加载、卸载插件。"""

    def __init__(self, plugin_dirs: list[str] | None = None):
        self._plugins: dict[str, PluginInfo] = {}
        self._modules: dict[str, Any] = {}
        self._hooks: dict[str, list[Callable]] = {}
        self._plugin_dirs = plugin_dirs or ["./plugins", os.path.expanduser("~/.agentos/plugins")]

    def discover(self) -> list[PluginInfo]:
        """扫描插件目录发现所有可用插件。"""
        discovered = []
        for d in self._plugin_dirs:
            if not os.path.isdir(d):
                continue
            for entry in os.listdir(d):
                pdir = os.path.join(d, entry)
                manifest = os.path.join(pdir, "plugin.json")
                if os.path.isfile(manifest):
                    import json
                    with open(manifest) as f:
                        info = PluginInfo(**json.load(f))
                        info.path = pdir
                        discovered.append(info)
        return discovered

    def register(self, info: PluginInfo):
        self._plugins[info.name] = info

    def load(self, name: str) -> Any:
        """加载并初始化一个插件。"""
        if name not in self._plugins:
            raise ValueError(f"Plugin '{name}' not registered")

        info = self._plugins[name]
        if info.path and info.path not in sys.path:
            sys.path.insert(0, info.path)

        try:
            mod = importlib.import_module(name)
        except ImportError:
            # 尝试直接加载
            spec = importlib.util.spec_from_file_location(name, os.path.join(info.path or ".", "__init__.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

        self._modules[name] = mod

        # 调用plugin的register函数
        if hasattr(mod, "register"):
            mod.register(self)

        return mod

    def unload(self, name: str):
        if name in self._modules:
            del self._modules[name]
        # 注意：无法真正从sys.modules卸载

    def add_hook(self, hook_name: str, callback: Callable):
        """注册钩子。"""
        self._hooks.setdefault(hook_name, []).append(callback)

    def call_hook(self, hook_name: str, *args, **kwargs):
        """触发钩子。"""
        for cb in self._hooks.get(hook_name, []):
            cb(*args, **kwargs)

    @property
    def loaded_plugins(self) -> list[str]:
        return list(self._modules.keys())
