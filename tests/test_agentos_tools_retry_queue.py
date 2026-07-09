"""Tests for agentos.tools.retry_queue — RetryJob, RetryQueue, BackoffStrategy."""

import pytest

from agentos.tools.retry_queue import (
    BackoffStrategy,
    RetryJob,
    RetryQueue,
)


class TestRetryJob:
    def test_execute(self):
        j = RetryJob(id="j1", func=lambda x: x * 2, args=(21,))
        assert j.execute() == 42

    def test_defaults(self):
        j = RetryJob(id="test", func=lambda: 1)
        assert j.attempts == 0
        assert j.last_error is None
        assert j.created_at > 0
        assert j.args == ()
        assert j.kwargs == {}


class TestRetryQueueInit:
    def test_defaults(self):
        rq = RetryQueue()
        assert rq._max_attempts == 3
        assert rq._base_delay == 1.0
        assert rq._max_delay == 60.0
        assert rq._backoff == BackoffStrategy.EXPONENTIAL
        assert rq._jitter is True

    def test_custom(self):
        rq = RetryQueue(max_attempts=5, base_delay=2.0, max_delay=30.0,
                        backoff=BackoffStrategy.CONSTANT, jitter=False)
        assert rq._max_attempts == 5
        assert rq._base_delay == 2.0
        assert rq._backoff == BackoffStrategy.CONSTANT

    def test_max_attempts_one(self):
        rq = RetryQueue(max_attempts=1)
        assert rq._max_attempts == 1

    def test_max_attempts_invalid(self):
        with pytest.raises(ValueError):
            RetryQueue(max_attempts=0)


class TestSubmitSuccess:
    def test_first_try(self):
        rq = RetryQueue()
        result = rq.submit(lambda a, b: a + b, 2, 3)
        assert result == 5

    def test_stats_after_success(self):
        rq = RetryQueue()
        rq.submit(lambda: "ok")
        s = rq.stats
        assert s["total_submitted"] == 1
        assert s["total_succeeded"] == 1
        assert s["total_failed"] == 0

    def test_retry_then_succeed(self):
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] < 3:
                raise RuntimeError("fail")
            return "ok"

        rq = RetryQueue(max_attempts=3, base_delay=0.01)
        result = rq.submit(flaky)
        assert result == "ok"
        assert counter[0] == 3


class TestSubmitFailure:
    def test_all_attempts_fail(self):
        rq = RetryQueue(max_attempts=2, base_delay=0.01)

        with pytest.raises(ValueError, match="always fail"):
            rq.submit(lambda: (_ for _ in ()).throw(ValueError("always fail")))

    def test_dead_letters(self):
        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        try:
            rq.submit(lambda: (_ for _ in ()).throw(KeyError("dead")))
        except KeyError:
            pass
        assert len(rq.dead_letters) == 1
        job, err = rq.dead_letters[0]
        assert isinstance(err, KeyError)

    def test_failed_stats(self):
        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        try:
            rq.submit(lambda: (_ for _ in ()).throw(Exception("x")))
        except Exception:
            pass
        s = rq.stats
        assert s["total_submitted"] == 1
        assert s["total_failed"] == 1
        assert s["dead_letter_count"] == 1


class TestClearDeadLetters:
    def test_clear(self):
        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        try:
            rq.submit(lambda: (_ for _ in ()).throw(Exception("x")))
        except Exception:
            pass
        assert len(rq.dead_letters) == 1
        rq.clear_dead_letters()
        assert len(rq.dead_letters) == 0


class TestRetryDeadLetter:
    def test_retry_success(self):
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] < 2:
                raise RuntimeError("fail")
            return "recovered"

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        try:
            rq.submit(flaky)
        except RuntimeError:
            pass
        assert len(rq.dead_letters) == 1
        result = rq.retry_dead_letter(0)
        assert result == "recovered"
        assert len(rq.dead_letters) == 0

    def test_retry_index_error(self):
        rq = RetryQueue()
        with pytest.raises(IndexError):
            rq.retry_dead_letter(0)


class TestHooks:
    def test_on_retry(self):
        events = []
        rq = RetryQueue(max_attempts=3, base_delay=0.01)
        rq.on_retry(lambda job, err, att: events.append(("retry", att)))

        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] < 2:
                raise RuntimeError("fail")
            return "ok"

        rq.submit(flaky)
        assert events == [("retry", 1)]

    def test_on_success(self):
        events = []
        rq = RetryQueue()
        rq.on_success(lambda job, result: events.append(("success", result)))
        rq.submit(lambda: 99)
        assert events == [("success", 99)]

    def test_on_failure(self):
        events = []
        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        rq.on_failure(lambda job, err: events.append(("fail", type(err).__name__)))
        try:
            rq.submit(lambda: (_ for _ in ()).throw(ValueError("oops")))
        except ValueError:
            pass
        assert len(events) == 1
        assert events[0] == ("fail", "ValueError")

    def test_on_retry_callback_error_suppressed(self):
        rq = RetryQueue(max_attempts=2, base_delay=0.01)
        rq.on_retry(lambda job, err, att: (_ for _ in ()).throw(RuntimeError("callback_bug")))
        # Should not propagate callback error
        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] < 2:
                raise RuntimeError("job_fail")
            return "ok"

        result = rq.submit(flaky)
        assert result == "ok"


class TestComputeDelay:
    def test_exponential(self):
        rq = RetryQueue(backoff=BackoffStrategy.EXPONENTIAL, base_delay=2.0, max_delay=100.0, jitter=False)
        d = rq._compute_delay(1)
        assert d == 2.0  # 2 * 2^0 = 2

    def test_exponential_second(self):
        rq = RetryQueue(backoff=BackoffStrategy.EXPONENTIAL, base_delay=2.0, max_delay=100.0, jitter=False)
        d = rq._compute_delay(2)
        assert d == 4.0  # 2 * 2^1 = 4

    def test_constant(self):
        rq = RetryQueue(backoff=BackoffStrategy.CONSTANT, base_delay=3.0, jitter=False)
        for attempt in [1, 2, 5]:
            assert rq._compute_delay(attempt) == 3.0

    def test_linear(self):
        rq = RetryQueue(backoff=BackoffStrategy.LINEAR, base_delay=2.0, max_delay=100.0, jitter=False)
        assert rq._compute_delay(1) == 2.0
        assert rq._compute_delay(3) == 6.0

    def test_max_delay_capped(self):
        rq = RetryQueue(backoff=BackoffStrategy.EXPONENTIAL, base_delay=10.0, max_delay=25.0, jitter=False)
        d = rq._compute_delay(3)  # 10 * 2^2 = 40 → capped at 25
        assert d == 25.0

    def test_jitter_range(self):
        rq = RetryQueue(backoff=BackoffStrategy.CONSTANT, base_delay=2.0, jitter=True)
        delays = [rq._compute_delay(1) for _ in range(50)]
        # All should be between 1.0 (50%) and 2.0 (100%) of base_delay
        assert all(1.0 <= d <= 2.0 for d in delays)
        # Should not all be identical
        assert len(set(round(d, 4) for d in delays)) > 1
