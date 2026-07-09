"""Tests for agentos.tools.csp."""

from agentos.tools.csp import CSP, generate_nonce


class TestGenerateNonce:
    def test_length(self):
        n1 = generate_nonce()
        assert len(n1) >= 43  # 32 bytes base64

    def test_uniqueness(self):
        n1 = generate_nonce()
        n2 = generate_nonce()
        assert n1 != n2


class TestCSP:
    def test_basic_header(self):
        csp = CSP().default_src("'self'").img_src("*").to_header()
        assert "default-src 'self'" in csp
        assert "img-src *" in csp

    def test_script_src_with_nonce(self):
        nonce = generate_nonce()
        header = CSP().script_src("'self'", nonce=nonce).to_header()
        assert f"'nonce-{nonce}'" in header
        assert "'self'" in header

    def test_flag_directives(self):
        header = CSP().upgrade_insecure_requests().to_header()
        assert "upgrade-insecure-requests" in header

    def test_block_mixed_content(self):
        header = CSP().block_all_mixed_content().to_header()
        assert "block-all-mixed-content" in header

    def test_sandbox(self):
        header = CSP().sandbox("allow-scripts", "allow-same-origin").to_header()
        assert "sandbox allow-scripts allow-same-origin" in header

    def test_report_uri(self):
        header = CSP().report_uri("https://example.com/csp-report").to_header()
        assert "report-uri https://example.com/csp-report" in header

    def test_report_to(self):
        header = CSP().report_to("csp-endpoint").to_header()
        assert "report-to csp-endpoint" in header

    def test_chaining(self):
        header = (
            CSP()
            .default_src("'none'")
            .script_src("'self'")
            .style_src("'self'", "https://fonts.googleapis.com")
            .img_src("'self'", "data:")
            .to_header()
        )
        assert "default-src 'none'" in header
        assert "script-src 'self'" in header
        assert "style-src 'self' https://fonts.googleapis.com" in header
        assert "img-src 'self' data:" in header

    def test_to_dict(self):
        csp = CSP().default_src("'self'").img_src("*")
        d = csp.to_dict()
        assert d["default-src"] == ["'self'"]
        assert d["img-src"] == ["*"]

    def test_parse_roundtrip(self):
        original = CSP().default_src("'self'").script_src("'self'", "'strict-dynamic'")
        parsed = CSP.parse(original.to_header())
        assert parsed.to_dict() == original.to_dict()

    def test_is_valid_directive(self):
        assert CSP.is_valid_directive("default-src")
        assert CSP.is_valid_directive("script-src")
        assert not CSP.is_valid_directive("invalid-src")

    def test_strict_policy(self):
        csp = CSP.strict_policy()
        header = csp.to_header()
        assert "base-uri 'self'" in header
        assert "object-src 'none'" in header
        assert "frame-ancestors 'none'" in header

    def test_strict_policy_with_nonce(self):
        nonce = generate_nonce()
        csp = CSP.strict_policy(nonce=nonce)
        header = csp.to_header()
        assert f"'nonce-{nonce}'" in header
        assert "'strict-dynamic'" in header

    def test_multiple_calls_accumulate(self):
        csp = CSP()
        csp.script_src("'self'")
        csp.script_src("'unsafe-inline'")
        sources = csp.to_dict()["script-src"]
        assert "'self'" in sources
        assert "'unsafe-inline'" in sources
