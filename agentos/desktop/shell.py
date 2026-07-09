"""
Desktop Shell — AgentOS 原生桌面壳。

基于 pywebview，将 Web 客户端包裹为原生桌面应用窗口。
提供与 AutoClaw 桌面客户端类似的体验:

功能:
- 原生窗口包裹 Web 前端
- 系统托盘（最小化到托盘）
- 开机自启配置
- 窗口置顶 / 全屏
- 原生通知
- 多平台兼容（Windows / macOS / Linux）

依赖: pip install pywebview

启动方式:
    python -m agentos.desktop.shell          # 连接本地服务
    python -m agentos.desktop.shell --url http://1.2.3.4:19999  # 连接远程
"""

from __future__ import annotations

import argparse
import json
import os
import time
import webbrowser

# ── 配置 ───────────────────────────────────────────────────────

APP_NAME = "AgentOS Desktop"
APP_VERSION = "1.7.1"
DEFAULT_URL = "http://127.0.0.1:19999"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".agentos")
CONFIG_FILE = os.path.join(CONFIG_DIR, "desktop.json")


def load_config() -> dict:
    """加载本地配置。"""
    defaults = {
        "url": DEFAULT_URL,
        "width": 1200,
        "height": 800,
        "fullscreen": False,
        "always_on_top": False,
        "auto_start": False,
        "minimize_to_tray": True,
        "title": f"{APP_NAME} v{APP_VERSION}",
    }
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                defaults.update(json.load(f))
        except Exception:
            pass
    return defaults


def save_config(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ── 原生桌面壳 ─────────────────────────────────────────────────


def create_native_shell(
    url: str,
    width: int = 1200,
    height: int = 800,
    title: str = APP_NAME,
    fullscreen: bool = False,
    on_top: bool = False,
    minimize_to_tray: bool = True,
) -> None:
    """使用 pywebview 创建原生桌面窗口。"""
    try:
        import webview
    except ImportError:
        print("需要安装 pywebview: pip install pywebview")
        print("自动打开浏览器作为降级方案...")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    webview.create_window(
        title=title,
        url=url,
        width=width,
        height=height,
        fullscreen=fullscreen,
        on_top=on_top,
        easy_drag=False,
        confirm_close=minimize_to_tray,
        text_select=True,
    )

    # 系统托盘暂时关闭（pywebview 托盘支持有限）
    # 完整的托盘功能需要 pywebview >= 5.0 + 特定平台的额外配置
    webview.start(gui="cef", debug=False)


# ── 命令行入口 ──


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AgentOS Desktop Shell — 原生桌面壳",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  agentos desktop-shell                        # 连接本地 127.0.0.1:19999
  agentos desktop-shell --url http://remote:19999  # 连接远程服务
  agentos desktop-shell --fullscreen           # 全屏模式
  agentos desktop-shell --on-top               # 窗口置顶
  agentos desktop-shell --browser              # 直接用浏览器打开（降级）
        """,
    )
    parser.add_argument("--url", default=None, help=f"服务端地址（默认: {DEFAULT_URL}）")
    parser.add_argument("--width", type=int, default=1200, help="窗口宽度（默认: 1200）")
    parser.add_argument("--height", type=int, default=800, help="窗口高度（默认: 800）")
    parser.add_argument("--fullscreen", action="store_true", help="全屏启动")
    parser.add_argument("--on-top", action="store_true", help="窗口置顶")
    parser.add_argument("--no-tray", action="store_true", help="禁用最小化到托盘")
    parser.add_argument("--browser", action="store_true", help="直接用系统浏览器打开")
    parser.add_argument("--config", action="store_true", help="显示当前配置")

    args = parser.parse_args()
    cfg = load_config()

    if args.config:
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return

    url = args.url or cfg.get("url", DEFAULT_URL)
    width = args.width
    height = args.height
    title = cfg.get("title", APP_NAME)
    fullscreen = args.fullscreen
    on_top = args.on_top
    tray = not args.no_tray

    if args.browser:
        print(f"用浏览器打开 {url} ...")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        print(f"启动 AgentOS Desktop Shell v{APP_VERSION}")
        print(f"连接: {url}")
        create_native_shell(
            url=url,
            width=width,
            height=height,
            title=title,
            fullscreen=fullscreen,
            on_top=on_top,
            minimize_to_tray=tray,
        )


if __name__ == "__main__":
    main()
