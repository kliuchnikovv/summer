"""Summarizer adapter: OpenRouter with deterministic mock fallback."""
from __future__ import annotations

import logging

from app.infrastructure import openrouter

logger = logging.getLogger(__name__)

_MAX_CHARS = 200_000  # guard against pathologically large inputs to the model


class OpenRouterSummarizer:
    """Implements the Summarizer port."""

    async def summarize(self, pages: list[str]) -> str:
        full = "\n\n".join(pages).strip()
        if not openrouter.available():
            return openrouter.mock_summarize(full)
        try:
            return await openrouter.summarize_text(full[:_MAX_CHARS])
        except Exception as exc:  # noqa: BLE001 - degrade rather than fail the whole doc
            logger.warning("openrouter summarize failed (%s); using mock", exc)
            return openrouter.mock_summarize(full)
