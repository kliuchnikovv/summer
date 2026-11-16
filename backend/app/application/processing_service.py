"""Use case: process one document (parse -> summarize), resumable from the last stage."""
from __future__ import annotations

import logging

from app.application.ports import DocumentRepository, ParserRegistry, Summarizer
from app.domain.errors import ParserError
from app.domain.models import DocStatus

logger = logging.getLogger(__name__)


class ProcessingService:
    def __init__(self, repo: DocumentRepository, parsers: ParserRegistry, summarizer: Summarizer):
        self._repo = repo
        self._parsers = parsers
        self._summarizer = summarizer

    async def process(self, doc_id: str) -> DocStatus:
        """Run the pipeline for one document. Returns the terminal status.

        Idempotent and crash-safe: already-completed stages are skipped, so a resumed
        document never re-runs the (possibly paid) parser. Expected document problems
        resolve to FAILED; unexpected errors propagate for retry/dead-letter.
        """
        state = await self._repo.get_state(doc_id)
        if state is None:
            logger.warning("doc %s vanished (TTL?); nothing to process", doc_id)
            return DocStatus.FAILED
        if state.status == DocStatus.DONE:
            return DocStatus.DONE

        raw = await self._repo.get_raw(doc_id)
        if raw is None:
            return await self._fail(state.principal, doc_id, "raw PDF bytes expired or missing")

        parser = self._parsers.get(state.parser)

        # Stage 1: parse (skipped if pages already produced).
        if state.status in (DocStatus.QUEUED, DocStatus.PARSING):
            await self._repo.set_status(doc_id, DocStatus.PARSING)
            await self._repo.clear_pages(doc_id)
            try:
                n_pages = 0
                async for page_no, markdown in parser.iter_pages(raw):
                    await self._repo.save_page(doc_id, page_no, markdown)
                    n_pages += 1
            except ParserError as exc:
                return await self._fail(state.principal, doc_id, str(exc))
            await self._repo.set_status(doc_id, DocStatus.PARSED, page_count=n_pages)

        # Stage 2: summarize (resume covers SUMMARIZING).
        await self._repo.set_status(doc_id, DocStatus.SUMMARIZING)
        pages = await self._repo.get_pages(doc_id)
        summary = await self._summarizer.summarize(pages)
        await self._repo.save_summary(doc_id, summary)

        await self._repo.set_status(doc_id, DocStatus.DONE)
        await self._repo.release_inflight(state.principal, doc_id)
        logger.info("doc %s done (%d pages)", doc_id, len(pages))
        return DocStatus.DONE

    async def _fail(self, principal: str, doc_id: str, error: str) -> DocStatus:
        logger.warning("doc %s failed: %s", doc_id, error)
        await self._repo.set_status(doc_id, DocStatus.FAILED, error=error)
        await self._repo.release_inflight(principal, doc_id)
        return DocStatus.FAILED
