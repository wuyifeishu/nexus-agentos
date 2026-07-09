"""Tests for agentos.tools.http_tools — HttpRequestTool, DownloadTool."""

import os
import tempfile

import pytest

from agentos.tools.http_tools import DownloadTool, HttpRequestTool

# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def http_tool():
    return HttpRequestTool()


@pytest.fixture
def download_tool():
    return DownloadTool()


def _is_network_ok() -> bool:
    """Quick connectivity check — skip if httpbin is unreachable or rate-limited."""
    import urllib.request
    try:
        req = urllib.request.Request("https://httpbin.org/get", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def _httpbin_url(path: str) -> str:
    return f"https://httpbin.org{path}"


def _httpbin_skip(msg: str = "httpbin.org unreachable or rate-limited"):
    return pytest.mark.skipif(not _is_network_ok(), reason=msg)


# ── HttpRequestTool Tests ──────────────────────────────────

class TestHttpRequestTool:
    def test_parameters_schema(self, http_tool):
        params = http_tool.parameters
        assert params["type"] == "object"
        assert "url" in params["properties"]
        assert "url" in params["required"]

    def test_name_and_description(self, http_tool):
        assert http_tool.name == "http_request"
        assert len(http_tool.description) > 0

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_get_request(self, http_tool):
        result = await http_tool.execute({"url": _httpbin_url("/get")})
        assert result.error is None
        assert "Status:" in result.output

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_get_with_headers(self, http_tool):
        result = await http_tool.execute({
            "url": _httpbin_url("/headers"),
            "headers": '{"X-Custom": "test-value"}',
        })
        assert result.error is None

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_post_request(self, http_tool):
        result = await http_tool.execute({
            "url": _httpbin_url("/post"),
            "method": "POST",
            "body": '{"key": "value"}',
        })
        assert result.error is None

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_http_error(self, http_tool):
        result = await http_tool.execute({"url": _httpbin_url("/status/404")})
        # HttpRequestTool uses ToolResult.ok for HTTP errors (with code in output)
        assert "404" in result.output or "HTTP" in result.output

    @pytest.mark.asyncio
    async def test_invalid_url(self, http_tool):
        result = await http_tool.execute({"url": "http://invalid-host-that-does-not-exist-99999.xyz/api"})
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_invalid_headers_json(self, http_tool):
        result = await http_tool.execute({
            "url": _httpbin_url("/get"),
            "headers": "not json",
        })
        assert result.error is not None
        assert "Invalid headers" in result.error

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_default_method_get(self, http_tool):
        result = await http_tool.execute({"url": _httpbin_url("/get")})
        assert result.error is None
        assert "Status:" in result.output

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_put_request(self, http_tool):
        result = await http_tool.execute({
            "url": _httpbin_url("/put"),
            "method": "PUT",
            "body": '{"updated": true}',
        })
        assert result.error is None

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_delete_request(self, http_tool):
        result = await http_tool.execute({
            "url": _httpbin_url("/delete"),
            "method": "DELETE",
        })
        assert result.error is None

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_patch_request(self, http_tool):
        result = await http_tool.execute({
            "url": _httpbin_url("/patch"),
            "method": "PATCH",
            "body": '{"patched": true}',
        })
        assert result.error is None


# ── DownloadTool Tests ─────────────────────────────────────

class TestDownloadTool:
    def test_parameters_schema(self, download_tool):
        params = download_tool.parameters
        assert params["type"] == "object"
        assert "url" in params["properties"]
        assert "url" in params["required"]

    def test_name_and_description(self, download_tool):
        assert download_tool.name == "download_file"
        assert len(download_tool.description) > 0

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_download_to_tempdir(self, download_tool):
        result = await download_tool.execute({
            "url": _httpbin_url("/bytes/1024"),
        })
        assert result.error is None
        assert "Downloaded:" in result.output
        assert "1024 bytes" in result.output
        path_line = result.output.split("\n")[0]
        filepath = path_line.replace("Downloaded: ", "").strip()
        if os.path.isfile(filepath):
            os.unlink(filepath)

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_download_to_specific_dir(self, download_tool):
        with tempfile.TemporaryDirectory() as td:
            result = await download_tool.execute({
                "url": _httpbin_url("/bytes/512"),
                "output_path": td,
            })
            assert result.error is None
            assert "Downloaded:" in result.output
            downloaded_path = result.output.split("\n")[0].replace("Downloaded: ", "").strip()
            assert os.path.isfile(downloaded_path)
            assert os.path.dirname(downloaded_path) == td

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_download_to_specific_file(self, download_tool):
        with tempfile.TemporaryDirectory() as td:
            filepath = os.path.join(td, "my_data.bin")
            result = await download_tool.execute({
                "url": _httpbin_url("/bytes/256"),
                "output_path": filepath,
            })
            assert result.error is None
            assert os.path.isfile(filepath)
            assert os.path.getsize(filepath) == 256

    @pytest.mark.asyncio
    @_httpbin_skip()
    async def test_download_duplicate_avoids_overwrite(self, download_tool):
        with tempfile.TemporaryDirectory() as td:
            filepath = os.path.join(td, "bytes")
            await download_tool.execute({
                "url": _httpbin_url("/bytes/100"),
                "output_path": filepath,
            })
            result2 = await download_tool.execute({
                "url": _httpbin_url("/bytes/100"),
                "output_path": filepath,
            })
            assert result2.error is None
            downloaded_path = result2.output.split("\n")[0].replace("Downloaded: ", "").strip()
            assert os.path.basename(downloaded_path) != "bytes"
            assert os.path.isfile(downloaded_path)

    @pytest.mark.asyncio
    async def test_download_invalid_url(self, download_tool):
        result = await download_tool.execute({
            "url": "http://invalid-host-that-does-not-exist-99999.xyz/file.bin",
        })
        assert result.error is not None
        assert "Download failed" in result.error
