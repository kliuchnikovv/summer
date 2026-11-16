"""Shared base for OpenRouter-backed parsers.

Template method: the common guard (validate PDF, mock fallback when no key / over the
page limit) lives here; each concrete strategy implements only its real parsing path.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.domain.errors import InvalidPDF, ParserError
from app.domain.models import ParserType
from app.infrastructure import openrouter
from app.infrastructure.config import get_settings
from app.infrastructure.pdf import count_pages, extract_text_pages


class OpenRouterParserBase(ABC):
    name: ParserType

    async def iter_pages(self, raw: bytes) -> AsyncIterator[tuple[int, str]]:
        try:
            pages = count_pages(raw)
        except InvalidPDF as exc:
            raise ParserError(str(exc)) from exc

        # No key, or beyond the provider's page limit -> deterministic local mock.
        if not openrouter.available() or pages > get_settings().gemini_max_pages:
            async for item in self._mock(raw):
                yield item
            return

        async for item in self._parse_real(raw, pages):
            yield item

    @abstractmethod
    def _parse_real(self, raw: bytes, pages: int) -> AsyncIterator[tuple[int, str]]:
        """The strategy's real (AI-backed) parsing path."""
        raise NotImplementedError

    async def _mock(self, raw: bytes) -> AsyncIterator[tuple[int, str]]:
        try:
            texts = extract_text_pages(raw)
        except InvalidPDF as exc:
            raise ParserError(str(exc)) from exc
        for i, text in enumerate(texts):
            yield i, openrouter.mock_markdown_from_text(text, i)
