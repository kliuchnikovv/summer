"""Rate limiting: daily quota, concurrency slots, burst (RedisRateLimiter)."""
from __future__ import annotations

import pytest

from app.domain.errors import RateLimited
from app.infrastructure.config import get_settings
from app.infrastructure.ratelimit import RedisRateLimiter


async def test_daily_quota_enforced(redis, monkeypatch):
    monkeypatch.setenv("DAILY_LIMIT", "3")
    get_settings.cache_clear()
    rl = RedisRateLimiter(redis)
    for _ in range(3):
        await rl.check_daily("alice")
    with pytest.raises(RateLimited) as exc:
        await rl.check_daily("alice")
    assert exc.value.retry_after > 0
    get_settings.cache_clear()


async def test_per_account_daily_limit_override(redis, monkeypatch):
    monkeypatch.setenv("DAILY_LIMIT", "100")
    get_settings.cache_clear()
    rl = RedisRateLimiter(redis)
    for _ in range(2):
        await rl.check_daily("alice", limit=2)
    with pytest.raises(RateLimited):
        await rl.check_daily("alice", limit=2)  # override beats the global default
    get_settings.cache_clear()


async def test_concurrency_cap(redis, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT", "2")
    get_settings.cache_clear()
    rl = RedisRateLimiter(redis)
    assert await rl.try_acquire_slot("bob", "d1") is True
    assert await rl.try_acquire_slot("bob", "d2") is True
    assert await rl.try_acquire_slot("bob", "d3") is False
    assert await rl.try_acquire_slot("bob", "d1") is True  # idempotent re-acquire
    await rl.release_slots("bob", ["d1"])
    assert await rl.try_acquire_slot("bob", "d3") is True
    get_settings.cache_clear()


async def test_burst_limit(redis, monkeypatch):
    monkeypatch.setenv("RATE_PER_MIN", "2")
    get_settings.cache_clear()
    rl = RedisRateLimiter(redis)
    await rl.check_burst("carol")
    await rl.check_burst("carol")
    with pytest.raises(RateLimited):
        await rl.check_burst("carol")
    get_settings.cache_clear()


async def test_concurrency_isolated_per_principal(redis, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT", "1")
    get_settings.cache_clear()
    rl = RedisRateLimiter(redis)
    assert await rl.try_acquire_slot("u1", "a") is True
    assert await rl.try_acquire_slot("u2", "b") is True
    assert await rl.try_acquire_slot("u1", "c") is False
    get_settings.cache_clear()
