"""HTTP routes for documents: upload, list, get, SSE, batch."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.application.documents_service import DocumentService, IncomingFile
from app.application.dto import UploadResponse
from app.domain.errors import PayloadTooLarge
from app.domain.models import DocStatus, DocumentResult, DocumentState, ParserType, Principal
from app.infrastructure.config import get_settings
from app.infrastructure.redis_client import get_redis
from app.infrastructure.repository import RedisDocumentRepository, k_events
from app.interfaces.deps import document_service, require_principal

router = APIRouter(tags=["documents"])

_CHUNK = 1 << 20  # 1 MB


async def _read_capped(upload: UploadFile, cap: int) -> IncomingFile:
    """Stream the upload, enforcing the byte cap authoritatively (never trust headers)."""
    hasher = hashlib.sha256()
    buf = bytearray()
    total = 0
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise PayloadTooLarge(f"File '{upload.filename}' exceeds the {cap} byte limit.")
        hasher.update(chunk)
        buf.extend(chunk)
    return IncomingFile(filename=upload.filename or "upload.pdf", raw=bytes(buf),
                        content_hash=hasher.hexdigest())


@router.post("/documents", response_model=UploadResponse, status_code=202)
async def upload_documents(
    request: Request,
    parser: ParserType = Form(...),
    files: list[UploadFile] = File(...),
    principal: Principal = Depends(require_principal),
    svc: DocumentService = Depends(document_service),
) -> UploadResponse:
    settings = get_settings()
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > settings.max_upload_bytes * 20:
        raise PayloadTooLarge("Request body too large.")
    incoming = [await _read_capped(f, settings.max_upload_bytes) for f in files]
    return await svc.upload(principal, parser, incoming)


@router.get("/documents", response_model=list[DocumentState])
async def list_documents(
    limit: int = 100,
    principal: Principal = Depends(require_principal),
    svc: DocumentService = Depends(document_service),
) -> list[DocumentState]:
    """The caller's own documents, newest first — metadata only (no page/summary content)."""
    return await svc.list_for(principal, limit)


@router.get("/documents/{doc_id}", response_model=DocumentResult)
async def get_document(
    doc_id: str,
    principal: Principal = Depends(require_principal),
    svc: DocumentService = Depends(document_service),
) -> DocumentResult:
    return await svc.get_owned(doc_id, principal)


@router.get("/batches/{batch_id}")
async def get_batch(
    batch_id: str,
    principal: Principal = Depends(require_principal),
    svc: DocumentService = Depends(document_service),
) -> dict:
    return {"batch_id": batch_id, "documents": await svc.batch(batch_id, principal)}


def _sse(data: str) -> str:
    return f"data: {data}\n\n"


@router.get("/documents/{doc_id}/events")
async def document_events(
    doc_id: str,
    principal: Principal = Depends(require_principal),
    svc: DocumentService = Depends(document_service),
) -> StreamingResponse:
    """SSE: live status/pages/summary for one document (snapshot then deltas)."""
    await svc.get_owned(doc_id, principal)  # 404/ownership before streaming
    redis = get_redis()
    repo = RedisDocumentRepository(redis)

    async def event_gen():
        pubsub = redis.pubsub()
        await pubsub.subscribe(k_events(doc_id))
        try:
            snapshot = await repo.get_result(doc_id)
            if snapshot is not None:
                yield _sse(snapshot.model_dump_json())
                if snapshot.status in (DocStatus.DONE, DocStatus.FAILED):
                    return
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                if msg is None:
                    yield ": keep-alive\n\n"
                    continue
                data = msg["data"]
                yield _sse(data)
                if '"status":"done"' in data or '"status":"failed"' in data:
                    return
        finally:
            await pubsub.unsubscribe(k_events(doc_id))
            await pubsub.aclose()

    return StreamingResponse(
        event_gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
