"""OCR parser: rasterize each page and OCR to markdown via OpenRouter (GPT-5 Mini default).

Strategy: OCR is image-based, so every page is always rasterized and transcribed.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.domain.errors import ParserError
from app.domain.models import ParserType
from app.infrastructure import openrouter
from app.infrastructure.parsers.base import OpenRouterParserBase
from app.infrastructure.pdf import render_pages_png

logger = logging.getLogger(__name__)


class OpenAIOCRParser(OpenRouterParserBase):
    """Named 'openai' in the API; backed by OpenRouter's configured OCR (vision) model."""

    name = ParserType.OPENAI

    async def _parse_real(self, raw: bytes, pages: int) -> AsyncIterator[tuple[int, str]]:
        try:
            images = await asyncio.to_thread(render_pages_png, raw)
        except Exception as exc:  # noqa: BLE001
            raise ParserError(f"Page rasterization failed: {exc}") from exc
        for i, png in enumerate(images):
            try:
                md = await openrouter.ocr_image(png)
            except Exception as exc:  # noqa: BLE001
                raise ParserError(f"OpenRouter OCR failed on page {i + 1}: {exc}") from exc
            yield i, md.strip()
