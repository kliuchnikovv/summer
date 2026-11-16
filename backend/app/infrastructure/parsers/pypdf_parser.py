"""PyPDF parser: text-only extraction, one page at a time."""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.domain.errors import InvalidPDF, ParserError
from app.domain.models import ParserType
from app.infrastructure.pdf import extract_text_pages


class PyPDFParser:
    name = ParserType.PYPDF

    async def iter_pages(self, raw: bytes) -> AsyncIterator[tuple[int, str]]:
        try:
            pages = extract_text_pages(raw)
        except InvalidPDF as exc:
            raise ParserError(str(exc)) from exc
        for i, text in enumerate(pages):
            yield i, text
