"""Tests for agentos.tools.scheduler."""

import time

import pytest

from agentos.tools.scheduler import Scheduler, _cron_next, _parse_cron_field


class TestCronParser:
    def test_parse_star(self):
        assert _parse_cron_field("*", 0, 5) == {0, 1, 2, 3, 4, 5}

    def test_parse_list(self):
        assert _parse_cron_field("1,3,5", 0, 5) == {1, 3, 5}

    def test_parse_range(self):
        assert _parse_cron_field("1-3", 0, 5) == {1, 2, 3}

    def test_parse_step(self):
        assert _parse_cron_field("*/15", 0, 59) == {0, 15, 30, 45}

    def test_cron_next_every_minute(self):
        cron = {"minute": "*", "hour": "*", "day": "*", "month": "*", "day_of_week": "*"}
        now = time.time()
        nxt = _cron_next(cron, now)
        assert nxt > now
        assert nxt - now < 61


class TestScheduler:
    def test_every_interval(self):
        s = Scheduler()
        results = []

        s.every(0.05).do(results.append, "ping")
        s.start()
        time.sleep(0.25)
        s.stop()
        assert len(results) >= 3

    def test_delay_one_shot(self):
        s = Scheduler()
        results = []

        s.delay(0.05).do(results.append, "once")
        s.start()
        time.sleep(0.2)
        s.stop()
        assert results == ["once"]

    def test_pause_resume(self):
        s = Scheduler()
        results = []

        job = s.every(0.05).do(results.append, "x")
        s.start()
        time.sleep(0.12)
        s.pause(job.id)
        count_after_pause = len(results)
        time.sleep(0.15)
        assert len(results) == count_after_pause

        s.resume(job.id)
        time.sleep(0.15)
        s.stop()
        assert len(results) > count_after_pause

    def test_remove_job(self):
        s = Scheduler()
        results = []

        job = s.every(0.05).do(results.append, "y")
        s.start()
        time.sleep(0.1)
        s.remove(job.id)
        count_after_remove = len(results)
        time.sleep(0.15)
        assert len(results) == count_after_remove
        s.stop()

    def test_job_info(self):
        s = Scheduler()
        job = s.every(60).do(lambda: None)
        info = s.get_job(job.id)
        assert info["id"] == job.id
        assert info["interval"] == 60

    def test_list_jobs(self):
        s = Scheduler()
        s.every(1).do(lambda: None)
        s.every(2).do(lambda: None)
        assert len(s.list_jobs()) == 2

    def test_error_count(self):
        s = Scheduler()

        def fail():
            raise ValueError("oops")

        job = s.every(0.05).do(fail)
        s.start()
        time.sleep(0.12)
        s.stop()
        assert job.error_count >= 1
        assert "oops" in (job.last_error or "")

    def test_invalid_cron_expression(self):
        s = Scheduler()
        with pytest.raises(ValueError):
            s.cron("* * * *").do(lambda: None)
