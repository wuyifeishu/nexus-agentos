"""
URLSigner — HMAC-based signed URL generation and verification.

Supports:
    - Sign URLs with HMAC-SHA256
    - Expiry-based signed URLs
    - Path-based signature
    - Verification of signed URLs
    - Multiple signing algorithms (HS256, HS384, HS512)
"""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
from typing import Optional, Tuple


# ============================================================================
# URLSigner
# ============================================================================

class URLSigner:
    """HMAC-based URL signing for secure temporary links.

    Usage:
        signer = URLSigner(secret="my-secret-key")

        # Generate a signed URL that expires in 1 hour
        signed = signer.sign("https://example.com/files/report.pdf", ttl=3600)
        # → https://example.com/files/report.pdf?sig=...&exp=...

        # Verify a signed URL
        ok, path = signer.verify(signed)
        if ok:
            serve(path)
    """

    def __init__(self, secret: str, algorithm: str = "HS256"):
        self._secret = secret.encode("utf-8")
        algorithms = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}
        if algorithm not in algorithms:
            raise ValueError(f"Unsupported algorithm: {algorithm}. Use HS256/HS384/HS512")
        self._hash_func = algorithms[algorithm]
        self._algorithm = algorithm

    def sign(
        self,
        url: str,
        ttl: Optional[float] = None,
        extra_params: Optional[dict] = None,
    ) -> str:
        """Sign a URL with optional TTL and extra params.

        Args:
            url: The URL to sign
            ttl: Time-to-live in seconds. None = no expiry
            extra_params: Additional query params to include in signature
        """
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))

        # Build signature payload
        path = parsed.path
        if extra_params:
            for k, v in sorted(extra_params.items()):
                params[k] = str(v)

        if ttl is not None:
            exp = int(time.time() + ttl)
            params["exp"] = str(exp)

        # Generate signature over path + sorted params
        sig = self._compute_signature(path, params)

        params["sig"] = sig

        new_query = urllib.parse.urlencode(params)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))

    def verify(self, url: str) -> Tuple[bool, Optional[str]]:
        """Verify a signed URL. Returns (is_valid, error_message)."""
        parsed = urllib.parse.urlparse(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))

        sig = params.pop("sig", None)
        if not sig:
            return False, "Missing signature"

        # Check expiry (do not pop — must remain for signature recalculation)
        exp = params.get("exp")
        if exp:
            exp_val = int(exp)
            if time.time() > exp_val:
                return False, f"URL expired at {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(exp_val))}"

        # Recompute
        path = parsed.path
        expected = self._compute_signature(path, params)

        if not hmac.compare_digest(sig, expected):
            return False, "Invalid signature"

        return True, None

    def _compute_signature(self, path: str, params: dict) -> str:
        data = path.encode("utf-8")
        for k in sorted(params.keys()):
            v = params[k]
            data += f"|{k}={v}".encode("utf-8")
        return hmac.new(self._secret, data, self._hash_func).hexdigest()
