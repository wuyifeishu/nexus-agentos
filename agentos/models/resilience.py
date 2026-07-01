"""
AgentOS v1.1.5 Resilience — 韧性层。
Retry with jitter + Circuit Breaker + Timeout + Fallback chain + Cancellation-aware retry。
"""

from __future__ import annotations

import asyncio
import random
import time
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Awaitable, TypeVar, Any

T = TypeVar("T")


class CircuitState(str, Enum):

    """熔断器状态枚举。"""

    CLOSED = "closed"           # 正常
    OPEN = "open"               # 熔断
    HALF_OPEN = "half_open"     # 半开（探测）


@dataclass
class CircuitBreakerConfig:
    """熔断器配置。"""

    failure_threshold: int = 5          # 连续失败N次后熔断
    success_threshold: int = 2          # 半开状态下N次成功后恢复
    timeout: float = 60.0               # 熔断持续时间（秒）
    half_open_max_requests: int = 1     # 半开状态下最大探测请求
    track_duration: float = 300.0       # 统计窗口


@dataclass
class CircuitBreakerStats:
    """熔断器运行统计。"""

    state: CircuitState
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    opened_at: float = 0.0
    total_failures: int = 0
    total_successes: int = 0


class CircuitBreaker:
    """熔断器：检测连续失败，自动熔断/恢复。"""

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: float = 0.0
        self._opened_at: float = 0.0
        self._lock = asyncio.Lock()
        self._stats = CircuitBreakerStats(state=CircuitState.CLOSED)

    async def call(self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        """通过熔断器调用函数。"""
        async with self._lock:
            if not self._allow_request():
                raise CircuitBreakerOpenError(f"Circuit {self.name} is OPEN")

        try:
            result = await fn(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise e

    def _allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self.config.timeout:
                self.state = CircuitState.HALF_OPEN
                self._success_count = 0
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return self._success_count < self.config.half_open_max_requests

        return True

    async def _on_success(self):
        async with self._lock:
            self._stats.total_successes += 1
            self._stats.last_success_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    self._failure_count = 0
            else:
                self._failure_count = 0

            self._stats.state = self.state

    async def _on_failure(self):
        async with self._lock:
            self._failure_count += 1
            self._stats.failure_count = self._failure_count
            self._stats.total_failures += 1
            self._stats.last_failure_time = time.time()

            if self._failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
                self._opened_at = time.time()
                self._stats.opened_at = self._opened_at

            self._stats.state = self.state

    @property
    def stats(self) -> CircuitBreakerStats:
        s = CircuitBreakerStats(state=self.state)
        s.failure_count = self._failure_count
        s.last_failure_time = self._last_failure_time
        s.last_success_time = self._stats.last_success_time
        s.opened_at = self._opened_at
        s.total_failures = self._stats.total_failures
        s.total_successes = self._stats.total_successes
        return s

    def reset(self):
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0


class CircuitBreakerOpenError(Exception):
    """熔断器打开异常。"""
    pass


# ── Retry with Jitter ──────────────────────────────────────────────────────

@dataclass
class RetryConfig:
    """重试策略配置。"""
    max_retries: int = 3
    base_delay: float = 1.0          # 基础延迟（秒）
    max_delay: float = 60.0          # 最大延迟
    backoff_multiplier: float = 2.0  # 退避乘数
    jitter: bool = True              # 是否加抖动
    jitter_factor: float = 0.1       # 抖动比例
    retry_on: tuple[type[Exception], ...] = (Exception,)


class CancellationSource(str, Enum):
    """取消来源，区分用户主动取消与系统取消。"""

    USER = "user"     # 用户主动取消 — 不重试
    SYSTEM = "system"  # 系统级别取消（超时、熔断等）— 按配置重试


class CancelledError(Exception):
    """带取消来源的取消异常。"""

    def __init__(self, message: str, source: CancellationSource = CancellationSource.SYSTEM):
        super().__init__(message)
        self.source = source


class RetryExhaustedError(Exception):
    """重试耗尽异常。"""

    def __init__(self, attempts: int, last_error: Exception):
        super().__init__(f"Retry exhausted after {attempts} attempts. Last error: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


async def retry_with_backoff(
    fn: Callable[..., Awaitable[T]],
    *args,
    config: RetryConfig | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs,
) -> T:
    """带指数退避和抖动的重试函数，区分用户取消（不重试）与系统取消（按配置重试）。"""
    cfg = config or RetryConfig()
    last_error: Exception | None = None

    def _apply_delay(attempt_num: int, err: Exception):
        delay = min(cfg.base_delay * (cfg.backoff_multiplier ** attempt_num), cfg.max_delay)
        if cfg.jitter:
            delay = delay * (1 + random.uniform(-cfg.jitter_factor, cfg.jitter_factor))
            delay = max(0.1, delay)
        if on_retry:
            on_retry(attempt_num + 1, err, delay)
        return delay

    for attempt in range(cfg.max_retries + 1):
        try:
            if circuit_breaker:
                return await circuit_breaker.call(fn, *args, **kwargs)
            return await fn(*args, **kwargs)

        except CircuitBreakerOpenError:
            raise  # 熔断打开不重试

        except CancelledError as e:
            if e.source == CancellationSource.USER:
                raise  # 用户取消不重试，直接上抛
            # 系统级取消按重试配置处理
            last_error = e
            if attempt == cfg.max_retries:
                raise RetryExhaustedError(cfg.max_retries + 1, e)
            delay = _apply_delay(attempt, e)
            await asyncio.sleep(delay)

        except cfg.retry_on as e:
            last_error = e
            if attempt == cfg.max_retries:
                raise RetryExhaustedError(cfg.max_retries + 1, e)
            delay = _apply_delay(attempt, e)
            await asyncio.sleep(delay)

    raise RetryExhaustedError(cfg.max_retries, last_error or RuntimeError("unknown"))


# ── Timeout ─────────────────────────────────────────────────────────────────

class TimeoutError(Exception):
    """超时异常。"""
    pass


async def with_timeout(
    fn: Callable[..., Awaitable[T]],
    *args,
    timeout: float = 120.0,
    **kwargs,
) -> T:
    """为异步函数添加超时保护。"""
    try:
        return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"Operation timed out after {timeout}s")


# ── Fallback Chain ──────────────────────────────────────────────────────────

async def with_fallback(
    primary: Callable[..., Awaitable[T]],
    fallbacks: list[Callable[..., Awaitable[T]]],
    *args, **kwargs,
) -> T:
    """依次尝试主函数和降级函数链。"""
    errors: list[Exception] = []

    try:
        return await primary(*args, **kwargs)
    except Exception as e:
        errors.append(e)

    for i, fallback in enumerate(fallbacks):
        try:
            return await fallback(*args, **kwargs)
        except Exception as e:
            errors.append(e)

    raise FallbackExhaustedError(errors)


class FallbackExhaustedError(Exception):

    """回退耗尽异常。"""

    def __init__(self, errors: list[Exception]):
        msg = f"All {len(errors)} attempts failed: " + "; ".join(str(e) for e in errors[:3])
        super().__init__(msg)
        self.errors = errors


# ── Composite Resilience ────────────────────────────────────────────────────

@dataclass
class ResilienceConfig:
    """弹性总配置。"""
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig | None = None
    timeout: float = 120.0


class ResilientCall:
    """组合韧性调用器：重试 + 熔断 + 超时 + 降级。"""

    def __init__(self, config: ResilienceConfig | None = None):
        cfg = config or ResilienceConfig()
        self.retry_config = cfg.retry
        self.timeout = cfg.timeout
        self._breaker: CircuitBreaker | None = None
        if cfg.circuit_breaker:
            self._breaker = CircuitBreaker("default", cfg.circuit_breaker)

    async def call(self, fn: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        async def _inner():
            return await with_timeout(fn, *args, timeout=self.timeout, **kwargs)

        return await retry_with_backoff(
            _inner,
            config=self.retry_config,
            circuit_breaker=self._breaker,
        )
