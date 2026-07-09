"""
浏览器自动化模块 — 通过 CDP (Chrome DevTools Protocol) 控制浏览器。

设计:
- 底层使用 Playwright 连接 Chromium 浏览器
- 操作统一为 BrowserAction 结构
- 支持导航、点击、填表、截图、提取文本、执行JS
- 权限级别: BROWSER (需用户授权)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from agentos.system.permissions import (
    PermissionDenied,
    PermissionTier,
    SystemPermissionManager,
)

# ── 浏览器动作定义 ─────────────────────────────────────────────


@dataclass
class BrowserAction:
    """浏览器操作定义。"""

    action_type: str  # navigate / click / type / screenshot / extract / js / wait / scroll
    url: str = ""  # 导航目标 URL
    selector: str = ""  # CSS/XPath 选择器
    value: str = ""  # 输入值 / JS 代码 / 等待时间
    screenshot_path: str = ""  # 截图保存路径
    wait_until: str = "load"  # 等待条件: load / networkidle / domcontentloaded


@dataclass
class BrowserResult:
    """浏览器操作结果。"""

    success: bool
    action: str
    url: str = ""
    text: str = ""  # 提取的文本
    html: str = ""  # 页面 HTML
    screenshot_path: str = ""  # 截图文件路径
    title: str = ""  # 页面标题
    error: str = ""
    duration_ms: float = 0


# ── CDP 浏览器会话 ─────────────────────────────────────────────


class BrowserSession:
    """基于 Playwright 的浏览器会话，封装 CDP 底层协议。

    使用方式:
        async with BrowserSession() as browser:
            await browser.navigate("https://example.com")
            text = await browser.extract_text("body")
            await browser.screenshot("page.png")
    """

    def __init__(
        self,
        headless: bool = True,
        slow_mo: int = 0,
        viewport_width: int = 1280,
        viewport_height: int = 720,
    ):
        self._headless = headless
        self._slow_mo = slow_mo
        self._viewport = {"width": viewport_width, "height": viewport_height}
        self._playwright = None
        self._browser = None
        self._page = None
        self._current_url = ""

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def start(self) -> None:
        """启动浏览器实例。"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "浏览器自动化需要 playwright。安装: pip install playwright && playwright install chromium"
            )

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            slow_mo=self._slow_mo,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        self._page = await self._browser.new_page(viewport=self._viewport)

    async def close(self) -> None:
        """关闭浏览器。"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ── 核心操作 ──

    async def navigate(self, url: str, wait_until: str = "load") -> BrowserResult:
        """导航到指定 URL。"""
        import time

        t0 = time.time()
        try:
            resp = await self._page.goto(url, wait_until=wait_until, timeout=30000)
            self._current_url = self._page.url
            title = await self._page.title()
            duration = (time.time() - t0) * 1000
            return BrowserResult(
                success=resp and resp.ok,
                action="navigate",
                url=self._current_url,
                title=title,
                duration_ms=duration,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="navigate",
                url=url,
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    async def click(self, selector: str) -> BrowserResult:
        """点击元素。"""
        import time

        t0 = time.time()
        try:
            await self._page.click(selector, timeout=10000)
            return BrowserResult(
                success=True,
                action="click",
                url=self._page.url,
                selector=selector,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="click",
                selector=selector,
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    async def type_text(self, selector: str, text: str) -> BrowserResult:
        """在输入框中输入文本。"""
        import time

        t0 = time.time()
        try:
            await self._page.fill(selector, text, timeout=10000)
            return BrowserResult(
                success=True,
                action="type",
                url=self._page.url,
                selector=selector,
                text=text,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="type",
                selector=selector,
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    async def extract_text(self, selector: str = "body") -> BrowserResult:
        """提取页面文本。"""
        import time

        t0 = time.time()
        try:
            element = await self._page.query_selector(selector)
            if element:
                text = await element.inner_text()
            else:
                text = ""
            return BrowserResult(
                success=True,
                action="extract",
                url=self._page.url,
                text=text,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="extract",
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    async def extract_html(self) -> BrowserResult:
        """获取完整 HTML。"""
        import time

        t0 = time.time()
        try:
            html = await self._page.content()
            return BrowserResult(
                success=True,
                action="extract",
                url=self._page.url,
                html=html,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="extract",
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    async def screenshot(self, path: str = "", full_page: bool = True) -> BrowserResult:
        """截取页面截图。"""
        import time

        t0 = time.time()
        save_path = path or f"/tmp/agentos_screenshot_{int(t0)}.png"
        try:
            await self._page.screenshot(path=save_path, full_page=full_page)
            return BrowserResult(
                success=True,
                action="screenshot",
                url=self._page.url,
                screenshot_path=save_path,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="screenshot",
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    async def execute_js(self, code: str) -> BrowserResult:
        """在页面中执行 JavaScript。"""
        import time

        t0 = time.time()
        try:
            result = await self._page.evaluate(code)
            return BrowserResult(
                success=True,
                action="js",
                url=self._page.url,
                text=str(result),
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="js",
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    async def wait(self, selector: str = "", milliseconds: int = 1000) -> BrowserResult:
        """等待元素出现或等待指定毫秒。"""
        import time

        t0 = time.time()
        try:
            if selector:
                await self._page.wait_for_selector(selector, timeout=10000)
            else:
                await asyncio.sleep(milliseconds / 1000)
            return BrowserResult(
                success=True,
                action="wait",
                url=self._page.url,
                selector=selector,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="wait",
                selector=selector,
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    async def scroll(self, direction: str = "down", amount: int = 500) -> BrowserResult:
        """滚动页面。"""
        import time

        t0 = time.time()
        try:
            if direction == "down":
                await self._page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                await self._page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "bottom":
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "top":
                await self._page.evaluate("window.scrollTo(0, 0)")
            return BrowserResult(
                success=True,
                action="scroll",
                url=self._page.url,
                text=f"已滚动 {direction}",
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return BrowserResult(
                success=False,
                action="scroll",
                error=str(e),
                duration_ms=(time.time() - t0) * 1000,
            )

    @property
    def current_url(self) -> str:
        return self._page.url if self._page else ""


# ── CDP 浏览器管理器 ───────────────────────────────────────────


class CDPBrowser:
    """浏览器管理器 — 带权限控制的浏览器自动化入口。

    使用:
        pm = SystemPermissionManager()
        browser = CDPBrowser(pm, "session-123")

        async with browser.session() as sess:
            await sess.navigate("https://example.com")
            text = await sess.extract_text()
    """

    def __init__(
        self, perm_manager: SystemPermissionManager, session_id: str, headless: bool = True
    ):
        self._pm = perm_manager
        self._sid = session_id
        self._headless = headless
        self._current_session: BrowserSession | None = None

    def session(self, headless: bool | None = None) -> BrowserSession:
        """创建浏览器会话（上下文管理器）。"""
        # 权限检查
        try:
            self._pm.require(self._sid, PermissionTier.BROWSER, "browser:*")
        except PermissionDenied as e:
            raise PermissionDenied(
                PermissionTier.BROWSER,
                "browser:*",
                f"浏览器自动化需要 BROWSER 权限: {e}",
            )

        hl = headless if headless is not None else self._headless
        self._current_session = BrowserSession(headless=hl)
        return self._current_session

    async def quick_fetch(self, url: str, extract_text: bool = True) -> BrowserResult:
        """快速抓取页面（自动打开关闭浏览器）。"""
        async with self.session() as sess:
            nav = await sess.navigate(url)
            if not nav.success:
                return nav
            if extract_text:
                return await sess.extract_text()
            return await sess.extract_html()

    async def quick_screenshot(self, url: str, save_path: str) -> BrowserResult:
        """快速截图页面。"""
        async with self.session() as sess:
            nav = await sess.navigate(url)
            if not nav.success:
                return nav
            return await sess.screenshot(save_path)

    async def execute_action(self, action: BrowserAction) -> BrowserResult:
        """执行单个浏览器动作。"""
        if not self._current_session:
            raise RuntimeError("没有活跃的浏览器会话，请使用 async with browser.session()")

        sess = self._current_session

        if action.action_type == "navigate":
            return await sess.navigate(action.url, action.wait_until)
        elif action.action_type == "click":
            return await sess.click(action.selector)
        elif action.action_type == "type":
            return await sess.type_text(action.selector, action.value)
        elif action.action_type == "screenshot":
            return await sess.screenshot(action.screenshot_path)
        elif action.action_type == "extract":
            return await sess.extract_text(action.selector or "body")
        elif action.action_type == "js":
            return await sess.execute_js(action.value)
        elif action.action_type == "wait":
            ms = int(action.value) if action.value.isdigit() else 1000
            return await sess.wait(action.selector, ms)
        elif action.action_type == "scroll":
            return await sess.scroll(action.value or "down")
        else:
            return BrowserResult(
                success=False, action=action.action_type, error=f"未知动作: {action.action_type}"
            )
