"""Redis Streams JobQueue: enqueue, consumer-group read, ack, reaper, dead-letter."""
from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.domain.models import ParserType
from app.infrastructure.config import get_settings


class RedisStreamQueue:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.s = get_settings()

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(self.s.stream_name, self.s.consumer_group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, doc_id: str, parser: ParserType) -> str:
        return await self.redis.xadd(self.s.stream_name, {"doc_id": doc_id, "parser": parser.value})

    async def read(self, consumer: str, count: int = 1) -> list[tuple[str, dict]]:
        try:
            resp = await self.redis.xreadgroup(
                groupname=self.s.consumer_group, consumername=consumer,
                streams={self.s.stream_name: ">"}, count=count, block=self.s.block_ms,
            )
        except (RedisTimeoutError, asyncio.TimeoutError):
            return []  # blocking read idled out with no new entries
        if not resp:
            return []
        return resp[0][1]

    async def ack(self, msg_id: str) -> None:
        await self.redis.xack(self.s.stream_name, self.s.consumer_group, msg_id)

    async def reclaim_stale(self, consumer: str, count: int = 10) -> list[tuple[str, dict]]:
        resp = await self.redis.xautoclaim(
            name=self.s.stream_name, groupname=self.s.consumer_group, consumername=consumer,
            min_idle_time=self.s.reaper_min_idle_ms, start_id="0-0", count=count,
        )
        claimed = resp[1] if len(resp) >= 2 else []
        return claimed

    async def delivery_count(self, msg_id: str) -> int:
        pending = await self.redis.xpending_range(
            name=self.s.stream_name, groupname=self.s.consumer_group, min=msg_id, max=msg_id, count=1,
        )
        return int(pending[0]["times_delivered"]) if pending else 0

    async def dead_letter(self, msg_id: str, doc_id: str, parser: str, reason: str) -> None:
        await self.redis.xadd(self.s.dead_stream_name,
                              {"doc_id": doc_id, "parser": parser, "reason": reason, "orig_id": msg_id})
        await self.ack(msg_id)
