"""Tests for agentos.tools.url_signer."""

import time

import pytest

from agentos.tools.url_signer import URLSigner


class TestURLSigner:
    def test_sign_and_verify(self):
        signer = URLSigner(secret="test-key")
        signed = signer.sign("https://example.com/files/a.pdf")
        ok, err = signer.verify(signed)
        assert ok
        assert err is None

    def test_verify_invalid_signature(self):
        signer = URLSigner(secret="test-key")
        signed = signer.sign("https://example.com/a.pdf")
        # Tamper with signature
        tampered = signed.replace("sig=", "sig=deadbeef")
        ok, err = signer.verify(tampered)
        assert not ok
        assert "Invalid" in err

    def test_verify_missing_signature(self):
        signer = URLSigner(secret="test-key")
        ok, err = signer.verify("https://example.com/a.pdf")
        assert not ok
        assert "Missing" in err

    def test_sign_with_ttl(self):
        signer = URLSigner(secret="test-key")
        signed = signer.sign("https://example.com/a.pdf", ttl=3600)
        ok, err = signer.verify(signed)
        assert ok

    def test_expired_url(self):
        signer = URLSigner(secret="test-key")
        signed = signer.sign("https://example.com/a.pdf", ttl=0)
        time.sleep(0.1)
        ok, err = signer.verify(signed)
        assert not ok
        assert "expired" in err

    def test_different_secrets_fail(self):
        s1 = URLSigner(secret="key-a")
        s2 = URLSigner(secret="key-b")
        signed = s1.sign("https://example.com/a.pdf")
        ok, _ = s2.verify(signed)
        assert not ok

    def test_extra_params_included_in_signature(self):
        signer = URLSigner(secret="test-key")
        signed = signer.sign(
            "https://example.com/a.pdf",
            extra_params={"user": "42", "role": "admin"},
        )
        ok, _ = signer.verify(signed)
        assert ok

    def test_extra_params_tampered(self):
        signer = URLSigner(secret="test-key")
        signed = signer.sign(
            "https://example.com/a.pdf",
            extra_params={"user": "42"},
        )
        tampered = signed.replace("user=42", "user=99")
        ok, _ = signer.verify(tampered)
        assert not ok

    def test_path_changes_invalid(self):
        signer = URLSigner(secret="test-key")
        signed = signer.sign("https://example.com/private/a.pdf")
        # Change path
        tampered = signed.replace("/private/", "/public/")
        ok, _ = signer.verify(tampered)
        assert not ok

    def test_deterministic_same_input(self):
        signer = URLSigner(secret="test-key")
        s1 = signer.sign("https://example.com/a.pdf")
        s2 = signer.sign("https://example.com/a.pdf")
        assert s1 == s2

    def test_different_urls_different_sig(self):
        signer = URLSigner(secret="test-key")
        s1 = signer.sign("https://example.com/a.pdf")
        s2 = signer.sign("https://example.com/b.pdf")
        assert s1 != s2

    def test_algorithm_hs512(self):
        signer = URLSigner(secret="test-key", algorithm="HS512")
        signed = signer.sign("https://example.com/a.pdf")
        ok, _ = signer.verify(signed)
        assert ok

    def test_invalid_algorithm(self):
        with pytest.raises(ValueError):
            URLSigner(secret="x", algorithm="MD5")
