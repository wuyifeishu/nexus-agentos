"""Tests for agentos.tools.web_tools module."""

from unittest.mock import AsyncMock, MagicMock, patch

from agentos.tools.base import PermissionLevel, ToolResult
from agentos.tools.web_tools import WebFetchTool


async def test_web_fetch_tool_metadata():
    t = WebFetchTool()
    assert t.name == "web_fetch"
    assert t.permission_level == PermissionLevel.SAFE
    params = t.parameters
    assert params["type"] == "object"
    assert "url" in params["required"]


async def test_web_fetch_execute_success():
    t = WebFetchTool()
    mock_resp = MagicMock()
    mock_resp.text = "<html>Hello</html>"
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("agentos.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
        result = await t.execute({"url": "https://example.com"})

    assert isinstance(result, ToolResult)
    assert result.error is None
    assert "<html>Hello</html>" in result.output


async def test_web_fetch_truncates_long_content():
    t = WebFetchTool()
    long_text = "x" * 15000
    mock_resp = MagicMock()
    mock_resp.text = long_text
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("agentos.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
        result = await t.execute({"url": "https://example.com"})

    assert len(result.output) == 10000


async def test_web_fetch_http_error():
    from httpx import HTTPStatusError, Request, Response

    t = WebFetchTool()
    request = Request("GET", "https://example.com")
    response = Response(404, request=request)
    exc = HTTPStatusError("Not Found", request=request, response=response)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=exc)

    with patch("agentos.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
        result = await t.execute({"url": "https://example.com"})

    assert result.error is not None
    assert "HTTP 404" in result.error


async def test_web_fetch_timeout():
    from httpx import TimeoutException

    t = WebFetchTool()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=TimeoutException("timeout"))

    with patch("agentos.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
        result = await t.execute({"url": "https://example.com"})

    assert result.error is not None
    assert "Timeout" in result.error


async def test_web_fetch_generic_error():
    t = WebFetchTool()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("agentos.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
        result = await t.execute({"url": "https://example.com"})

    assert result.error == "boom"


def test_openai_schema():
    t = WebFetchTool()
    schema = t.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "web_fetch"
