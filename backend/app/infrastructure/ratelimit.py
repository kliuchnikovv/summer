"""Redis-backed RateLimiter: per-principal daily quota, concurrency, burst.

Raises the domain RateLimited error (the HTTP layer maps it to 429 + Retry-After).
Concurrency uses an atomic Lua script over a ZSET whose stale entries age out by score
(crash-safe), which dovetails with the resumability design.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.domain.errors import RateLimited
from app.infrastructure.config import get_settings

_ACQUIRE_SLOT_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local maxc = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - ttl)
if redis.call('ZSCORE', key, member) then
  return 1
end
if redis.call('ZCARD', key) >= maxc then
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, ttl)
return 1
"""


def _seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return max(1, int((end - now).total_seconds()) + 1)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _minute() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M")


class RedisRateLimiter:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.s = get_settings()

    async def check_daily(self, principal: str, limit: int | None = None) -> None:
        effective = limit if limit is not None else self.s.daily_limit
        key = f"ratelimit:day:{principal}:{_today()}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, _seconds_until_utc_midnight())
        if count > effective:
            raise RateLimited(f"Daily quota of {effective} calls exceeded.",
                              retry_after=_seconds_until_utc_midnight())

    async def check_burst(self, principal: str) -> None:
        key = f"ratelimit:burst:{principal}:{_minute()}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 60)
        if count > self.s.rate_per_min:
            raise RateLimited(f"Rate limit of {self.s.rate_per_min} calls/min exceeded.", retry_after=60)

    async def try_acquire_slot(self, principal: str, doc_id: str) -> bool:
        res = await self.redis.eval(
            _ACQUIRE_SLOT_LUA, 1, f"inflight:{principal}",
            str(time.time()), str(self.s.inflight_ttl_seconds), str(self.s.max_concurrent), doc_id,
        )
        return int(res) == 1

    async def release_slots(self, principal: str, doc_ids: list[str]) -> None:
        if doc_ids:
            await self.redis.zrem(f"inflight:{principal}", *doc_ids)
