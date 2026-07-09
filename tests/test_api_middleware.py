"""Unit tests for agentos.api.middleware module."""
import time

from agentos.api.middleware import (
    AuthConfig,
    AuthMiddleware,
    CORSConfig,
    CORSMiddleware,
    MiddlewareStack,
    RequestContext,
    RequestIDMiddleware,
    RequestLogMiddleware,
)

# ── RequestContext ──

def test_request_context_defaults():
    ctx = RequestContext()
    assert ctx.request_id == ""
    assert ctx.start_time == 0.0


def test_request_context_full():
    ctx = RequestContext(request_id="abc123", start_time=100.0, method="GET", path="/api/test", client_ip="1.2.3.4", user_agent="test-agent")
    assert ctx.request_id == "abc123"
    assert ctx.method == "GET"
    assert ctx.path == "/api/test"


def test_request_context_elapsed_ms():
    now = time.monotonic()
    ctx = RequestContext(start_time=now)
    time.sleep(0.01)
    elapsed = ctx.elapsed_ms
    assert elapsed >= 0
    assert elapsed < 1000


# ── RequestIDMiddleware ──

def test_request_id_middleware_generates_id():
    mw = RequestIDMiddleware()
    ctx = mw.process_request({"x-request-id": ""})
    assert ctx.request_id != ""
    assert len(ctx.request_id) == 12


def test_request_id_middleware_preserves_header():
    mw = RequestIDMiddleware()
    ctx = mw.process_request({"X-Request-ID": "my-custom-id"})
    assert ctx.request_id == "my-custom-id"


def test_request_id_middleware_lowercase_header():
    mw = RequestIDMiddleware()
    ctx = mw.process_request({"x-request-id": "lowercase-id"})
    assert ctx.request_id == "lowercase-id"


def test_request_id_middleware_custom_header():
    mw = RequestIDMiddleware(header="X-Correlation-ID")
    ctx = mw.process_request({"X-Correlation-ID": "corr-123"})
    assert ctx.request_id == "corr-123"


# ── CORSConfig ──

def test_cors_config_defaults():
    cfg = CORSConfig()
    assert cfg.allow_origins == ["*"]
    assert "GET" in cfg.allow_methods
    assert cfg.max_age == 86400


def test_cors_config_custom():
    cfg = CORSConfig(allow_origins=["https://example.com"], max_age=3600, allow_credentials=True)
    assert cfg.allow_origins == ["https://example.com"]
    assert cfg.max_age == 3600
    assert cfg.allow_credentials is True


# ── CORSMiddleware ──

def test_cors_middleware_default_config():
    mw = CORSMiddleware()
    assert mw.config.allow_origins == ["*"]


def test_cors_middleware_custom_config():
    cfg = CORSConfig(allow_origins=["https://myapp.com"])
    mw = CORSMiddleware(config=cfg)
    assert mw.config.allow_origins == ["https://myapp.com"]


def test_cors_apply_adds_headers():
    mw = CORSMiddleware()
    result = mw.apply({})
    assert "Access-Control-Allow-Origin" in result
    assert "Access-Control-Allow-Methods" in result
    assert "Access-Control-Allow-Headers" in result
    assert result["Access-Control-Allow-Origin"] == "*"


def test_cors_apply_with_expose_headers():
    cfg = CORSConfig(expose_headers=["X-Custom", "X-RateLimit"])
    mw = CORSMiddleware(config=cfg)
    result = mw.apply({})
    assert "Access-Control-Expose-Headers" in result
    assert "X-Custom" in result["Access-Control-Expose-Headers"]


def test_cors_apply_with_credentials():
    cfg = CORSConfig(allow_credentials=True)
    mw = CORSMiddleware(config=cfg)
    result = mw.apply({})
    assert result["Access-Control-Allow-Credentials"] == "true"


def test_cors_apply_preserves_existing_headers():
    mw = CORSMiddleware()
    result = mw.apply({"Content-Type": "application/json", "Existing": "value"})
    assert result["Content-Type"] == "application/json"
    assert result["Existing"] == "value"
    assert "Access-Control-Allow-Origin" in result


# ── AuthConfig ──

def test_auth_config_defaults():
    cfg = AuthConfig()
    assert cfg.api_key_header == "X-API-Key"
    assert cfg.api_key == ""
    assert cfg.enabled is True


# ── AuthMiddleware ──

def test_auth_middleware_default_config():
    mw = AuthMiddleware()
    assert mw.config.enabled is True


def test_auth_middleware_custom_config():
    cfg = AuthConfig(api_key="secret123")
    mw = AuthMiddleware(config=cfg)
    assert mw.config.api_key == "secret123"


def test_auth_disabled_allows_all():
    cfg = AuthConfig(enabled=False)
    mw = AuthMiddleware(config=cfg)
    ok, msg = mw.authenticate({})
    assert ok is True
    assert msg == ""


def test_auth_no_key_configured_allows():
    cfg = AuthConfig(api_key="")
    mw = AuthMiddleware(config=cfg)
    ok, msg = mw.authenticate({"X-API-Key": "anything"})
    assert ok is True


def test_auth_correct_key():
    cfg = AuthConfig(api_key="my-secret-key")
    mw = AuthMiddleware(config=cfg)
    ok, msg = mw.authenticate({"X-API-Key": "my-secret-key"})
    assert ok is True
    assert msg == ""


def test_auth_wrong_key():
    cfg = AuthConfig(api_key="my-secret-key")
    mw = AuthMiddleware(config=cfg)
    ok, msg = mw.authenticate({"X-API-Key": "wrong-key"})
    assert ok is False
    assert "Invalid" in msg


def test_auth_missing_key():
    cfg = AuthConfig(api_key="my-secret-key")
    mw = AuthMiddleware(config=cfg)
    ok, msg = mw.authenticate({})
    assert ok is False


def test_auth_case_insensitive_header():
    cfg = AuthConfig(api_key="secret")
    mw = AuthMiddleware(config=cfg)
    ok, msg = mw.authenticate({"x-api-key": "secret"})
    assert ok is True


# ── RequestLogMiddleware ──

def test_request_log_middleware_default_logger():
    mw = RequestLogMiddleware()
    assert mw._log is print


def test_request_log_middleware_custom_logger():
    logs = []
    mw = RequestLogMiddleware(logger=lambda msg: logs.append(msg))
    ctx = RequestContext(request_id="req-1", method="GET", path="/api", start_time=time.monotonic())
    result = mw.log(ctx, 200)
    assert "req-1" in result
    assert "GET" in result
    assert "/api" in result
    assert "200" in result
    assert len(logs) == 1
    assert "req-1" in logs[0]


def test_request_log_middleware_error_status():
    logs = []
    mw = RequestLogMiddleware(logger=lambda msg: logs.append(msg))
    ctx = RequestContext(request_id="req-2", method="POST", path="/api/error", start_time=time.monotonic())
    result = mw.log(ctx, 500)
    assert "500" in result
    assert len(logs) == 1


# ── MiddlewareStack ──

def test_middleware_stack_defaults():
    stack = MiddlewareStack()
    assert stack.cors is not None
    assert stack.auth is not None
    assert stack.req_log is not None
    assert stack.req_id is not None


def test_middleware_stack_custom_components():
    cors = CORSMiddleware()
    auth = AuthMiddleware()
    req_log = RequestLogMiddleware()
    req_id = RequestIDMiddleware()
    stack = MiddlewareStack(cors=cors, auth=auth, req_log=req_log, req_id=req_id)
    assert stack.cors is cors
    assert stack.auth is auth
    assert stack.req_log is req_log
    assert stack.req_id is req_id
