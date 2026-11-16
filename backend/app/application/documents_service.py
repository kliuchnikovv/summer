"""Use cases for documents: upload, list, get, batch."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.application.dto import UploadAccepted, UploadResponse
from app.application.ports import (
    DocumentRepository,
    JobQueue,
    PdfInspector,
    RateLimiter,
)
from app.domain.errors import InvalidRequest, NotFound, PageLimitExceeded, RateLimited
from app.domain.models import DocStatus, DocumentResult, DocumentState, ParserType, Principal
from app.domain.services import make_doc_id


@dataclass
class IncomingFile:
    filename: str
    raw: bytes
    content_hash: str


class DocumentService:
    def __init__(
        self,
        repo: DocumentRepository,
        queue: JobQueue,
        limiter: RateLimiter,
        pdf: PdfInspector,
        *,
        gemini_max_pages: int,
        gemini_page_cutoff_enabled: bool,
        max_files: int = 20,
    ):
        self._repo = repo
        self._queue = queue
        self._limiter = limiter
        self._pdf = pdf
        self._gemini_max_pages = gemini_max_pages
        self._gemini_page_cutoff_enabled = gemini_page_cutoff_enabled
        self._max_files = max_files

    async def upload(self, principal: Principal, parser: ParserType, files: list[IncomingFile]) -> UploadResponse:
        if not files:
            raise InvalidRequest("No files provided.")
        if len(files) > self._max_files:
            raise InvalidRequest(f"At most {self._max_files} files per request.")

        # Per-request limits.
        await self._limiter.check_burst(principal.id)
        await self._limiter.check_daily(principal.id, principal.daily_limit)

        batch_id = uuid4().hex
        accepted: list[UploadAccepted] = []
        acquired: list[str] = []
        try:
            for f in files:
                pages = self._pdf.count_pages(f.raw)  # raises InvalidPDF -> 422

                if (parser == ParserType.GEMINI and self._gemini_page_cutoff_enabled
                        and pages > self._gemini_max_pages):
                    raise PageLimitExceeded(
                        f"'{f.filename}' has {pages} pages; the model accepts up to {self._gemini_max_pages}."
                    )

                doc_id = make_doc_id(f.content_hash, parser, principal.id)
                state, duplicate = await self._repo.create(
                    doc_id=doc_id, principal=principal.id, parser=parser, filename=f.filename,
                    content_hash=f.content_hash, batch_id=batch_id, raw_bytes=f.raw, page_count=pages,
                )

                if duplicate:
                    if state.status == DocStatus.FAILED:  # resume-by-file: re-queue a failed doc
                        if not await self._limiter.try_acquire_slot(principal.id, doc_id):
                            raise RateLimited("Max concurrent documents in processing.", retry_after=10)
                        acquired.append(doc_id)
                        await self._repo.set_status(doc_id, DocStatus.QUEUED, error="")
                        await self._queue.enqueue(doc_id, parser)
                        accepted.append(UploadAccepted(id=doc_id, filename=state.filename,
                                                       status=DocStatus.QUEUED, duplicate=True))
                    else:
                        accepted.append(UploadAccepted(id=doc_id, filename=state.filename,
                                                       status=state.status, duplicate=True))
                    continue

                if not await self._limiter.try_acquire_slot(principal.id, doc_id):
                    raise RateLimited("Max concurrent documents in processing.", retry_after=10)
                acquired.append(doc_id)
                await self._queue.enqueue(doc_id, parser)
                accepted.append(UploadAccepted(id=doc_id, filename=f.filename,
                                               status=DocStatus.QUEUED, duplicate=False))
        except Exception:
            await self._limiter.release_slots(principal.id, acquired)
            raise

        return UploadResponse(batch_id=batch_id, documents=accepted)

    async def get_owned(self, doc_id: str, principal: Principal) -> DocumentResult:
        result = await self._repo.get_result(doc_id)
        if result is None or result.principal != principal.id:
            raise NotFound("Document not found.")
        return result

    async def list_for(self, principal: Principal, limit: int) -> list[DocumentState]:
        return await self._repo.list_documents(principal.id, limit=min(max(1, limit), 500))

    async def batch(self, batch_id: str, principal: Principal) -> list[DocumentResult]:
        docs: list[DocumentResult] = []
        for did in await self._repo.batch_doc_ids(batch_id):
            result = await self._repo.get_result(did)
            if result is not None and result.principal == principal.id:
                docs.append(result)
        return docs
