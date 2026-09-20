"""Async token-bucket rate limiter and retry helpers."""

from __future__ import annotations

import asyncio
import random
import time

__all__ = ["RateLimiter", "RetryPolicy", "backoff_delay"]


class RateLimiter:
    """Token-bucket rate limiter safe for concurrent async use.

    ``rate`` is sustained requests per second; ``burst`` is the bucket
    capacity (max requests allowed in an instant). A semaphore caps the
    number of in-flight requests.
    """

    def __init__(self, rate: float = 5.0, burst: int = 5, max_concurrent: int = 4) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if burst <= 0:
            raise ValueError("burst must be positive")
        self.rate = float(rate)
        self.capacity = float(burst)
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def acquire(self) -> None:
        """Wait until a request slot is available, then reserve it."""
        await self._semaphore.acquire()
        try:
            while True:
                async with self._lock:
                    now = time.monotonic()
                    self._tokens = min(
                        self.capacity, self._tokens + (now - self._updated) * self.rate
                    )
                    self._updated = now
                    if self._tokens >= 1.0:
                        self._tokens -= 1.0
                        return
                    wait = (1.0 - self._tokens) / self.rate
                await asyncio.sleep(wait)
        except BaseException:
            self._semaphore.release()
            raise

    def release(self) -> None:
        """Release the concurrency slot after a request finishes."""
        self._semaphore.release()

    async def __aenter__(self) -> RateLimiter:
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.release()


def backoff_delay(
    attempt: int,
    *,
    base: float = 0.5,
    factor: float = 2.0,
    maximum: float = 30.0,
    jitter: float = 0.25,
    retry_after: float | None = None,
) -> float:
    """Exponential backoff with jitter, honoring a server ``Retry-After``."""
    delay = min(maximum, base * (factor**attempt))
    if retry_after is not None:
        delay = max(delay, retry_after)
    return delay + random.uniform(0, jitter * delay)


class RetryPolicy:
    """Configuration for automatic retries on transient failures."""

    def __init__(
        self,
        max_attempts: int = 3,
        retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504}),
        backoff_base: float = 0.5,
        backoff_max: float = 30.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.retry_statuses = retry_statuses
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        return backoff_delay(
            attempt,
            base=self.backoff_base,
            maximum=self.backoff_max,
            retry_after=retry_after,
        )
