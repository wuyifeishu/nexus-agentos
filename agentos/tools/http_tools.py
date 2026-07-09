"""HTTP 工具 — HTTP 请求、文件下载。"""

from __future__ import annotations

import json
import os
import tempfile
import time
from urllib.parse import urlparse

from agentos.tools.base import BaseTool, ToolResult


class HttpRequestTool(BaseTool):
    """HTTP 请求工具 — 发送 GET/POST/PUT/DELETE 请求。"""

    name = "http_request"
    description = "发送 HTTP 请求（GET/POST/PUT/DELETE），支持 JSON body、自定义 header"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "请求 URL"},
                "method": {
                    "type": "string",
                    "description": "HTTP 方法：GET/POST/PUT/DELETE，默认 GET",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                },
                "body": {"type": "string", "description": "请求体（JSON 字符串）"},
                "headers": {"type": "string", "description": "自定义 Header，JSON 格式串"},
                "timeout": {"type": "integer", "description": "超时秒数，默认 30"},
            },
            "required": ["url"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        import urllib.error
        import urllib.request

        url = arguments.get("url", "")
        method = arguments.get("method", "GET").upper()
        body = arguments.get("body", "")
        headers_str = arguments.get("headers", "{}")
        timeout = arguments.get("timeout", 30)

        try:
            parsed_headers = json.loads(headers_str) if headers_str else {}
        except json.JSONDecodeError:
            return ToolResult.fail(call_id="", error=f"Invalid headers JSON: {headers_str}")

        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "AgentOS-HttpTool/1.0")
        req.add_header("Accept", "application/json, text/plain, */*")
        if body:
            req.add_header("Content-Type", "application/json")
        for k, v in parsed_headers.items():
            req.add_header(k, str(v))

        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                elapsed_ms = (time.time() - t0) * 1000
                raw_body = resp.read()
                text_body = raw_body.decode("utf-8", errors="replace")
                content_type = resp.headers.get("Content-Type", "")

                output = (
                    f"Status: {resp.status}\n"
                    f"Content-Type: {content_type}\n"
                    f"Body length: {len(raw_body)} bytes\n"
                    f"Elapsed: {elapsed_ms:.0f}ms\n\n"
                    f"{text_body[:3000]}"
                )
                return ToolResult.ok(call_id="", output=output)

        except urllib.error.HTTPError as e:
            elapsed_ms = (time.time() - t0) * 1000
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")[:1000]
            except Exception:
                pass
            return ToolResult.ok(
                call_id="",
                output=f"HTTP {e.code} {e.reason}\nElapsed: {elapsed_ms:.0f}ms\n\n{error_body}",
            )
        except Exception as e:
            return ToolResult.fail(call_id="", error=f"Request failed: {e}")


class DownloadTool(BaseTool):
    """文件下载工具 — 下载 URL 内容到本地文件。"""

    name = "download_file"
    description = "从 URL 下载文件到本地，返回本地路径和文件大小"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "下载 URL"},
                "output_path": {
                    "type": "string",
                    "description": "输出目录或文件路径，默认临时目录",
                },
            },
            "required": ["url"],
        }

    async def execute(self, arguments: dict, sandbox=None) -> ToolResult:
        import urllib.request

        url = arguments.get("url", "")
        output_path = arguments.get("output_path", "")

        parsed = urlparse(url)
        filename = os.path.basename(parsed.path) or "download"
        if output_path:
            if os.path.isdir(output_path) or output_path.endswith("/"):
                filepath = os.path.join(output_path, filename)
            else:
                filepath = output_path
        else:
            filepath = os.path.join(tempfile.gettempdir(), filename)

        # Avoid overwriting
        if os.path.exists(filepath):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(filepath):
                filepath = os.path.join(os.path.dirname(filepath), f"{base}_{counter}{ext}")
                counter += 1

        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        t0 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=300) as resp:
                total = 0
                with open(filepath, "wb") as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        total += len(chunk)

            elapsed_ms = (time.time() - t0) * 1000
            size_mb = total / (1024 * 1024)
            return ToolResult.ok(
                call_id="",
                output=f"Downloaded: {filepath}\nSize: {total} bytes ({size_mb:.2f} MB)\nTime: {elapsed_ms:.0f}ms",
            )
        except Exception as e:
            return ToolResult.fail(call_id="", error=f"Download failed: {e}")
