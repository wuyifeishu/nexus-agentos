"""
Scheduler — lightweight interval + cron-style job scheduler.

Supports:
    - Fixed interval scheduling (every N seconds)
    - Delayed one-shot scheduling
    - Cron-style scheduling (minute, hour, day of month, month, day of week)
    - Job lifecycle (start, stop, pause, resume)
    - Execution history / stats
    - Thread-safe
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# ============================================================================
# Job
# ============================================================================


class JobState:
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass
class Job:
    id: str
    func: Callable[..., Any]
    args: tuple = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    # Scheduling
    interval: float | None = None  # Fixed interval in seconds
    cron: dict[str, str] | None = None  # {"minute": "*", "hour": "*", ...}
    delay: float | None = None  # One-shot delay
    # State
    state: str = JobState.PENDING
    next_run: float = 0.0
    last_run: float | None = None
    run_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    _timer: threading.Timer | None = field(default=None, repr=False)


# ============================================================================
# Cron Parser
# ============================================================================


def _cron_next(cron: dict[str, str], now: float) -> float:
    """Compute next run time from cron expression. Returns timestamp."""
    import calendar

    t = time.localtime(now)
    # Parse fields
    minutes = _parse_cron_field(cron.get("minute", "*"), 0, 59)
    hours = _parse_cron_field(cron.get("hour", "*"), 0, 23)
    doms = _parse_cron_field(cron.get("day", "*"), 1, 31)
    months = _parse_cron_field(cron.get("month", "*"), 1, 12)
    dows = _parse_cron_field(cron.get("day_of_week", "*"), 0, 6)

    # Search forward
    year = t.tm_year
    month = t.tm_mon
    day = t.tm_mday
    hour = t.tm_hour
    minute = t.tm_min

    for _ in range(366 * 5):  # max 5 years search
        # Check month
        if month not in months:
            month += 1
            if month > 12:
                month = 1
                year += 1
            day = 1
            hour = 0
            minute = 0
            continue

        # Check day (DOM and DOW)
        if day > calendar.monthrange(year, month)[1]:
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
            hour = 0
            minute = 0
            continue

        dow = calendar.weekday(year, month, day)
        # Convert Monday=0..Sunday=6 to Sunday=0..Saturday=6
        dow = (dow + 1) % 7

        if day not in doms and dow not in dows:
            day += 1
            hour = 0
            minute = 0
            continue

        # Check hour
        if hour not in hours:
            hour += 1
            if hour > 23:
                hour = 0
                day += 1
            minute = 0
            continue

        # Check minute
        if minute not in minutes:
            minute += 1
            if minute > 59:
                minute = 0
                hour += 1
            continue

        # Found
        result = time.mktime((year, month, day, hour, minute, 0, 0, 0, 0))
        if result > now:
            return result
        # Advance past current instant
        minute += 1

    raise RuntimeError("No cron match within 5 years")


def _parse_cron_field(field: str, lo: int, hi: int) -> set[int]:
    """Parse cron field like '*' or '1,3,5' or '*/15'."""
    if field == "*":
        return set(range(lo, hi + 1))
    result = set()
    for part in field.split(","):
        part = part.strip()
        if "/" in part:
            base, step = part.split("/")
            base = lo if base == "*" else int(base)
            step = int(step)
            for v in range(base, hi + 1, step):
                result.add(v)
        elif "-" in part:
            a, b = part.split("-")
            result.update(range(int(a), int(b) + 1))
        else:
            result.add(int(part))
    return result


# ============================================================================
# Scheduler
# ============================================================================


class Scheduler:
    """Lightweight job scheduler.

    Usage:
        sched = Scheduler()

        # Every 5 seconds
        sched.every(5).do(my_func, arg1, arg2)

        # Every minute
        sched.cron("*/1 * * * *").do(my_func)

        # One-shot delay
        sched.delay(10).do(my_func)

        sched.start()
    """

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._running = False
        self._id_counter = 0

    # ---------- Fluent API ----------

    def every(self, seconds: float) -> Scheduler:
        self._last_interval = seconds
        self._last_cron = None
        self._last_delay = None
        return self

    def cron(self, expression: str) -> Scheduler:
        """Cron expression: 'minute hour day month day_of_week'"""
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(
                "Cron expression must have 5 fields: 'minute hour day month day_of_week'"
            )
        self._last_cron = {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }
        self._last_interval = None
        self._last_delay = None
        return self

    def delay(self, seconds: float) -> Scheduler:
        self._last_delay = seconds
        self._last_interval = None
        self._last_cron = None
        return self

    def do(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Job:
        """Register the job and return it."""
        self._id_counter += 1
        job_id = f"job_{self._id_counter}"

        interval = getattr(self, "_last_interval", None)
        cron = getattr(self, "_last_cron", None)
        delay = getattr(self, "_last_delay", None)

        now = time.time()
        if interval:
            next_run = now + interval
        elif cron:
            next_run = _cron_next(cron, now)
        elif delay:
            next_run = now + delay
        else:
            raise ValueError("Must call every(), cron(), or delay() before do()")

        job = Job(
            id=job_id,
            func=func,
            args=args,
            kwargs=kwargs,
            interval=interval,
            cron=cron,
            delay=delay,
            next_run=next_run,
        )

        with self._lock:
            self._jobs[job_id] = job

        # Schedule if running
        if self._running:
            self._schedule_job(job)

        return job

    # ---------- Lifecycle ----------

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            for job in self._jobs.values():
                if job.state in (JobState.PENDING,):
                    self._schedule_job(job)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            for job in self._jobs.values():
                if job._timer:
                    job._timer.cancel()
                    job._timer = None
                if job.state == JobState.RUNNING:
                    job.state = JobState.PAUSED

    def pause(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job._timer:
                job._timer.cancel()
                job._timer = None
            job.state = JobState.PAUSED
            return True

    def resume(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.state != JobState.PAUSED:
                return False
            job.state = JobState.PENDING
            job.next_run = time.time()  # run immediately
            if self._running:
                self._schedule_job(job)
            return True

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job and job._timer:
                job._timer.cancel()
            return job is not None

    # ---------- Internal ----------

    def _schedule_job(self, job: Job) -> None:
        if job.state == JobState.PAUSED:
            return
        job.state = JobState.PENDING
        delay = max(0, job.next_run - time.time())
        timer = threading.Timer(delay, self._run_job, args=[job.id])
        timer.daemon = True
        job._timer = timer
        timer.start()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or not self._running:
                return
            job.state = JobState.RUNNING

        try:
            job.func(*job.args, **job.kwargs)
            job.last_error = None
        except Exception as e:
            job.error_count += 1
            job.last_error = str(e)
        finally:
            with self._lock:
                job.last_run = time.time()
                job.run_count += 1

                if job.delay:
                    # One-shot — mark done
                    job.state = JobState.STOPPED
                    return

                if job.state != JobState.PAUSED:
                    # Compute next run
                    if job.interval:
                        job.next_run = time.time() + job.interval
                    elif job.cron:
                        job.next_run = _cron_next(job.cron, time.time())
                    else:
                        job.state = JobState.STOPPED
                        return

                    if self._running:
                        self._schedule_job(job)

    # ---------- Query ----------

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return self._job_info(job)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._job_info(j) for j in self._jobs.values()]

    @staticmethod
    def _job_info(job: Job) -> dict[str, Any]:
        return {
            "id": job.id,
            "state": job.state,
            "interval": job.interval,
            "cron": job.cron,
            "delay": job.delay,
            "next_run": job.next_run,
            "last_run": job.last_run,
            "run_count": job.run_count,
            "error_count": job.error_count,
            "last_error": job.last_error,
        }
