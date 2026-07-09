"""Tests for agentos.tools.id_generator."""

import time

import pytest

from agentos.tools.id_generator import (
    Snowflake,
    generate,
    nanoid,
    short_id,
    ulid,
    uuid4,
    uuid7,
)


class TestUUID7:
    def test_format(self):
        uid = uuid7()
        parts = uid.split("-")
        assert len(parts) == 5
        assert parts[2][0] == "7"  # version nibble

    def test_time_ordering(self):
        ids = [uuid7() for _ in range(10)]
        time.sleep(0.01)
        ids += [uuid7() for _ in range(5)]
        # Verify timestamp portions are monotonically increasing
        ts_parts = [uid.split("-")[0] + uid.split("-")[1] for uid in ids]
        assert ts_parts == sorted(ts_parts)

    def test_uniqueness(self):
        ids = {uuid7() for _ in range(100)}
        assert len(ids) == 100


class TestULID:
    def test_length(self):
        u = ulid()
        assert len(u) == 26

    def test_crockford_chars(self):
        from agentos.tools.id_generator import _CROCKFORD
        u = ulid()
        assert all(c in _CROCKFORD for c in u)

    def test_time_ordering(self):
        ids = [ulid() for _ in range(5)]
        time.sleep(0.01)
        ids += [ulid() for _ in range(5)]
        # First 10 chars are timestamp — must be monotonically increasing
        ts_parts = [uid[:10] for uid in ids]
        assert ts_parts == sorted(ts_parts)

    def test_uniqueness(self):
        ids = {ulid() for _ in range(100)}
        assert len(ids) == 100


class TestNanoID:
    def test_default_length(self):
        uid = nanoid()
        assert len(uid) == 21

    def test_custom_length(self):
        uid = nanoid(size=10)
        assert len(uid) == 10

    def test_custom_alphabet(self):
        uid = nanoid(alphabet="abc")
        assert all(c in "abc" for c in uid)

    def test_uniqueness(self):
        ids = {nanoid() for _ in range(100)}
        assert len(ids) == 100


class TestSnowflake:
    def test_generate_int(self):
        sf = Snowflake(worker_id=1)
        sid = sf.generate()
        assert sid > 0

    def test_generate_str(self):
        sf = Snowflake()
        sid = sf.generate_str()
        assert sid.isdigit()

    def test_uniqueness(self):
        sf = Snowflake()
        ids = {sf.generate() for _ in range(100)}
        assert len(ids) == 100

    def test_monotonic(self):
        sf = Snowflake()
        prev = sf.generate()
        for _ in range(100):
            cur = sf.generate()
            assert cur > prev
            prev = cur

    def test_invalid_worker_id(self):
        with pytest.raises(ValueError):
            Snowflake(worker_id=1024)

    def test_different_workers(self):
        sf1 = Snowflake(worker_id=0)
        sf2 = Snowflake(worker_id=1)
        id1 = sf1.generate()
        id2 = sf2.generate()
        assert id1 != id2


class TestShortID:
    def test_default_length(self):
        sid = short_id()
        assert len(sid) == 8

    def test_custom_length(self):
        sid = short_id(length=12)
        assert len(sid) == 12

    def test_no_ambiguous_chars(self):
        sid = short_id(length=100)
        ambiguous = "0O1Il"
        assert not any(c in ambiguous for c in sid)

    def test_uniqueness(self):
        ids = {short_id() for _ in range(100)}
        assert len(ids) == 100


class TestUUID4:
    def test_format(self):
        uid = uuid4()
        assert len(uid) == 36
        assert uid[14] == "4"

    def test_uniqueness(self):
        ids = {uuid4() for _ in range(100)}
        assert len(ids) == 100


class TestGenerate:
    def test_all_styles(self):
        for style in ("uuid4", "uuid7", "ulid", "nanoid", "short"):
            uid = generate(style)
            assert isinstance(uid, str)
            assert len(uid) > 0

    def test_invalid_style(self):
        with pytest.raises(ValueError):
            generate("invalid")
