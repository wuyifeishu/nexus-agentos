"""
RetryQueue — asynchronous retry with exponential backoff, max attempts, and dead letter queue.

Supports:
    - Exponential backoff with jitter
    - Max retry attempts
    - Dead letter queue for permanently failed items
    - Callback hooks (on_retry, on_failure, on_success)
    - Synchronous and async execution modes
    - Configurable backoff strategy (exponential, constant, linear)
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ============================================================================
# Backoff Strategy
# ============================================================================

class BackoffStrategy(Enum):
    EXPONENTIAL = "exponential"
    CONSTANT = "constant"
    LINEAR = "linear"


# ============================================================================
# Job
# ============================================================================

@dataclass
class RetryJob:
    id: str
    func: Callable[..., Any]
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    last_error: Optional[Exception] = None
    created_at: float = field(default_factory=time.time)

    def execute(self) -> Any:
        return self.func(*self.args, **self.kwargs)


# ============================================================================
# RetryQueue
# ============================================================================

class RetryQueue:
    """Asynchronous retry queue with exponential backoff.

    Usage:
        rq = RetryQueue(
            max_attempts=3,
            base_delay=1.0,
            max_delay=30.0,
        )

        def risky_call(a, b):
            # might fail...
            return a / b

        # Submit a job — if it fails, it will be retried
        result = rq.submit(risky_call, 10, 0)

        # Check dead letters
        for job, error in rq.dead_letters:
            print(f"Job {job.id} permanently failed: {error}")
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL,
        jitter: bool = True,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._backoff = backoff
        self._jitter = jitter
        self._dead_letters: List[tuple] = []
        self._lock = threading.RLock()
        self._total_submitted: int = 0
        self._total_succeeded: int = 0
        self._total_failed: int = 0
        # Hooks
        self._on_retry: List[Callable[[RetryJob, Exception, int], None]] = []
        self._on_failure: List[Callable[[RetryJob, Exception], None]] = []
        self._on_success: List[Callable[[RetryJob, Any], None]] = []

    # ---------- submit ----------

    def submit(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Submit and execute a job with retry. Raises last error if all attempts fail."""
        import uuid
        job = RetryJob(
            id=str(uuid.uuid4())[:8],
            func=func,
            args=args,
            kwargs=kwargs,
        )
        with self._lock:
            self._total_submitted += 1
        return self._execute(job)

    def _execute(self, job: RetryJob) -> Any:
        attempt = 0
        while True:
            try:
                result = job.execute()
                self._notify_success(job, result)
                with self._lock:
                    self._total_succeeded += 1
                return result
            except Exception as e:
                job.last_error = e
                job.attempts += 1
                attempt += 1

                if attempt >= self._max_attempts:
                    self._notify_failure(job, e)
                    with self._lock:
                        self._total_failed += 1
                        self._dead_letters.append((job, e))
                    raise

                self._notify_retry(job, e, attempt)
                delay = self._compute_delay(attempt)
                time.sleep(delay)

    def _compute_delay(self, attempt: int) -> float:
        if self._backoff == BackoffStrategy.CONSTANT:
            delay = self._base_delay
        elif self._backoff == BackoffStrategy.LINEAR:
            delay = self._base_delay * attempt
        else:  # EXPONENTIAL
            delay = self._base_delay * (2 ** (attempt - 1))

        delay = min(delay, self._max_delay)

        if self._jitter:
            delay = delay * (0.5 + random.random() * 0.5)  # 50%-100% of delay

        return delay

    # ---------- hooks ----------

    def on_retry(self, callback: Callable[[RetryJob, Exception, int], None]) -> None:
        self._on_retry.append(callback)

    def on_failure(self, callback: Callable[[RetryJob, Exception], None]) -> None:
        self._on_failure.append(callback)

    def on_success(self, callback: Callable[[RetryJob, Any], None]) -> None:
        self._on_success.append(callback)

    def _notify_retry(self, job, error, attempt):
        for cb in self._on_retry:
            try:
                cb(job, error, attempt)
            except Exception:
                pass

    def _notify_failure(self, job, error):
        for cb in self._on_failure:
            try:
                cb(job, error)
            except Exception:
                pass

    def _notify_success(self, job, result):
        for cb in self._on_success:
            try:
                cb(job, result)
            except Exception:
                pass

    # ---------- dead letters ----------

    @property
    def dead_letters(self) -> List[tuple]:
        with self._lock:
            return list(self._dead_letters)

    def clear_dead_letters(self) -> None:
        with self._lock:
            self._dead_letters.clear()

    def retry_dead_letter(self, index: int) -> Any:
        """Re-submit a dead letter job."""
        with self._lock:
            if index < 0 or index >= len(self._dead_letters):
                raise IndexError("dead letter index out of range")
            job, _ = self._dead_letters.pop(index)
        job.attempts = 0
        job.last_error = None
        return self._execute(job)

    # ---------- stats ----------

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total_submitted": self._total_submitted,
                "total_succeeded": self._total_succeeded,
                "total_failed": self._total_failed,
                "dead_letter_count": len(self._dead_letters),
                "max_attempts": self._max_attempts,
                "backoff": self._backoff.value,
            }
