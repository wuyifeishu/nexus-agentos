"""Tests for agentos.tools.jwt."""

import json
import time

import pytest

from agentos.tools.jwt import JWT, ExpiredTokenError, InvalidTokenError


class TestJWT:
    SECRET = "super-secret-key-for-testing"

    def test_encode_decode(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123", "role": "admin"})
        payload = jwt.decode(token)
        assert payload["sub"] == "user123"
        assert payload["role"] == "admin"

    def test_encode_with_ttl(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123"}, ttl=3600)
        payload = jwt.decode(token)
        assert payload["sub"] == "user123"
        assert "exp" in payload
        assert "iat" in payload

    def test_expired_token(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123"}, ttl=0)
        time.sleep(0.1)
        with pytest.raises(ExpiredTokenError):
            jwt.decode(token)

    def test_invalid_signature(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123"})
        # Tamper with payload
        parts = token.split(".")
        tampered = parts[0] + "." + parts[1] + ".deadbeef"
        with pytest.raises(InvalidTokenError):
            jwt.decode(tampered)

    def test_verify_false(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123"})
        payload = jwt.decode(token, verify=False)
        assert payload["sub"] == "user123"

    def test_decode_unverified(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123"})
        payload = JWT.decode_unverified(token)
        assert payload["sub"] == "user123"

    def test_invalid_token_format(self):
        jwt = JWT(secret=self.SECRET)
        with pytest.raises(InvalidTokenError):
            jwt.decode("not.a.valid.jwt.token")

    def test_algorithm_mismatch(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123"})
        # Change algorithm in header
        parts = token.split(".")
        import base64
        header = {"alg": "HS384", "typ": "JWT"}
        new_header = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
        tampered = new_header + "." + parts[1] + "." + parts[2]
        with pytest.raises(InvalidTokenError):
            jwt.decode(tampered)

    def test_audience_validation(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123", "aud": "my-api"})
        payload = jwt.decode(token, audience="my-api")
        assert payload["sub"] == "user123"

    def test_audience_mismatch(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123", "aud": "my-api"})
        with pytest.raises(InvalidTokenError):
            jwt.decode(token, audience="other-api")

    def test_issuer_validation(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123", "iss": "auth.example.com"})
        payload = jwt.decode(token, issuer="auth.example.com")
        assert payload["sub"] == "user123"

    def test_issuer_mismatch(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123", "iss": "auth.example.com"})
        with pytest.raises(InvalidTokenError):
            jwt.decode(token, issuer="evil.com")

    def test_not_before(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123", "nbf": int(time.time()) + 3600})
        with pytest.raises(InvalidTokenError):
            jwt.decode(token)

    def test_custom_claims(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123", "custom_field": 42, "roles": ["admin", "editor"]})
        payload = jwt.decode(token)
        assert payload["custom_field"] == 42
        assert "admin" in payload["roles"]

    def test_get_header(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123"})
        header = JWT.get_header(token)
        assert header["alg"] == "HS256"
        assert header["typ"] == "JWT"

    def test_missing_algorithm_verify(self):
        jwt = JWT(secret=self.SECRET)
        token = jwt.encode({"sub": "user123"})
        # Remove algorithm from header
        parts = token.split(".")
        import base64
        header = {"typ": "JWT"}
        new_header = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
        tampered = new_header + "." + parts[1] + "." + parts[2]
        with pytest.raises(InvalidTokenError):
            jwt.decode(tampered)

    def test_invalid_algorithm_constructor(self):
        with pytest.raises(ValueError):
            JWT(secret=self.SECRET, algorithm="NONE")

    def test_hs_missing_secret(self):
        with pytest.raises(ValueError):
            JWT(algorithm="HS256")
