"""Queue + worker happy path and ack behavior."""
from __future__ import annotations

from app.domain.models import DocStatus, ParserType
from app.domain.services import make_doc_id
from app.infrastructure.config import get_settings
from app.infrastructure.queue import RedisStreamQueue
from app.infrastructure.repository import RedisDocumentRepository
from app.interfaces.worker import Worker


async def _seed(redis, doc_id, parser, principal, raw):
    repo = RedisDocumentRepository(redis)
    await repo.create(
        doc_id=doc_id, principal=principal, parser=parser, filename="f.pdf",
        content_hash=doc_id, batch_id="b", raw_bytes=raw, page_count=2,
    )
    queue = RedisStreamQueue(redis)
    await queue.ensure_group()
    await queue.enqueue(doc_id, parser)
    return repo, queue


async def test_worker_processes_and_acks(redis, pdf_bytes):
    parser = ParserType.PYPDF
    doc_id = make_doc_id("zzz", parser, "alice")
    repo, queue = await _seed(redis, doc_id, parser, "alice", pdf_bytes)

    worker = Worker()
    entries = await queue.read("c1", count=5)
    assert len(entries) == 1
    msg_id, fields = entries[0]
    await worker.handle(msg_id, fields)

    result = await repo.get_result(doc_id)
    assert result.status == DocStatus.DONE
    assert len(result.pages) == 2

    s = get_settings()
    pending = await redis.xpending(s.stream_name, s.consumer_group)
    assert pending["pending"] == 0


async def test_worker_releases_concurrency_slot_on_done(redis, pdf_bytes):
    parser = ParserType.PYPDF
    doc_id = make_doc_id("slot", parser, "alice")
    repo, queue = await _seed(redis, doc_id, parser, "alice", pdf_bytes)
    await redis.zadd("inflight:alice", {doc_id: 1})

    worker = Worker()
    entries = await queue.read("c1", count=5)
    await worker.handle(entries[0][0], entries[0][1])

    assert await redis.zcard("inflight:alice") == 0
