"""
网络工具 — 搜索与网页抓取。
"""

from __future__ import annotations

import httpx

from agentos.tools.base import BaseTool, PermissionLevel, ToolResult


class WebFetchTool(BaseTool):

    """网页抓取工具。"""

    name = "web_fetch"
    description = "抓取指定URL的网页正文内容。用于读取网页、文档、API响应等。"
    permission_level = PermissionLevel.SAFE

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的URL，需以http://或https://开头",
                },
            },
            "required": ["url"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        url = arguments["url"]
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "AgentOS/0.1 (+https://agentos.dev)"},
                )
                response.raise_for_status()
                text = response.text[:10000]  # 限制最大10K字符
            return ToolResult.ok("", output=text)
        except httpx.HTTPStatusError as e:
            return ToolResult.fail("", error=f"HTTP {e.response.status_code}: {url}")
        except httpx.TimeoutException:
            return ToolResult.fail("", error=f"Timeout fetching {url}")
        except Exception as e:
            return ToolResult.fail("", error=str(e))
