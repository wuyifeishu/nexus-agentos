"""Tests for agentos.tools.retry_queue — RetryQueue, RetryJob, BackoffStrategy."""


import pytest

from agentos.tools.retry_queue import BackoffStrategy, RetryJob, RetryQueue

# ============================================================================
# BackoffStrategy
# ============================================================================

class TestBackoffStrategy:
    def test_enum_values(self):
        assert BackoffStrategy.EXPONENTIAL.value == "exponential"
        assert BackoffStrategy.CONSTANT.value == "constant"
        assert BackoffStrategy.LINEAR.value == "linear"

    def test_enum_membership(self):
        assert BackoffStrategy("exponential") == BackoffStrategy.EXPONENTIAL
        assert BackoffStrategy("constant") == BackoffStrategy.CONSTANT
        assert BackoffStrategy("linear") == BackoffStrategy.LINEAR


# ============================================================================
# RetryJob
# ============================================================================

class TestRetryJob:
    def test_creation_defaults(self):
        job = RetryJob(id="j1", func=lambda: 42)
        assert job.id == "j1"
        assert job.args == ()
        assert job.kwargs == {}
        assert job.attempts == 0
        assert job.last_error is None
        assert isinstance(job.created_at, float)

    def test_creation_with_args(self):
        def f(a, b, c=3):
            return a + b + c

        job = RetryJob(id="j2", func=f, args=(1, 2), kwargs={"c": 4})
        assert job.args == (1, 2)
        assert job.kwargs == {"c": 4}

    def test_execute(self):
        job = RetryJob(id="j3", func=lambda x: x * 2, args=(21,))
        assert job.execute() == 42

    def test_execute_raises(self):
        def fail():
            raise ValueError("boom")

        job = RetryJob(id="j4", func=fail)
        with pytest.raises(ValueError, match="boom"):
            job.execute()

    def test_attempts_not_auto_incremented(self):
        job = RetryJob(id="j5", func=lambda: 1)
        job.execute()
        assert job.attempts == 0  # execute doesn't increment attempts


# ============================================================================
# RetryQueue — Construction
# ============================================================================

class TestRetryQueueInit:
    def test_defaults(self):
        rq = RetryQueue()
        assert rq._max_attempts == 3
        assert rq._base_delay == 1.0
        assert rq._max_delay == 60.0
        assert rq._backoff == BackoffStrategy.EXPONENTIAL
        assert rq._jitter is True

    def test_custom_values(self):
        rq = RetryQueue(max_attempts=5, base_delay=0.5, max_delay=10.0,
                        backoff=BackoffStrategy.CONSTANT, jitter=False)
        assert rq._max_attempts == 5
        assert rq._base_delay == 0.5
        assert rq._max_delay == 10.0
        assert rq._backoff == BackoffStrategy.CONSTANT
        assert rq._jitter is False

    def test_max_attempts_validation(self):
        with pytest.raises(ValueError, match="max_attempts must be at least 1"):
            RetryQueue(max_attempts=0)
        with pytest.raises(ValueError, match="max_attempts must be at least 1"):
            RetryQueue(max_attempts=-1)

    def test_max_attempts_one_is_valid(self):
        rq = RetryQueue(max_attempts=1)
        assert rq._max_attempts == 1


# ============================================================================
# RetryQueue — Successful execution
# ============================================================================

class TestRetryQueueSuccess:
    def test_submit_simple(self):
        rq = RetryQueue()
        result = rq.submit(lambda x, y: x + y, 3, 4)
        assert result == 7

    def test_submit_no_args(self):
        rq = RetryQueue()
        result = rq.submit(lambda: 99)
        assert result == 99

    def test_submit_keyword_args(self):
        rq = RetryQueue()
        result = rq.submit(lambda a, b: a * b, a=6, b=7)
        assert result == 42

    def test_submit_mixed_args(self):
        rq = RetryQueue()
        result = rq.submit(lambda a, b, c=1: a + b + c, 2, 3, c=4)
        assert result == 9

    def test_stats_after_success(self):
        rq = RetryQueue()
        rq.submit(lambda: 1)
        rq.submit(lambda: 2)
        s = rq.stats
        assert s["total_submitted"] == 2
        assert s["total_succeeded"] == 2
        assert s["total_failed"] == 0
        assert s["dead_letter_count"] == 0

    def test_success_hook(self):
        rq = RetryQueue()
        hooks = []
        rq.on_success(lambda job, result: hooks.append(("success", job.id, result)))
        rq.submit(lambda: 42)
        assert len(hooks) == 1
        assert hooks[0][0] == "success"
        assert hooks[0][2] == 42


# ============================================================================
# RetryQueue — Retry & failure
# ============================================================================

class TestRetryQueueRetry:
    def test_retry_then_succeed(self):
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("fail")
            return "ok"

        rq = RetryQueue(max_attempts=3, base_delay=0.01, jitter=False)
        result = rq.submit(flaky)
        assert result == "ok"
        assert len(attempts) == 3

    def test_exhausted_attempts_raises(self):
        def always_fail():
            raise RuntimeError("always")

        rq = RetryQueue(max_attempts=2, base_delay=0.01, jitter=False)
        with pytest.raises(RuntimeError, match="always"):
            rq.submit(always_fail)

        s = rq.stats
        assert s["total_submitted"] == 1
        assert s["total_succeeded"] == 0
        assert s["total_failed"] == 1
        assert s["dead_letter_count"] == 1

    def test_dead_letters_populated(self):
        def fail():
            raise RuntimeError("dead")

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        try:
            rq.submit(fail)
        except RuntimeError:
            pass

        assert len(rq.dead_letters) == 1
        job, error = rq.dead_letters[0]
        assert isinstance(error, RuntimeError)
        assert str(error) == "dead"
        assert job.attempts == 1

    def test_retry_hook(self):
        hooks = []

        def fail_once():
            if fail_once.calls == 0:
                fail_once.calls += 1
                raise RuntimeError("first")
            return "ok"

        fail_once.calls = 0

        rq = RetryQueue(max_attempts=3, base_delay=0.01, jitter=False)
        rq.on_retry(lambda job, err, attempt: hooks.append((job.id, attempt, str(err))))
        rq.submit(fail_once)

        assert len(hooks) == 1
        assert hooks[0][1] == 1
        assert "first" in hooks[0][2]

    def test_multiple_retry_hooks(self):
        hooks = []

        def fail():
            raise RuntimeError("x")

        rq = RetryQueue(max_attempts=2, base_delay=0.01, jitter=False)
        rq.on_retry(lambda j, e, a: hooks.append(1))
        rq.on_retry(lambda j, e, a: hooks.append(2))
        try:
            rq.submit(fail)
        except RuntimeError:
            pass

        assert len(hooks) == 2  # 1 hook fire x 1 retry

    def test_failure_hook(self):
        hooks = []

        def fail():
            raise RuntimeError("gone")

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        rq.on_failure(lambda job, err: hooks.append(("fail", str(err))))
        try:
            rq.submit(fail)
        except RuntimeError:
            pass

        assert len(hooks) == 1
        assert hooks[0][0] == "fail"
        assert "gone" in hooks[0][1]

    def test_hook_exceptions_do_not_propagate(self):
        def bad_hook(job, err):
            raise RuntimeError("hook broken")

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        rq.on_failure(bad_hook)
        # Should not raise from hook
        with pytest.raises(RuntimeError, match="x"):
            rq.submit(lambda: (_ for _ in ()).throw(RuntimeError("x")))

    def test_retry_hook_exception_does_not_propagate(self):
        def bad_retry_hook(job, err, attempt):
            raise RuntimeError("hook broken")

        def fail_once():
            if fail_once.calls == 0:
                fail_once.calls += 1
                raise RuntimeError("first")
            return "ok"

        fail_once.calls = 0

        rq = RetryQueue(max_attempts=3, base_delay=0.01, jitter=False)
        rq.on_retry(bad_retry_hook)
        result = rq.submit(fail_once)
        assert result == "ok"

    def test_success_hook_exception_does_not_propagate(self):
        def bad_success_hook(job, result):
            raise RuntimeError("hook broken")

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        rq.on_success(bad_success_hook)
        result = rq.submit(lambda: 42)
        assert result == 42


# ============================================================================
# RetryQueue — Backoff computation
# ============================================================================

class TestRetryQueueBackoff:
    def test_exponential_backoff(self):
        rq = RetryQueue(base_delay=1.0, max_delay=30.0, backoff=BackoffStrategy.EXPONENTIAL, jitter=False)
        # attempt 1: 1.0 * 2^0 = 1.0
        assert rq._compute_delay(1) == 1.0
        # attempt 2: 1.0 * 2^1 = 2.0
        assert rq._compute_delay(2) == 2.0
        # attempt 3: 1.0 * 2^2 = 4.0
        assert rq._compute_delay(3) == 4.0

    def test_constant_backoff(self):
        rq = RetryQueue(base_delay=2.0, backoff=BackoffStrategy.CONSTANT, jitter=False)
        for i in range(1, 6):
            assert rq._compute_delay(i) == 2.0

    def test_linear_backoff(self):
        rq = RetryQueue(base_delay=1.5, backoff=BackoffStrategy.LINEAR, jitter=False)
        assert rq._compute_delay(1) == 1.5
        assert rq._compute_delay(2) == 3.0
        assert rq._compute_delay(3) == 4.5

    def test_max_delay_clamp(self):
        rq = RetryQueue(base_delay=10.0, max_delay=15.0, backoff=BackoffStrategy.EXPONENTIAL, jitter=False)
        # attempt 1: 10 * 2^0 = 10, under 15
        assert rq._compute_delay(1) == 10.0
        # attempt 2: 10 * 2^1 = 20, clamped to 15
        assert rq._compute_delay(2) == 15.0

    def test_jitter_range(self):
        rq = RetryQueue(base_delay=10.0, jitter=True)
        for _ in range(20):
            d = rq._compute_delay(1)
            # 10 * 0.5 = 5, 10 * 1.0 = 10
            assert 5.0 <= d <= 10.0


# ============================================================================
# RetryQueue — Dead letters
# ============================================================================

class TestRetryQueueDeadLetters:
    def test_clear_dead_letters(self):
        def fail():
            raise RuntimeError("x")

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        try:
            rq.submit(fail)
        except RuntimeError:
            pass

        assert len(rq.dead_letters) == 1
        rq.clear_dead_letters()
        assert len(rq.dead_letters) == 0

    def test_retry_dead_letter_success(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("first")
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
        assert rq.stats["total_succeeded"] == 1

    def test_retry_dead_letter_index_error(self):
        rq = RetryQueue()
        with pytest.raises(IndexError, match="out of range"):
            rq.retry_dead_letter(0)

    def test_retry_dead_letter_still_fails(self):
        def fail():
            raise RuntimeError("again")

        rq = RetryQueue(max_attempts=1, base_delay=0.01)
        try:
            rq.submit(fail)
        except RuntimeError:
            pass

        assert len(rq.dead_letters) == 1
        with pytest.raises(RuntimeError, match="again"):
            rq.retry_dead_letter(0)
        # Dead letter re-added since retry also failed (max_attempts=1)
        assert len(rq.dead_letters) == 1


# ============================================================================
# RetryQueue — Stats
# ============================================================================

class TestRetryQueueStats:
    def test_default_stats(self):
        rq = RetryQueue(max_attempts=5, backoff=BackoffStrategy.LINEAR)
        s = rq.stats
        assert s["total_submitted"] == 0
        assert s["total_succeeded"] == 0
        assert s["total_failed"] == 0
        assert s["dead_letter_count"] == 0
        assert s["max_attempts"] == 5
        assert s["backoff"] == "linear"

    def test_stats_reflect_state(self):
        rq = RetryQueue(max_attempts=2, base_delay=0.01, jitter=False)
        # succeed once
        rq.submit(lambda: 1)

        # fail once
        try:
            rq.submit(lambda: (_ for _ in ()).throw(ValueError("x")))
        except ValueError:
            pass

        s = rq.stats
        assert s["total_submitted"] == 2
        assert s["total_succeeded"] == 1
        assert s["total_failed"] == 1
        assert s["dead_letter_count"] == 1

    def test_stats_thread_safety(self):
        import threading

        rq = RetryQueue(max_attempts=5, base_delay=0.01, jitter=False)
        errors = []

        def worker():
            try:
                rq.submit(lambda x: x + 1, 1)
                rq.stats  # concurrent read
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert rq.stats["total_submitted"] == 5
        assert rq.stats["total_succeeded"] == 5
