"""Idempotency + resumability at the repository/processing level."""
from __future__ import annotations

from app.application.processing_service import ProcessingService
from app.domain.models import DocStatus, ParserType
from app.domain.services import make_doc_id
from app.infrastructure.parsers.registry import ParserRegistryImpl
from app.infrastructure.repository import RedisDocumentRepository
from app.infrastructure.summarizer import OpenRouterSummarizer


def _svc(redis) -> tuple[RedisDocumentRepository, ProcessingService]:
    repo = RedisDocumentRepository(redis)
    return repo, ProcessingService(repo, ParserRegistryImpl(), OpenRouterSummarizer())


async def _create(repo, raw, parser=ParserType.PYPDF, principal="alice"):
    content_hash = "abc123"
    doc_id = make_doc_id(content_hash, parser, principal)
    state, dup = await repo.create(
        doc_id=doc_id, principal=principal, parser=parser, filename="f.pdf",
        content_hash=content_hash, batch_id="b1", raw_bytes=raw, page_count=2,
    )
    return doc_id, state, dup


async def test_create_is_idempotent(redis, pdf_bytes):
    repo, _ = _svc(redis)
    doc_id1, _, dup1 = await _create(repo, pdf_bytes)
    doc_id2, _, dup2 = await _create(repo, pdf_bytes)
    assert doc_id1 == doc_id2
    assert dup1 is False
    assert dup2 is True


async def test_doc_id_depends_on_parser(redis, pdf_bytes):
    repo, _ = _svc(redis)
    id_pypdf, _, _ = await _create(repo, pdf_bytes, parser=ParserType.PYPDF)
    id_gemini, _, _ = await _create(repo, pdf_bytes, parser=ParserType.GEMINI)
    assert id_pypdf != id_gemini


def test_doc_id_is_per_principal():
    h = "samehash"
    alice = make_doc_id(h, ParserType.PYPDF, "alice")
    bob = make_doc_id(h, ParserType.PYPDF, "bob")
    alice2 = make_doc_id(h, ParserType.PYPDF, "alice")
    assert alice != bob
    assert alice == alice2


async def test_pipeline_runs_to_done(redis, pdf_bytes):
    repo, proc = _svc(redis)
    doc_id, _, _ = await _create(repo, pdf_bytes)
    final = await proc.process(doc_id)
    assert final == DocStatus.DONE
    result = await repo.get_result(doc_id)
    assert result.status == DocStatus.DONE
    assert len(result.pages) == 2
    assert result.summary is not None


async def test_pipeline_idempotent_on_done(redis, pdf_bytes):
    repo, proc = _svc(redis)
    doc_id, _, _ = await _create(repo, pdf_bytes)
    await proc.process(doc_id)
    assert await proc.process(doc_id) == DocStatus.DONE


async def test_resume_skips_parse_when_already_parsed(redis, pdf_bytes, monkeypatch):
    """If a doc is already PARSED (crash before summary), re-processing must NOT re-parse."""
    repo, proc = _svc(redis)
    doc_id, _, _ = await _create(repo, pdf_bytes)

    await repo.save_page(doc_id, 0, "page0")
    await repo.save_page(doc_id, 1, "page1")
    await repo.set_status(doc_id, DocStatus.PARSED, page_count=2)

    called = {"parse": False}
    from app.infrastructure.parsers import pypdf_parser

    orig = pypdf_parser.PyPDFParser.iter_pages

    async def spy(self, raw):  # pragma: no cover - should not run
        called["parse"] = True
        async for x in orig(self, raw):
            yield x

    monkeypatch.setattr(pypdf_parser.PyPDFParser, "iter_pages", spy)

    final = await proc.process(doc_id)
    assert final == DocStatus.DONE
    assert called["parse"] is False
    result = await repo.get_result(doc_id)
    assert result.pages == ["page0", "page1"]
    assert result.summary is not None
