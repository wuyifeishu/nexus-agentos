"""Tests for agentos.tools.retry_queue."""

import pytest

from agentos.tools.retry_queue import BackoffStrategy, RetryJob, RetryQueue


class TestRetryQueue:
    def test_success_first_try(self):
        rq = RetryQueue(max_attempts=3)
        result = rq.submit(lambda a, b: a + b, 2, 3)
        assert result == 5
        assert rq.stats["total_succeeded"] == 1
        assert rq.stats["total_failed"] == 0

    def test_retry_then_success(self):
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise ValueError("fail")
            return "ok"

        rq = RetryQueue(max_attempts=5, base_delay=0.01)
        result = rq.submit(flaky)
        assert result == "ok"
        assert len(attempts) == 3

    def test_all_attempts_exhausted(self):
        def always_fails():
            raise RuntimeError("boom")

        rq = RetryQueue(max_attempts=2, base_delay=0.01)
        with pytest.raises(RuntimeError, match="boom"):
            rq.submit(always_fails)

        assert rq.stats["total_failed"] == 1
        assert len(rq.dead_letters) == 1

    def test_dead_letter_contains_job_and_error(self):
        def fails():
            raise ValueError("bad")

        rq = RetryQueue(max_attempts=2, base_delay=0.01)
        try:
            rq.submit(fails)
        except ValueError:
            pass
        assert len(rq.dead_letters) == 1
        job, error = rq.dead_letters[0]
        assert isinstance(job, RetryJob)
        assert isinstance(error, ValueError)

    def test_retry_dead_letter(self):
        counter = {"calls": 0}

        def flaky():
            counter["calls"] += 1
            if counter["calls"] < 4:
                raise ValueError("nope")
            return "finally"

        rq = RetryQueue(max_attempts=2, base_delay=0.01)
        try:
            rq.submit(flaky)
        except ValueError:
            pass
        assert len(rq.dead_letters) == 1

        result = rq.retry_dead_letter(0)
        assert result == "finally"
        assert rq.stats["total_succeeded"] == 1

    def test_clear_dead_letters(self):
        def fails():
            raise RuntimeError()

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        try:
            rq.submit(fails)
        except RuntimeError:
            pass
        assert len(rq.dead_letters) == 1
        rq.clear_dead_letters()
        assert len(rq.dead_letters) == 0

    def test_on_retry_hook(self):
        events = []

        def hook(job, error, attempt):
            events.append((job.id, str(error), attempt))

        rq = RetryQueue(max_attempts=3, base_delay=0.01)
        rq.on_retry(hook)

        counter = [0]

        def flaky():
            counter[0] += 1
            if counter[0] < 3:
                raise ValueError("err")
            return "ok"

        rq.submit(flaky)
        assert len(events) == 2
        assert events[0][1] == "err"
        assert events[1][2] == 2

    def test_on_failure_hook(self):
        events = []

        def hook(job, error):
            events.append(str(error))

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        rq.on_failure(hook)
        try:
            rq.submit(lambda: (_ for _ in ()).throw(ValueError("dead")))
        except ValueError:
            pass
        assert len(events) == 1
        assert "dead" in events[0]

    def test_on_success_hook(self):
        events = []

        def hook(job, result):
            events.append(result)

        rq = RetryQueue(max_attempts=3, base_delay=0.01)
        rq.on_success(hook)
        rq.submit(lambda: 42)
        assert events == [42]

    def test_args_kwargs_preserved(self):
        captured = {}

        def capture(a, b=0, **kw):
            captured["a"] = a
            captured["b"] = b
            captured["kw"] = kw
            return a + b

        rq = RetryQueue(max_attempts=1)
        rq.submit(capture, 3, b=4, extra="yes")
        assert captured["a"] == 3
        assert captured["b"] == 4
        assert captured["kw"] == {"extra": "yes"}

    def test_constant_backoff(self):
        rq = RetryQueue(max_attempts=3, base_delay=0.02, backoff=BackoffStrategy.CONSTANT, jitter=False)
        assert rq._compute_delay(1) == 0.02
        assert rq._compute_delay(2) == 0.02

    def test_linear_backoff(self):
        rq = RetryQueue(max_attempts=3, base_delay=0.02, backoff=BackoffStrategy.LINEAR, jitter=False)
        assert rq._compute_delay(1) == 0.02
        assert rq._compute_delay(3) == 0.06

    def test_exponential_backoff(self):
        rq = RetryQueue(max_attempts=3, base_delay=1.0, backoff=BackoffStrategy.EXPONENTIAL, jitter=False)
        assert rq._compute_delay(1) == 1.0
        assert rq._compute_delay(2) == 2.0
        assert rq._compute_delay(3) == 4.0

    def test_max_delay_capped(self):
        rq = RetryQueue(max_attempts=3, base_delay=10.0, max_delay=15.0, jitter=False)
        assert rq._compute_delay(5) == 15.0

    def test_invalid_max_attempts(self):
        with pytest.raises(ValueError):
            RetryQueue(max_attempts=0)
