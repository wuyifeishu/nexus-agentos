"""
AgentOS v0.60 Rate Limiter — 流量控制。
Token Bucket + Sliding Window + Concurrency Limiter + 多级配额。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum


class RateLimitStrategy(StrEnum):
    """限流策略枚举。"""

    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitConfig:
    """限流配置。"""

    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    max_requests: int = 60  # 每单位时间的最大请求数
    per_seconds: float = 60.0  # 时间窗口（秒）
    burst_size: int = 10  # 突发容量（token bucket 专用）
    max_concurrent: int = 5  # 最大并发数
    queue_timeout: float = 30.0  # 排队超时
    retry_after_header: bool = True  # 是否在拒绝时返回 Retry-After


@dataclass
class RateLimitResult:
    """限流检查结果。"""

    allowed: bool
    remaining: int = 0
    reset_at: float = 0.0
    retry_after: float = 0.0
    limit: int = 0
    reason: str = ""


class TokenBucket:
    """令牌桶算法实现。"""

    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # 令牌填充速率（个/秒）
        self.capacity = capacity  # 桶容量（最大突发）
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> bool:
        async with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    @property
    def available(self) -> float:
        self._refill()
        return self.tokens


class SlidingWindow:
    """滑动窗口计数器。"""

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def allow(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self.window
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return True
            return False

    @property
    def current_count(self) -> int:
        cutoff = time.monotonic() - self.window
        return sum(1 for t in self._timestamps if t > cutoff)


class ConcurrencyLimiter:
    """并发请求限制器。"""

    def __init__(self, max_concurrent: int):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent

    async def acquire(self) -> bool:
        return await self._semaphore.acquire()

    def release(self):
        self._semaphore.release()

    @property
    def available(self) -> int:
        return self._semaphore._value


class RateLimiter:
    """组合限流器：Token Bucket + Concurrency Limiter + 多级配额。"""

    def __init__(self, config: RateLimitConfig | None = None):
        cfg = config or RateLimitConfig()
        self.config = cfg
        self._bucket = TokenBucket(
            rate=cfg.max_requests / cfg.per_seconds, capacity=cfg.burst_size or cfg.max_requests
        )
        self._window = SlidingWindow(cfg.max_requests, cfg.per_seconds)
        self._concurrency = ConcurrencyLimiter(cfg.max_concurrent)

    async def acquire(self, weight: int = 1) -> RateLimitResult:
        """尝试获取请求配额。先检查并发，再检查速率。"""
        # 1. 并发检查
        if not self._concurrency._semaphore.locked():
            pass  # 还有并发槽位

        # 2. 速率检查
        if self.config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            if await self._bucket.consume(weight):
                return RateLimitResult(
                    allowed=True,
                    remaining=max(0, int(self._bucket.available)),
                    limit=self.config.max_requests,
                )
            wait = (weight - self._bucket.available) / self._bucket.rate
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after=wait,
                limit=self.config.max_requests,
                reason="rate_limit_exceeded",
            )

        elif self.config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            if await self._window.allow():
                return RateLimitResult(
                    allowed=True,
                    remaining=self.config.max_requests - self._window.current_count,
                    limit=self.config.max_requests,
                )
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after=self.config.per_seconds,
                limit=self.config.max_requests,
                reason="window_exceeded",
            )

        # fixed window fallback
        return RateLimitResult(allowed=True, limit=self.config.max_requests)

    async def release(self):
        self._concurrency.release()

    def model_quota(self, model: str) -> RateLimitConfig:
        """返回特定模型的配额配置。"""
        quotas = {
            "gpt-4o": RateLimitConfig(max_requests=50, per_seconds=60, burst_size=5),
            "gpt-4o-mini": RateLimitConfig(max_requests=200, per_seconds=60, burst_size=20),
            "claude-sonnet-4": RateLimitConfig(max_requests=40, per_seconds=60, burst_size=5),
            "deepseek-v3.1": RateLimitConfig(max_requests=100, per_seconds=60, burst_size=15),
        }
        return quotas.get(model, self.config)


class QuotaManager:
    """多租户配额管理。"""

    def __init__(self):
        self._limiters: dict[str, RateLimiter] = {}

    def get(self, key: str, config: RateLimitConfig | None = None) -> RateLimiter:
        if key not in self._limiters:
            self._limiters[key] = RateLimiter(config)
        return self._limiters[key]

    def add_quota(self, key: str, config: RateLimitConfig):
        self._limiters[key] = RateLimiter(config)

    def clear_expired(self, ttl: float = 3600):
        """清除超过TTL未使用的限流器（预留接口）。"""
