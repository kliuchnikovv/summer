"""Parser registry + mock-mode parsing + page split."""
from __future__ import annotations

import pytest

from app.domain.errors import ParserError
from app.domain.models import ParserType
from app.domain.services import split_pages
from app.infrastructure.parsers.registry import ParserRegistryImpl

registry = ParserRegistryImpl()


@pytest.mark.parametrize("ptype", [ParserType.PYPDF, ParserType.GEMINI, ParserType.OPENAI])
async def test_parser_yields_pages_in_mock_mode(ptype, pdf_bytes):
    parser = registry.get(ptype)
    pages = [md async for _, md in parser.iter_pages(pdf_bytes)]
    assert len(pages) == 2


async def test_parser_rejects_garbage(pdf_bytes):
    parser = registry.get(ParserType.PYPDF)
    with pytest.raises(ParserError):
        _ = [x async for x in parser.iter_pages(b"garbage")]


def test_registry_covers_all_parser_types():
    for ptype in ParserType:
        assert registry.get(ptype) is not None


def test_page_split_is_whitespace_tolerant():
    assert split_pages("A\n\n<!--PAGE-BREAK-->\n\nB") == ["A", "B"]
    assert split_pages("A<!-- page-break -->B") == ["A", "B"]
    assert split_pages("Only one page\n<!--PAGE-BREAK-->\n") == ["Only one page"]
    assert split_pages("solo") == ["solo"]
