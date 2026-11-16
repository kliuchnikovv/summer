"""Stream consumer worker: process documents, ack, reclaim orphans, dead-letter poison.

All workers share one consumer group, so the stream load-balances documents across them.
Survives Redis restarts: the loop catches transient errors, reconnects and re-ensures the group.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket

from app.domain.models import DocStatus
from app.infrastructure.config import get_settings
from app.infrastructure.queue import RedisStreamQueue
from app.infrastructure.redis_client import get_redis
from app.infrastructure.repository import RedisDocumentRepository
from app.interfaces.deps import build_processing_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("worker")


def _consumer_name() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class Worker:
    def __init__(self):
        self.redis = get_redis()
        self.queue = RedisStreamQueue(self.redis)
        self.repo = RedisDocumentRepository(self.redis)
        self.processing = build_processing_service()
        self.settings = get_settings()
        self.consumer = _consumer_name()

    async def handle(self, msg_id: str, fields: dict) -> None:
        doc_id = fields.get("doc_id")
        parser = fields.get("parser", "")
        if not doc_id:
            await self.queue.ack(msg_id)
            return

        attempts = await self.queue.delivery_count(msg_id)
        if attempts > self.settings.max_delivery_attempts:
            logger.error("doc %s exceeded %d attempts; dead-lettering", doc_id, self.settings.max_delivery_attempts)
            state = await self.repo.get_state(doc_id)
            if state is not None:
                await self.repo.set_status(doc_id, DocStatus.FAILED, error="exceeded max retry attempts")
                await self.repo.release_inflight(state.principal, doc_id)
            await self.queue.dead_letter(msg_id, doc_id, parser, "max attempts exceeded")
            return

        try:
            await self.processing.process(doc_id)
            await self.queue.ack(msg_id)  # terminal -> remove from PEL
        except Exception:  # noqa: BLE001 - unexpected: leave unacked for reaper-driven retry
            logger.exception("unexpected error processing doc %s (attempt %d); will retry", doc_id, attempts)

    async def _reaper_loop(self) -> None:
        interval = max(1.0, self.settings.reaper_min_idle_ms / 1000 / 2)
        while True:
            try:
                for msg_id, fields in await self.queue.reclaim_stale(self.consumer):
                    logger.info("reclaimed orphaned entry %s (doc %s)", msg_id, fields.get("doc_id"))
                    await self.handle(msg_id, fields)
            except Exception:  # noqa: BLE001
                logger.exception("reaper iteration failed")
            await asyncio.sleep(interval)

    async def run(self) -> None:
        await self.queue.ensure_group()
        logger.info("worker %s started; group=%s stream=%s",
                    self.consumer, self.settings.consumer_group, self.settings.stream_name)
        reaper = asyncio.create_task(self._reaper_loop())
        try:
            while True:
                try:
                    await self.queue.ensure_group()  # recreate group if Redis was wiped/restarted
                    for msg_id, fields in await self.queue.read(self.consumer, count=1):
                        await self.handle(msg_id, fields)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - survive Redis restarts / transient errors
                    logger.exception("worker loop error; retrying in 1s")
                    await asyncio.sleep(1.0)
        finally:
            reaper.cancel()


async def run_worker() -> None:
    await Worker().run()
