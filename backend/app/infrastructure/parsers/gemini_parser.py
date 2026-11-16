"""Markdown parser: PDF -> markdown via OpenRouter (Gemini model by default).

Strategy: send the whole PDF natively; on the provider's minimum-balance rule for file
inputs, degrade to per-page image parsing with the same model.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.domain.errors import ParserError
from app.domain.models import ParserType
from app.domain.services import split_pages
from app.infrastructure import openrouter
from app.infrastructure.parsers.base import OpenRouterParserBase
from app.infrastructure.pdf import render_pages_png

logger = logging.getLogger(__name__)


class GeminiParser(OpenRouterParserBase):
    """Named 'gemini' in the API; backed by OpenRouter's configured parse model."""

    name = ParserType.GEMINI

    async def _parse_real(self, raw: bytes, pages: int) -> AsyncIterator[tuple[int, str]]:
        try:
            markdown = await openrouter.pdf_to_markdown(raw)
        except Exception as exc:  # noqa: BLE001
            if openrouter.is_file_input_error(exc):
                logger.warning("PDF-file input unavailable (%s); falling back to per-page images", exc)
                async for item in self._image_pages(raw):
                    yield item
                return
            raise ParserError(f"OpenRouter parse failed: {exc}") from exc

        for i, chunk in enumerate(split_pages(markdown)):
            yield i, chunk

    async def _image_pages(self, raw: bytes) -> AsyncIterator[tuple[int, str]]:
        try:
            images = await asyncio.to_thread(render_pages_png, raw)
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"Page rasterization failed: {exc}") from exc
        for i, png in enumerate(images):
            try:
                md = await openrouter.parse_image(png)
            except Exception as exc:  # noqa: BLE001
                raise ParserError(f"OpenRouter image parse failed on page {i + 1}: {exc}") from exc
            yield i, md.strip()
