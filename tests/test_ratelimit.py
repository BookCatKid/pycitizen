"""Tests for the token-bucket rate limiter and backoff."""

from __future__ import annotations

import asyncio
import time

import pytest

from pycitizen.ratelimit import RateLimiter, RetryPolicy, backoff_delay


async def test_burst_immediate() -> None:
    limiter = RateLimiter(rate=1.0, burst=3)
    start = time.monotonic()
    for _ in range(3):
        async with limiter:
            pass
    assert time.monotonic() - start < 0.5


async def test_sustained_rate_enforced() -> None:
    limiter = RateLimiter(rate=20.0, burst=1, max_concurrent=1)
    start = time.monotonic()
    for _ in range(3):
        async with limiter:
            pass
    # 3 requests at burst=1, 20/s -> ~0.1s minimum.
    assert time.monotonic() - start >= 0.09


async def test_concurrency_capped() -> None:
    limiter = RateLimiter(rate=10_000, burst=10_000, max_concurrent=2)
    running = 0
    peak = 0

    async def worker() -> None:
        nonlocal running, peak
        async with limiter:
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

    await asyncio.gather(*(worker() for _ in range(6)))
    assert peak == 2


async def test_release_on_exception() -> None:
    limiter = RateLimiter(rate=10_000, burst=10_000, max_concurrent=1)
    with pytest.raises(RuntimeError):
        async with limiter:
            raise RuntimeError("boom")
    # Slot must have been released; this would hang otherwise.
    async with asyncio.timeout(1):
        async with limiter:
            pass


def test_backoff_growth() -> None:
    d0 = backoff_delay(0, base=0.5, jitter=0)
    d3 = backoff_delay(3, base=0.5, jitter=0)
    assert d0 == 0.5
    assert d3 == 4.0


def test_backoff_honors_retry_after() -> None:
    assert backoff_delay(0, base=0.5, jitter=0, retry_after=10.0) == 10.0


def test_backoff_capped() -> None:
    assert backoff_delay(20, base=0.5, jitter=0, maximum=30.0) == 30.0


def test_retry_policy_validation() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RateLimiter(rate=0)
    with pytest.raises(ValueError):
        RateLimiter(burst=0)
