"""Tests for agentos.tools.scheduler — Scheduler, Job, cron parser."""

import time

import pytest

from agentos.tools.scheduler import (
    Job,
    JobState,
    Scheduler,
    _cron_next,
    _parse_cron_field,
)

# ============================================================================
# Cron Field Parser
# ============================================================================

class TestParseCronField:
    def test_star(self):
        result = _parse_cron_field("*", 0, 59)
        assert result == set(range(0, 60))

    def test_single_value(self):
        result = _parse_cron_field("15", 0, 59)
        assert result == {15}

    def test_comma_list(self):
        result = _parse_cron_field("0,15,30,45", 0, 59)
        assert result == {0, 15, 30, 45}

    def test_step(self):
        result = _parse_cron_field("*/15", 0, 59)
        assert result == {0, 15, 30, 45}

    def test_range(self):
        result = _parse_cron_field("5-10", 0, 59)
        assert result == {5, 6, 7, 8, 9, 10}

    def test_step_from_nonzero(self):
        result = _parse_cron_field("5/10", 0, 59)
        assert result == {5, 15, 25, 35, 45, 55}


# ============================================================================
# Cron Next Computation
# ============================================================================

class TestCronNext:
    def test_every_minute(self):
        now = time.mktime((2025, 1, 1, 12, 0, 0, 0, 0, 0))
        cron = {"minute": "*", "hour": "*", "day": "*", "month": "*", "day_of_week": "*"}
        nxt = _cron_next(cron, now)
        assert nxt > now

    def test_specific_time(self):
        # Every day at 14:30
        now = time.mktime((2025, 1, 1, 12, 0, 0, 0, 0, 0))
        cron = {"minute": "30", "hour": "14", "day": "*", "month": "*", "day_of_week": "*"}
        nxt = _cron_next(cron, now)
        t = time.localtime(nxt)
        assert t.tm_hour == 14
        assert t.tm_min == 30

    def test_specific_minute_every_hour(self):
        now = time.mktime((2025, 1, 1, 12, 5, 0, 0, 0, 0))
        cron = {"minute": "0", "hour": "*", "day": "*", "month": "*", "day_of_week": "*"}
        nxt = _cron_next(cron, now)
        t = time.localtime(nxt)
        assert t.tm_min == 0
        assert t.tm_hour == 13  # next hour

    def test_month_restriction(self):
        now = time.mktime((2025, 1, 1, 12, 0, 0, 0, 0, 0))
        cron = {"minute": "0", "hour": "12", "day": "1", "month": "6", "day_of_week": "*"}
        nxt = _cron_next(cron, now)
        t = time.localtime(nxt)
        assert t.tm_mon == 6


# ============================================================================
# Job / JobState
# ============================================================================

class TestJob:
    def test_default_state(self):
        j = Job(id="j1", func=lambda: 1)
        assert j.state == JobState.PENDING
        assert j.run_count == 0
        assert j.error_count == 0
        assert j.last_error is None


# ============================================================================
# Scheduler: Fluent API
# ============================================================================

class TestFluentAPI:
    def test_every_do(self):
        s = Scheduler()
        job = s.every(10).do(lambda: "hi")
        assert job.id.startswith("job_")
        assert job.interval == 10

    def test_delay_do(self):
        s = Scheduler()
        job = s.delay(5).do(lambda: "hi")
        assert job.delay == 5
        assert job.interval is None

    def test_cron_do(self):
        s = Scheduler()
        job = s.cron("*/5 * * * *").do(lambda: "hi")
        assert job.cron is not None
        assert job.cron["minute"] == "*/5"

    def test_do_without_schedule_raises(self):
        s = Scheduler()
        with pytest.raises(ValueError, match="Must call"):
            s.do(lambda: 1)

    def test_cron_invalid_fields_raises(self):
        s = Scheduler()
        with pytest.raises(ValueError):
            s.cron("* * *").do(lambda: 1)


# ============================================================================
# Scheduler: Lifecycle
# ============================================================================

class TestLifecycle:
    def test_start_stop(self):
        s = Scheduler()
        s.start()
        assert s._running is True
        s.stop()
        assert s._running is False

    def test_double_start_noop(self):
        s = Scheduler()
        s.start()
        s.start()  # should not error
        s.stop()

    def test_pause_resume(self):
        s = Scheduler()
        job = s.every(99).do(lambda: None)
        assert s.pause(job.id) is True
        assert job.state == JobState.PAUSED
        assert s.resume(job.id) is True
        assert job.state == JobState.PENDING

    def test_pause_nonexistent(self):
        s = Scheduler()
        assert s.pause("ghost") is False

    def test_resume_nonexistent(self):
        s = Scheduler()
        assert s.resume("ghost") is False

    def test_resume_non_paused(self):
        s = Scheduler()
        job = s.every(60).do(lambda: None)
        assert s.resume(job.id) is False

    def test_remove(self):
        s = Scheduler()
        job = s.every(60).do(lambda: None)
        assert s.remove(job.id) is True
        assert s.remove(job.id) is False
        assert s.get_job(job.id) is None

    def test_remove_cancels_timer(self):
        s = Scheduler()
        s.start()
        job = s.every(0.01).do(lambda: None)
        assert s.remove(job.id) is True
        s.stop()


# ============================================================================
# Scheduler: Execution
# ============================================================================

class TestExecution:
    def test_interval_job_runs(self):
        results = []
        s = Scheduler()
        s.every(0.05).do(results.append, "ping")
        s.start()
        time.sleep(0.15)
        s.stop()
        assert len(results) >= 2

    def test_delay_one_shot(self):
        results = []
        s = Scheduler()
        s.delay(0.03).do(results.append, "once")
        s.start()
        time.sleep(0.08)
        s.stop()
        assert results == ["once"]

    def test_job_stops_after_delay(self):
        s = Scheduler()
        job = s.delay(0.02).do(lambda: None)
        s.start()
        time.sleep(0.06)
        s.stop()
        assert job.state == JobState.STOPPED

    def test_job_run_count(self):
        s = Scheduler()
        job = s.every(0.03).do(lambda: None)
        s.start()
        time.sleep(0.10)
        s.stop()
        assert job.run_count >= 2

    def test_job_error_handling(self):
        s = Scheduler()
        job = s.every(0.03).do(lambda: (_ for _ in ()).throw(ValueError("oops")))
        s.start()
        time.sleep(0.08)
        s.stop()
        assert job.error_count >= 1
        assert "oops" in (job.last_error or "")

    def test_paused_job_not_executed(self):
        results = []
        s = Scheduler()
        job = s.every(0.03).do(results.append, "tick")
        s.start()
        time.sleep(0.03)
        s.pause(job.id)
        before = job.run_count
        time.sleep(0.08)
        after = job.run_count
        s.stop()
        assert after == before or after <= before + 1

    def test_start_before_do(self):
        """Jobs registered after start() should also be scheduled."""
        results = []
        s = Scheduler()
        s.start()
        s.every(0.03).do(results.append, "late")
        time.sleep(0.10)
        s.stop()
        assert len(results) >= 1


# ============================================================================
# Scheduler: Query
# ============================================================================

class TestQuery:
    def test_list_jobs(self):
        s = Scheduler()
        s.every(10).do(lambda: 1)
        s.every(20).do(lambda: 2)
        jobs = s.list_jobs()
        assert len(jobs) == 2

    def test_get_job(self):
        s = Scheduler()
        job = s.delay(5).do(lambda: "x")
        info = s.get_job(job.id)
        assert info["id"] == job.id
        assert info["delay"] == 5

    def test_get_job_missing(self):
        s = Scheduler()
        assert s.get_job("nope") is None

    def test_job_info_fields(self):
        s = Scheduler()
        job = s.every(30).do(lambda: None)
        info = s.get_job(job.id)
        assert set(info.keys()) == {
            "id", "state", "interval", "cron", "delay",
            "next_run", "last_run", "run_count", "error_count", "last_error",
        }
