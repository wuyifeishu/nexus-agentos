"""Tests for agentos.tools.totp."""

import pytest

from agentos.tools.totp import HOTP, TOTP


class TestTOTP:
    SECRET = "JBSWY3DPEHPK3PXP"

    def test_now(self):
        totp = TOTP(secret=self.SECRET)
        code = totp.now()
        assert len(code) == 6
        assert code.isdigit()

    def test_at(self):
        totp = TOTP(secret=self.SECRET)
        code1 = totp.at(0)
        code2 = totp.at(0)
        assert code1 == code2  # Deterministic

    def test_verify(self):
        totp = TOTP(secret=self.SECRET)
        code = totp.now()
        assert totp.verify(code)

    def test_verify_with_drift(self):
        totp = TOTP(secret=self.SECRET)
        code = totp.now()
        # Should still verify with drift=1
        assert totp.verify(code, drift=1)

    def test_wrong_code(self):
        totp = TOTP(secret=self.SECRET)
        # Only 0-9 digits possible in TOTP
        current = totp.now()
        wrong = str((int(current) + 1) % 1000000).zfill(6)
        if wrong == current:
            wrong = str((int(wrong) + 1) % 1000000).zfill(6)
        assert not totp.verify(wrong, drift=0)

    def test_digits_8(self):
        totp = TOTP(secret=self.SECRET, digits=8)
        code = totp.now()
        assert len(code) == 8
        assert code.isdigit()

    def test_period_custom(self):
        totp = TOTP(secret=self.SECRET, period=60)
        code = totp.now()
        assert len(code) == 6

    def test_algorithms(self):
        for algo in ("SHA1", "SHA256", "SHA512"):
            totp = TOTP(secret=self.SECRET, algorithm=algo)
            code = totp.now()
            assert len(code) == 6

    def test_invalid_algorithm(self):
        with pytest.raises(ValueError):
            TOTP(secret=self.SECRET, algorithm="MD5")

    def test_uri_generation(self):
        totp = TOTP(secret=self.SECRET)
        uri = totp.to_uri("user@example.com", "MyApp")
        assert uri.startswith("otpauth://totp/")
        assert "MyApp" in uri
        assert "user%40example.com" in uri
        assert self.SECRET in uri

    def test_generate_secret(self):
        secret = TOTP.generate_secret()
        assert len(secret) >= 16
        # base32 charset
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret)

    def test_secret_with_spaces(self):
        totp = TOTP(secret="JBSW Y3DP EHPK 3PXP")
        assert totp.secret == "JBSWY3DPEHPK3PXP"


class TestHOTP:
    def test_counter_increment(self):
        hotp = HOTP(secret=TestTOTP.SECRET)
        c0 = hotp.at(0)
        c1 = hotp.at(1)
        assert c0 != c1

    def test_verify(self):
        hotp = HOTP(secret=TestTOTP.SECRET)
        code = hotp.at(0)
        ok, matched = hotp.verify(code, counter=0)
        assert ok
        assert matched == 0

    def test_verify_look_ahead(self):
        hotp = HOTP(secret=TestTOTP.SECRET)
        code = hotp.at(5)
        ok, matched = hotp.verify(code, counter=0, look_ahead=5)
        assert ok
        assert matched == 5

    def test_verify_wrong(self):
        hotp = HOTP(secret=TestTOTP.SECRET)
        code = hotp.at(0)
        ok, matched = hotp.verify(str((int(code) + 1) % 1000000).zfill(6), counter=5, look_ahead=3)
        assert not ok
        assert matched is None
