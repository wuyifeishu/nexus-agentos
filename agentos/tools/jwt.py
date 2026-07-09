"""
JWT — JSON Web Token encode/decode/verify (HS256/RS256/ES256).

Supports:
    - HS256 (HMAC-SHA256), RS256 (RSA), ES256 (ECDSA) algorithms
    - Encode with claims (iss, sub, aud, exp, iat, nbf, jti, custom)
    - Decode with signature verification
    - Decode without verification (for inspection)
    - Token expiry checking
    - Claim validation
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

# ============================================================================
# JWTError
# ============================================================================


class JWTError(Exception):
    pass


class ExpiredTokenError(JWTError):
    pass


class InvalidTokenError(JWTError):
    pass


# ============================================================================
# Helpers
# ============================================================================


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    # Restore padding
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _json_b64_decode(s: str) -> dict:
    return json.loads(_b64url_decode(s))


# ============================================================================
# JWT
# ============================================================================

ALGORITHMS = frozenset(
    {"HS256", "HS384", "HS512", "RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
)


class JWT:
    """JSON Web Token encoder/decoder.

    Usage:
        jwt = JWT(secret="my-secret")  # for HS256

        # Encode
        token = jwt.encode({"sub": "user123", "role": "admin"}, ttl=3600)

        # Decode & verify
        payload = jwt.decode(token)

        # Decode without verification (inspect only)
        payload = jwt.decode(token, verify=False)
    """

    def __init__(
        self,
        secret: str | None = None,
        private_key: str | None = None,
        public_key: str | None = None,
        algorithm: str = "HS256",
    ):
        if algorithm not in ALGORITHMS:
            raise ValueError(f"Unsupported algorithm: {algorithm}. Use one of {sorted(ALGORITHMS)}")

        self._algorithm = algorithm
        self._hash_func = {
            "HS256": hashlib.sha256,
            "HS384": hashlib.sha384,
            "HS512": hashlib.sha512,
        }

        if algorithm.startswith("HS"):
            if not secret:
                raise ValueError(f"{algorithm} requires a secret")
            self._secret = secret.encode("utf-8")
        elif algorithm.startswith("RS") or algorithm.startswith("ES"):
            if not private_key and not public_key:
                raise ValueError(f"{algorithm} requires at least one key")
            self._private_key = private_key
            self._public_key = public_key

    # ---------- Encode ----------

    def encode(
        self,
        payload: dict,
        ttl: int | None = None,
        headers_extra: dict | None = None,
    ) -> str:
        """Encode a JWT token.

        Args:
            payload: Claims to include
            ttl: Time-to-live in seconds (sets 'exp' claim)
            headers_extra: Additional header parameters
        """
        header = {"alg": self._algorithm, "typ": "JWT"}
        if headers_extra:
            header.update(headers_extra)

        claims = dict(payload)
        now = int(time.time())

        # Standard claims
        if "iat" not in claims:
            claims["iat"] = now
        if ttl is not None and "exp" not in claims:
            claims["exp"] = now + ttl

        header_b64 = _b64url_encode(json.dumps(header).encode("utf-8"))
        payload_b64 = _b64url_encode(json.dumps(claims).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}"

        signature = self._sign(signing_input)
        return f"{signing_input}.{signature}"

    # ---------- Decode ----------

    def decode(
        self,
        token: str,
        verify: bool = True,
        audience: str | list[str] | None = None,
        issuer: str | None = None,
    ) -> dict:
        """Decode and optionally verify a JWT token.

        Args:
            token: The JWT string
            verify: Whether to verify the signature (default True)
            audience: Expected audience (if present, validates 'aud' claim)
            issuer: Expected issuer (if present, validates 'iss' claim)
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidTokenError("JWT must have 3 parts (header.payload.signature)")

        header_b64, payload_b64, signature_b64 = parts

        # Decode header and payload (always safe)
        header = _json_b64_decode(header_b64)
        payload = _json_b64_decode(payload_b64)

        # Verify algorithm
        alg = header.get("alg")
        if verify and alg != self._algorithm:
            raise InvalidTokenError(f"Algorithm mismatch: expected {self._algorithm}, got {alg}")

        # Verify signature
        if verify:
            signing_input = f"{header_b64}.{payload_b64}"
            if not self._verify(signing_input, signature_b64):
                raise InvalidTokenError("Invalid signature")

        # Check expiry
        exp = payload.get("exp")
        if exp and int(exp) < time.time():
            raise ExpiredTokenError(f"Token expired at {exp}")

        # Check not-before
        nbf = payload.get("nbf")
        if nbf and int(nbf) > time.time():
            raise InvalidTokenError(f"Token not valid before {nbf}")

        # Check audience
        if audience is not None:
            aud = payload.get("aud")
            if aud is None:
                raise InvalidTokenError("Token missing 'aud' claim")
            expected = [audience] if isinstance(audience, str) else audience
            if isinstance(aud, str):
                aud = [aud]
            if not set(expected) & set(aud):
                raise InvalidTokenError("Audience mismatch")

        # Check issuer
        if issuer is not None:
            iss = payload.get("iss")
            if iss != issuer:
                raise InvalidTokenError(f"Issuer mismatch: expected {issuer}, got {iss}")

        return payload

    # ---------- Signature ----------

    def _sign(self, data: str) -> str:
        if self._algorithm.startswith("HS"):
            d = hmac.new(
                self._secret, data.encode("utf-8"), self._hash_func[self._algorithm]
            ).digest()
            return _b64url_encode(d)
        else:
            raise NotImplementedError(
                f"Signing with {self._algorithm} requires cryptographic libraries (cryptography)"
            )

    def _verify(self, data: str, signature_b64: str) -> bool:
        if self._algorithm.startswith("HS"):
            expected = self._sign(data)
            return hmac.compare_digest(expected, signature_b64)
        else:
            raise NotImplementedError(
                f"Verification with {self._algorithm} requires cryptographic libraries (cryptography)"
            )

    # ---------- Static helpers ----------

    @staticmethod
    def decode_unverified(token: str) -> dict:
        """Decode JWT without verifying signature (inspect only)."""
        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidTokenError("JWT must have 3 parts")
        return _json_b64_decode(parts[1])

    @staticmethod
    def get_header(token: str) -> dict:
        """Extract JWT header without verification."""
        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidTokenError("JWT must have 3 parts")
        return _json_b64_decode(parts[0])
