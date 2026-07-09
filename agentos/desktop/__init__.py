"""
AgentOS Desktop — 一键启动的桌面客户端 (v1.7.5)

v1.7.5 增强:
- Textual TUI 终端界面（三面板：文件树/聊天/终端）
- 全键盘快捷键操作
- 实时流式输出

v1.7.1:
- 可视化授权审批引擎（Agent 主动申请 → 用户点击允许/拒绝）
- 原生桌面壳支持（pywebview 窗口包裹）
- 权限模式一键切换
"""

from agentos.desktop.server import DesktopConfig, DesktopServer, launch_desktop

try:
    from agentos.desktop.tui import AgentOSTUI, TUIConfig, launch_tui
except ImportError:

    class _StubApp:
        pass

    def launch_tui(**kw):
        return print("ERROR: textual not installed. Run: pip install textual")  # type: ignore

    TUIConfig = type("TUIConfig", (), {})  # type: ignore
    AgentOSTUI = _StubApp  # type: ignore

__all__ = [
    "DesktopServer",
    "DesktopConfig",
    "launch_desktop",
    "launch_tui",
    "TUIConfig",
    "AgentOSTUI",
]
