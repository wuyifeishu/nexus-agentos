"""Tests for agentos.tools.request_deduplicator — fingerprint-based request dedup."""

import time

import pytest

from agentos.tools.request_deduplicator import (
    DedupResult,
    RequestDeduplicator,
    ResultStatus,
)


class TestDedupResult:
    def test_completed(self):
        r = DedupResult(ResultStatus.COMPLETED, "ok")
        assert r.status == ResultStatus.COMPLETED
        assert r.value == "ok"
        assert r.timestamp > 0

    def test_error(self):
        r = DedupResult(ResultStatus.ERROR, RuntimeError("boom"))
        assert r.status == ResultStatus.ERROR
        assert isinstance(r.value, RuntimeError)


class TestCreateKey:
    def test_identical_args_same_key(self):
        d = RequestDeduplicator()
        k1 = d.create_key(method="POST", path="/api", body={"a": 1})
        k2 = d.create_key(body={"a": 1}, path="/api", method="POST")
        assert k1 == k2

    def test_different_args_different_key(self):
        d = RequestDeduplicator()
        k1 = d.create_key(method="GET", path="/a")
        k2 = d.create_key(method="POST", path="/b")
        assert k1 != k2

    def test_key_prefix(self):
        d = RequestDeduplicator(key_prefix="my:")
        key = d.create_key("hello")
        assert key.startswith("my:")

    def test_positional_sensitive(self):
        d = RequestDeduplicator()
        k1 = d.create_key("a", "b")
        k2 = d.create_key("b", "a")
        assert k1 != k2  # positional args matter


class TestCacheLookup:
    def test_get_missing(self):
        d = RequestDeduplicator()
        assert d.get("nonexistent") is None

    def test_complete_then_get(self):
        d = RequestDeduplicator()
        d.mark_in_flight("k1")
        d.complete("k1", {"data": 42})
        entry = d.get("k1")
        assert entry is not None
        assert entry.value == {"data": 42}

    def test_ttl_expiry(self):
        d = RequestDeduplicator(ttl=0.01)
        d.mark_in_flight("k1")
        d.complete("k1", "val")
        time.sleep(0.02)
        assert d.get("k1") is None

    def test_get_or_none(self):
        d = RequestDeduplicator()
        d.mark_in_flight("k")
        d.complete("k", "hello")
        assert d.get_or_none("k") == "hello"
        assert d.get_or_none("ghost") is None


class TestInFlight:
    def test_mark_in_flight_first_wins(self):
        d = RequestDeduplicator()
        assert d.mark_in_flight("key") is True
        assert d.mark_in_flight("key") is False

    def test_wait_in_flight_gets_result(self):
        d = RequestDeduplicator()
        assert d.mark_in_flight("key") is True
        d.complete("key", "result")
        assert d.wait_in_flight("key") == "result"

    def test_wait_in_flight_timeout(self):
        d = RequestDeduplicator()
        d.mark_in_flight("stuck")
        # never complete — should return None on timeout
        result = d.wait_in_flight("stuck", timeout=0.01)
        assert result is None

    def test_wait_in_flight_nonexistent(self):
        d = RequestDeduplicator()
        assert d.wait_in_flight("ghost") is None

    def test_error_signal(self):
        d = RequestDeduplicator()
        d.mark_in_flight("e")
        d.error("e", ValueError("bad"))
        result = d.wait_in_flight("e")
        assert isinstance(result, ValueError)
        assert str(result) == "bad"

    def test_in_flight_count(self):
        d = RequestDeduplicator()
        assert d.in_flight_count == 0
        d.mark_in_flight("a")
        d.mark_in_flight("b")
        assert d.in_flight_count == 2


class TestEviction:
    def test_max_entries_evicts_oldest(self):
        d = RequestDeduplicator(max_entries=2)
        keys = []
        for i in range(3):
            k = d.create_key(f"item_{i}")
            d.mark_in_flight(k)
            d.complete(k, i)
            keys.append(k)
            time.sleep(0.002)
        assert d.cache_size <= 2

    def test_clear(self):
        d = RequestDeduplicator()
        d.mark_in_flight("k")
        d.complete("k", 1)
        d.clear()
        assert d.cache_size == 0
        assert d.in_flight_count == 0


class TestDecorator:
    def test_deduplicate_basic(self):
        d = RequestDeduplicator()
        call_count = [0]

        @d.deduplicate(key_fn=lambda x: f"item:{x}")
        def fetch(x):
            call_count[0] += 1
            return f"result:{x}"

        r1 = fetch(1)
        r2 = fetch(1)  # cached
        assert r1 == "result:1"
        assert r2 == "result:1"
        assert call_count[0] == 1  # only called once

    def test_deduplicate_different_key(self):
        d = RequestDeduplicator()
        call_count = [0]

        @d.deduplicate(key_fn=lambda x, y: f"{x}:{y}")
        def add(a, b):
            call_count[0] += 1
            return a + b

        assert add(1, 2) == 3
        assert add(2, 3) == 5
        assert call_count[0] == 2

    def test_deduplicate_error_propagates(self):
        d = RequestDeduplicator()

        @d.deduplicate(key_fn=lambda: "fixed", cache_errors=False)
        def boom():
            raise ValueError("bang")

        with pytest.raises(ValueError, match="bang"):
            boom()

    def test_deduplicate_cache_errors(self):
        """With cache_errors=True, errors are cached with COMPLETED status,
        so the second call returns the exception value (not raises it)."""
        d = RequestDeduplicator(ttl=60.0)

        @d.deduplicate(key_fn=lambda: "err_k", cache_errors=True)
        def bad():
            raise RuntimeError("oops")

        with pytest.raises(RuntimeError, match="oops"):
            bad()
        # second call returns cached result (exception object)
        result = bad()
        assert isinstance(result, RuntimeError)
        assert str(result) == "oops"


class TestCacheSize:
    def test_initial(self):
        d = RequestDeduplicator()
        assert d.cache_size == 0

    def test_after_complete(self):
        d = RequestDeduplicator()
        d.mark_in_flight("k")
        d.complete("k", "v")
        assert d.cache_size == 1
