"""
TOTP — Time-based One-Time Password (RFC 6238).

Supports:
    - TOTP generation (SHA1/SHA256/SHA512)
    - Configurable digits (6/8) and period (30s default)
    - Key URI generation for QR codes (otpauth://)
    - Verification with drift tolerance
    - HOTP (counter-based) support (RFC 4226)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from typing import Optional, Tuple
from urllib.parse import quote, urlencode


# ============================================================================
# TOTP / HOTP
# ============================================================================

class TOTP:
    """Time-based One-Time Password generator (RFC 6238).

    Usage:
        totp = TOTP(secret="JBSWY3DPEHPK3PXP")
        code = totp.now()               # 6-digit code
        ok = totp.verify(code)          # True/False
        uri = totp.to_uri("user@example.com", "MyApp")  # QR code URI
    """

    def __init__(
        self,
        secret: str,
        digits: int = 6,
        period: int = 30,
        algorithm: str = "SHA1",
    ):
        self._secret = secret.upper().replace(" ", "")
        self._digits = digits
        self._period = period
        algorithms = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}
        if algorithm not in algorithms:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
        self._hash_func = algorithms[algorithm]
        self._algorithm = algorithm

    @property
    def secret(self) -> str:
        return self._secret

    @property
    def digits(self) -> int:
        return self._digits

    @property
    def period(self) -> int:
        return self._period

    @property
    def algorithm(self) -> str:
        return self._algorithm

    # ---------- Generation ----------

    def now(self) -> str:
        """Generate the current TOTP code."""
        return self.at(int(time.time()))

    def at(self, timestamp: int) -> str:
        """Generate TOTP code for a specific Unix timestamp."""
        counter = timestamp // self._period
        return self._generate(counter)

    # ---------- Verification ----------

    def verify(
        self,
        code: str,
        drift: int = 1,
        timestamp: Optional[int] = None,
    ) -> bool:
        """Verify a TOTP code with optional drift tolerance.

        Args:
            code: The code to verify
            drift: Number of periods before/after to check (default 1 = +/-30s)
            timestamp: Reference timestamp, defaults to now
        """
        ts = timestamp or int(time.time())
        for offset in range(-drift, drift + 1):
            if self.at(ts + offset * self._period) == code:
                return True
        return False

    # ---------- URI ----------

    def to_uri(self, account: str, issuer: Optional[str] = None) -> str:
        """Generate otpauth:// URI for QR code.

        Args:
            account: User account (e.g., email)
            issuer: Service name
        """
        label = account
        if issuer:
            label = f"{issuer}:{account}"

        params = {
            "secret": self._secret,
            "digits": str(self._digits),
            "period": str(self._period),
            "algorithm": self._algorithm,
        }
        if issuer:
            params["issuer"] = issuer

        query = urlencode(params)
        return f"otpauth://totp/{quote(label)}?{query}"

    # ---------- Internal ----------

    def _generate(self, counter: int) -> str:
        """Generate HOTP code for a given counter."""
        key = base64.b64decode(self._pad_base64(self._secret))
        msg = struct.pack(">Q", counter)
        h = hmac.new(key, msg, self._hash_func).digest()
        offset = h[-1] & 0x0F
        binary = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
        mod = 10 ** self._digits
        return str(binary % mod).zfill(self._digits)

    @staticmethod
    def _pad_base64(s: str) -> str:
        """Pad base32 string for base64 decoding (base32 → base64)."""
        # Convert base32 to bytes, then encode as base64
        # Standard base32 alphabet: A-Z 2-7, padding =
        missing_padding = len(s) % 8
        if missing_padding:
            s += "=" * (8 - missing_padding)
        raw = base64.b32decode(s)
        return base64.b64encode(raw).decode("ascii")

    @classmethod
    def generate_secret(cls, length: int = 32) -> str:
        """Generate a random base32 secret."""
        import secrets
        raw = secrets.token_bytes(length)
        return base64.b32encode(raw).decode("ascii").rstrip("=")


class HOTP(TOTP):
    """HMAC-based One-Time Password (RFC 4226).

    Usage:
        hotp = HOTP(secret="JBSWY3DPEHPK3PXP")
        code = hotp.at(0)   # Generate for counter 0
        ok = hotp.verify(code, counter=0)
    """

    def __init__(
        self,
        secret: str,
        digits: int = 6,
        algorithm: str = "SHA1",
    ):
        super().__init__(secret=secret, digits=digits, period=1, algorithm=algorithm)

    def at(self, counter: int) -> str:
        return self._generate(counter)

    def verify(
        self,
        code: str,
        counter: int,
        look_ahead: int = 10,
    ) -> Tuple[bool, Optional[int]]:
        """Verify HOTP code, returns (is_valid, matched_counter)."""
        for c in range(counter, counter + look_ahead + 1):
            if self.at(c) == code:
                return True, c
        return False, None
