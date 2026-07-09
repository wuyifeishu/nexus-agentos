"""Tests for agentos.tools.request_deduplicator."""

import threading
import time

from agentos.tools.request_deduplicator import RequestDeduplicator, ResultStatus


class TestRequestDeduplicator:
    def test_create_key_deterministic(self):
        dedup = RequestDeduplicator()
        k1 = dedup.create_key(method="POST", path="/api", body={"a": 1})
        k2 = dedup.create_key(method="POST", path="/api", body={"a": 1})
        assert k1 == k2

    def test_create_key_different_args(self):
        dedup = RequestDeduplicator()
        k1 = dedup.create_key(method="POST", path="/api")
        k2 = dedup.create_key(method="GET", path="/api")
        assert k1 != k2

    def test_get_miss(self):
        dedup = RequestDeduplicator()
        assert dedup.get("nonexistent") is None

    def test_complete_and_get(self):
        dedup = RequestDeduplicator()
        key = "test-key"
        assert dedup.mark_in_flight(key)
        dedup.complete(key, "result-value")

        entry = dedup.get(key)
        assert entry is not None
        assert entry.value == "result-value"
        assert entry.status == ResultStatus.COMPLETED

    def test_ttl_expiry(self):
        dedup = RequestDeduplicator(ttl=0.2)
        key = "ttl-key"
        dedup.mark_in_flight(key)
        dedup.complete(key, "val")
        assert dedup.get(key) is not None
        time.sleep(0.3)
        assert dedup.get(key) is None

    def test_mark_in_flight_second_caller_false(self):
        dedup = RequestDeduplicator()
        key = "dup-key"
        assert dedup.mark_in_flight(key) is True
        assert dedup.mark_in_flight(key) is False

    def test_wait_in_flight(self):
        dedup = RequestDeduplicator()
        key = "wait-key"
        assert dedup.mark_in_flight(key)

        results = []

        def waiter():
            res = dedup.wait_in_flight(key, timeout=5.0)
            results.append(res)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        dedup.complete(key, "done")
        t.join(timeout=2)
        assert results == ["done"]

    def test_error_handling(self):
        dedup = RequestDeduplicator()
        key = "error-key"
        dedup.mark_in_flight(key)
        dedup.error(key, ValueError("bad"))

        # get() doesn't cache errors
        assert dedup.get("error-key") is None

    def test_concurrent_dedup_decorator(self):
        dedup = RequestDeduplicator(ttl=10.0)
        calls = []
        results = []

        def key_fn(a, b):
            return f"{a}_{b}"

        @dedup.deduplicate(key_fn=key_fn, wait_timeout=5.0)
        def slow_add(a, b):
            calls.append(threading.current_thread().name)
            time.sleep(0.3)
            return a + b

        r_container = []

        def call_in_thread():
            r = slow_add(3, 4)
            results.append(r)

        t1 = threading.Thread(target=call_in_thread)
        t2 = threading.Thread(target=call_in_thread)
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join()
        t2.join()

        # Only one actual call, both get same result
        assert len(calls) == 1
        assert results == [7, 7]

    def test_decorator_cached_replay(self):
        dedup = RequestDeduplicator(ttl=10.0)
        counts = []

        def key_fn(x):
            return str(x)

        @dedup.deduplicate(key_fn=key_fn)
        def compute(x):
            counts.append(1)
            return x * 2

        r1 = compute(5)  # first call — executes
        r2 = compute(5)  # second call — cached
        assert r1 == 10
        assert r2 == 10
        assert len(counts) == 1

    def test_cache_size_limit(self):
        dedup = RequestDeduplicator(max_entries=3, ttl=999)
        for i in range(5):
            key = f"k{i}"
            dedup.mark_in_flight(key)
            dedup.complete(key, i)
        assert dedup.cache_size <= 3

    def test_clear(self):
        dedup = RequestDeduplicator()
        key = "clear-test"
        dedup.mark_in_flight(key)
        dedup.complete(key, "v")
        dedup.clear()
        assert dedup.get(key) is None
        assert dedup.cache_size == 0
        assert dedup.in_flight_count == 0

    def test_get_or_none(self):
        dedup = RequestDeduplicator()
        key = "gn"
        dedup.mark_in_flight(key)
        dedup.complete(key, 42)
        assert dedup.get_or_none(key) == 42
        assert dedup.get_or_none("no") is None
