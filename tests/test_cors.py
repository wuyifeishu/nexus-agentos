"""Tests for agentos.tools.cors."""

from agentos.tools.cors import CORSConfig


class TestCORSConfig:
    def test_allow_single_origin(self):
        cors = CORSConfig().allow_origins("https://example.com")
        assert cors.is_origin_allowed("https://example.com")
        assert not cors.is_origin_allowed("https://evil.com")

    def test_allow_multiple_origins(self):
        cors = CORSConfig().allow_origins("https://a.com", "https://b.com")
        assert cors.is_origin_allowed("https://a.com")
        assert cors.is_origin_allowed("https://b.com")
        assert not cors.is_origin_allowed("https://c.com")

    def test_allow_any_origin(self):
        cors = CORSConfig().allow_origins("*")
        assert cors.is_origin_allowed("https://anything.com")
        assert cors.is_origin_allowed("http://localhost:3000")

    def test_wildcard_origin_pattern(self):
        cors = CORSConfig().allow_origins("https://*.example.com")
        assert cors.is_origin_allowed("https://app.example.com")
        assert cors.is_origin_allowed("https://api.example.com")
        assert not cors.is_origin_allowed("https://example.com")
        assert not cors.is_origin_allowed("https://evil.com")

    def test_origin_trailing_slash(self):
        cors = CORSConfig().allow_origins("https://example.com")
        assert cors.is_origin_allowed("https://example.com/")

    def test_preflight_headers_basic(self):
        cors = CORSConfig().allow_origins("https://example.com").allow_methods("GET", "POST")
        headers = cors.preflight_headers("https://example.com", "POST")
        assert headers["Access-Control-Allow-Origin"] == "https://example.com"
        assert "GET" in headers["Access-Control-Allow-Methods"]
        assert "POST" in headers["Access-Control-Allow-Methods"]

    def test_preflight_headers_any_origin_no_creds(self):
        cors = CORSConfig().allow_origins("*").allow_methods("GET")
        headers = cors.preflight_headers("https://example.com")
        assert headers["Access-Control-Allow-Origin"] == "*"

    def test_preflight_headers_any_origin_with_creds(self):
        cors = CORSConfig().allow_origins("*").allow_credentials()
        headers = cors.preflight_headers("https://example.com")
        # Must be specific origin when credentials are allowed
        assert headers["Access-Control-Allow-Origin"] == "https://example.com"
        assert headers["Access-Control-Allow-Credentials"] == "true"

    def test_preflight_disallowed_origin(self):
        cors = CORSConfig().allow_origins("https://example.com")
        headers = cors.preflight_headers("https://evil.com")
        assert not headers

    def test_preflight_request_headers_filtered(self):
        cors = CORSConfig().allow_origins("https://example.com").allow_headers("content-type", "authorization")
        headers = cors.preflight_headers(
            "https://example.com",
            request_method="POST",
            request_headers=["Content-Type", "X-Custom"],
        )
        assert "content-type" in headers["Access-Control-Allow-Headers"]
        assert "x-custom" not in headers["Access-Control-Allow-Headers"]

    def test_max_age(self):
        cors = CORSConfig().allow_origins("https://example.com").max_age(3600)
        headers = cors.preflight_headers("https://example.com")
        assert headers["Access-Control-Max-Age"] == "3600"

    def test_expose_headers(self):
        cors = CORSConfig().allow_origins("https://example.com").expose_headers("X-Total-Count", "X-Rate-Limit")
        headers = cors.actual_headers("https://example.com")
        assert "x-total-count" in headers["Access-Control-Expose-Headers"]
        assert "x-rate-limit" in headers["Access-Control-Expose-Headers"]

    def test_actual_headers_credentials(self):
        cors = CORSConfig().allow_origins("https://example.com").allow_credentials()
        headers = cors.actual_headers("https://example.com")
        assert headers["Access-Control-Allow-Credentials"] == "true"

    def test_actual_headers_disallowed(self):
        cors = CORSConfig().allow_origins("https://example.com")
        headers = cors.actual_headers("https://evil.com")
        assert not headers

    def test_is_preflight(self):
        cors = CORSConfig()
        assert cors.is_preflight("OPTIONS")
        assert not cors.is_preflight("GET")
        assert not cors.is_preflight("POST")

    def test_allow_all_methods(self):
        cors = CORSConfig().allow_origins("https://example.com").allow_all_methods()
        headers = cors.preflight_headers("https://example.com", "GET")
        assert "GET" in headers["Access-Control-Allow-Methods"]
        assert "DELETE" in headers["Access-Control-Allow-Methods"]

    def test_allow_all_headers(self):
        cors = CORSConfig().allow_origins("https://example.com").allow_all_headers()
        headers = cors.preflight_headers("https://example.com", request_headers=["X-Custom"])
        assert "x-custom" in headers["Access-Control-Allow-Headers"]
