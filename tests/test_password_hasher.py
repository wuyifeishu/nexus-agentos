"""Tests for agentos.tools.password_hasher."""

from agentos.tools.password_hasher import PasswordHasher


class TestPasswordHasher:
    def test_hash_and_verify(self):
        ph = PasswordHasher()
        hashed = ph.hash("my-secret-password")
        valid, needs_upgrade = ph.verify("my-secret-password", hashed)
        assert valid
        assert not needs_upgrade

    def test_verify_wrong_password(self):
        ph = PasswordHasher()
        hashed = ph.hash("correct-password")
        valid, needs_upgrade = ph.verify("wrong-password", hashed)
        assert not valid
        assert not needs_upgrade

    def test_hash_is_different_each_time(self):
        ph = PasswordHasher()
        h1 = ph.hash("password")
        h2 = ph.hash("password")
        assert h1 != h2

    def test_verify_still_works_with_different_salts(self):
        ph = PasswordHasher()
        h1 = ph.hash("password")
        h2 = ph.hash("password")
        assert ph.verify("password", h1)[0]
        assert ph.verify("password", h2)[0]

    def test_hash_format(self):
        ph = PasswordHasher()
        hashed = ph.hash("password")
        parts = hashed.split("$")
        assert len(parts) == 5
        assert parts[0] == ""
        assert parts[1] == "pbkdf2-sha256"
        assert parts[2] == "100000"

    def test_needs_upgrade_lower_iterations(self):
        ph_old = PasswordHasher(iterations=10000)
        ph_new = PasswordHasher(iterations=200000)
        hashed = ph_old.hash("password")
        assert ph_new.needs_upgrade(hashed)
        valid, needs_upgrade = ph_new.verify("password", hashed)
        assert valid
        assert needs_upgrade

    def test_needs_upgrade_same_iterations(self):
        ph = PasswordHasher()
        hashed = ph.hash("password")
        assert not ph.needs_upgrade(hashed)

    def test_needs_upgrade_invalid_hash(self):
        ph = PasswordHasher()
        assert ph.needs_upgrade("not-a-valid-hash")

    def test_verify_empty_password(self):
        ph = PasswordHasher()
        hashed = ph.hash("")
        valid, _ = ph.verify("", hashed)
        assert valid

    def test_verify_long_password(self):
        ph = PasswordHasher()
        long_pw = "x" * 1000
        hashed = ph.hash(long_pw)
        valid, _ = ph.verify(long_pw, hashed)
        assert valid

    def test_verify_inconsistent_password(self):
        ph = PasswordHasher()
        hashed = ph.hash("hello")
        valid, _ = ph.verify("HELLO", hashed)
        assert not valid

    def test_parse_invalid_format(self):
        ph = PasswordHasher()
        # Not a valid hash format
        valid, _ = ph.verify("test", "garbage")
        assert not valid
