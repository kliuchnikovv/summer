"""Redis-backed DocumentRepository.

Binary PDF bytes are base64-encoded so they coexist with a decode_responses=True client.
Each stage transition publishes the current result on a per-document Pub/Sub channel (SSE).
"""
from __future__ import annotations

import base64
import time

import redis.asyncio as aioredis

from app.domain.models import DocStatus, DocumentResult, DocumentState, ParserType
from app.infrastructure.config import get_settings


def _now() -> float:
    return time.time()


def k_doc(doc_id: str) -> str: return f"doc:{doc_id}"
def k_raw(doc_id: str) -> str: return f"doc:{doc_id}:raw"
def k_pages(doc_id: str) -> str: return f"doc:{doc_id}:pages"
def k_summary(doc_id: str) -> str: return f"doc:{doc_id}:summary"
def k_events(doc_id: str) -> str: return f"doc:{doc_id}:events"
def k_idem(doc_id: str) -> str: return f"idem:{doc_id}"
def k_batch(batch_id: str) -> str: return f"batch:{batch_id}"
def k_inflight(principal: str) -> str: return f"inflight:{principal}"
def k_principal_docs(principal: str) -> str: return f"docs:principal:{principal}"


class RedisDocumentRepository:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.settings = get_settings()

    async def create(self, *, doc_id, principal, parser, filename, content_hash,
                     batch_id, raw_bytes, page_count) -> tuple[DocumentState, bool]:
        won = await self.redis.set(k_idem(doc_id), "1", nx=True)
        if not won:
            existing = await self.get_state(doc_id)
            if existing is not None:
                return existing, True

        now = _now()
        state = DocumentState(
            id=doc_id, principal=principal, parser=parser, filename=filename,
            status=DocStatus.QUEUED, content_hash=content_hash, batch_id=batch_id,
            page_count=page_count, created_at=now, updated_at=now,
        )
        mapping = {
            "id": doc_id, "principal": principal, "parser": parser.value, "filename": filename,
            "status": DocStatus.QUEUED.value, "content_hash": content_hash, "batch_id": batch_id,
            "page_count": "" if page_count is None else str(page_count), "error": "",
            "created_at": str(now), "updated_at": str(now),
        }
        pipe = self.redis.pipeline()
        pipe.hset(k_doc(doc_id), mapping=mapping)
        pipe.set(k_raw(doc_id), base64.b64encode(raw_bytes).decode(), ex=self.settings.raw_ttl_seconds)
        pipe.sadd(k_batch(batch_id), doc_id)
        pipe.expire(k_batch(batch_id), self.settings.raw_ttl_seconds)
        pipe.zadd(k_principal_docs(principal), {doc_id: now})
        await pipe.execute()
        return state, False

    async def get_state(self, doc_id: str) -> DocumentState | None:
        data = await self.redis.hgetall(k_doc(doc_id))
        return _state_from_hash(data) if data else None

    async def get_raw(self, doc_id: str) -> bytes | None:
        b64 = await self.redis.get(k_raw(doc_id))
        return base64.b64decode(b64) if b64 is not None else None

    async def get_pages(self, doc_id: str) -> list[str]:
        pages = await self.redis.hgetall(k_pages(doc_id))
        if not pages:
            return []
        return [pages[str(i)] for i in sorted(int(x) for x in pages.keys())]

    async def get_summary(self, doc_id: str) -> str | None:
        return await self.redis.get(k_summary(doc_id))

    async def get_result(self, doc_id: str) -> DocumentResult | None:
        state = await self.get_state(doc_id)
        if state is None:
            return None
        pages = await self.get_pages(doc_id)
        summary = await self.get_summary(doc_id)
        return DocumentResult(
            id=state.id, principal=state.principal, parser=state.parser, filename=state.filename,
            status=state.status, page_count=state.page_count, error=state.error,
            pages=pages, summary=summary, created_at=state.created_at, updated_at=state.updated_at,
        )

    async def set_status(self, doc_id, status, *, error=None, page_count=None) -> None:
        mapping = {"status": status.value, "updated_at": str(_now())}
        if error is not None:
            mapping["error"] = error
        if page_count is not None:
            mapping["page_count"] = str(page_count)
        await self.redis.hset(k_doc(doc_id), mapping=mapping)
        await self._publish(doc_id)

    async def save_page(self, doc_id, page_no, markdown) -> None:
        await self.redis.hset(k_pages(doc_id), str(page_no), markdown)
        await self.redis.expire(k_pages(doc_id), self.settings.raw_ttl_seconds)

    async def save_summary(self, doc_id, summary) -> None:
        await self.redis.set(k_summary(doc_id), summary, ex=self.settings.raw_ttl_seconds)

    async def clear_pages(self, doc_id) -> None:
        await self.redis.delete(k_pages(doc_id))

    async def release_inflight(self, principal, doc_id) -> None:
        await self.redis.zrem(k_inflight(principal), doc_id)

    async def batch_doc_ids(self, batch_id) -> list[str]:
        return sorted(await self.redis.smembers(k_batch(batch_id)))

    async def list_documents(self, principal, limit) -> list[DocumentState]:
        ids = await self.redis.zrevrange(k_principal_docs(principal), 0, max(0, limit - 1))
        states: list[DocumentState] = []
        for doc_id in ids:
            state = await self.get_state(doc_id)
            if state is not None:
                states.append(state)
            else:
                await self.redis.zrem(k_principal_docs(principal), doc_id)
        return states

    async def _publish(self, doc_id: str) -> None:
        result = await self.get_result(doc_id)
        if result is not None:
            await self.redis.publish(k_events(doc_id), result.model_dump_json())


def _state_from_hash(data: dict[str, str]) -> DocumentState:
    pc = data.get("page_count") or ""
    return DocumentState(
        id=data["id"], principal=data["principal"], parser=ParserType(data["parser"]),
        filename=data["filename"], status=DocStatus(data["status"]),
        content_hash=data["content_hash"], batch_id=data["batch_id"],
        page_count=int(pc) if pc else None, error=data.get("error") or None,
        created_at=float(data["created_at"]), updated_at=float(data["updated_at"]),
    )
