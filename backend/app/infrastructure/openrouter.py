"""OpenRouter LLM client (OpenAI-compatible) with deterministic mock fallback.

All AI work — PDF->markdown, OCR, summaries — routes through OpenRouter. Without an
OPENROUTER_API_KEY every call degrades to a local deterministic mock so the whole
pipeline and UI stay demoable with zero credentials.
"""
from __future__ import annotations

import asyncio
import base64
import logging

from app.domain.services import PAGE_DELIM
from app.infrastructure.config import get_settings

logger = logging.getLogger(__name__)

_PARSE_PROMPT = (
    "Convert this PDF document into clean, well-structured GitHub-flavored Markdown. "
    "Preserve headings, lists, tables and reading order. "
    f"Separate the markdown of each page with this exact delimiter on its own line: {PAGE_DELIM.strip()}"
)
_OCR_PROMPT = (
    "Transcribe this page image into clean GitHub-flavored Markdown. "
    "Preserve headings, lists and tables. Output only the markdown."
)
_SUMMARY_PROMPT = (
    "Write a concise summary (5-8 sentences) of the following document. "
    "Capture the main topics and key points. Return plain prose.\n\n---\n\n"
)


def available() -> bool:
    return bool(get_settings().openrouter_api_key)


def _client():
    from openai import OpenAI  # lazy import so mock mode / tests need no SDK/network

    s = get_settings()
    return OpenAI(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
        default_headers={"HTTP-Referer": s.openrouter_referer, "X-Title": s.openrouter_title},
    )


def _chat_sync(model: str, content: list[dict]) -> str:
    resp = _client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=get_settings().openrouter_max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


async def pdf_to_markdown(raw: bytes) -> str:
    """Full-document markdown (pages separated by PAGE_DELIM) via a PDF-capable model."""
    b64 = base64.b64encode(raw).decode()
    content = [
        {"type": "text", "text": _PARSE_PROMPT},
        {"type": "file", "file": {"filename": "document.pdf",
                                  "file_data": f"data:application/pdf;base64,{b64}"}},
    ]
    return await asyncio.to_thread(_chat_sync, get_settings().openrouter_parse_model, content)


async def ocr_image(png: bytes) -> str:
    """OCR one page image to markdown via a vision model."""
    return await _image_chat(png, get_settings().openrouter_ocr_model)


async def parse_image(png: bytes) -> str:
    """Markdown from one page image via the parse model (fallback when PDF-file input is unavailable)."""
    return await _image_chat(png, get_settings().openrouter_parse_model)


async def _image_chat(png: bytes, model: str) -> str:
    b64 = base64.b64encode(png).decode()
    content = [
        {"type": "text", "text": _OCR_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]
    return await asyncio.to_thread(_chat_sync, model, content)


async def summarize_text(text: str) -> str:
    content = [{"type": "text", "text": _SUMMARY_PROMPT + text}]
    return await asyncio.to_thread(_chat_sync, get_settings().openrouter_summary_model, content)


# ------------------------------------------------------------- mock fallbacks
def mock_markdown_from_text(text: str, page_no: int) -> str:
    body = text.strip() or "_(no extractable text on this page)_"
    return f"# Page {page_no + 1}\n\n{body}"


def mock_summarize(text: str, max_sentences: int = 5) -> str:
    clean = " ".join(text.split())
    if not clean:
        return "No text content was available to summarize."
    sentences: list[str] = []
    buf = ""
    for ch in clean:
        buf += ch
        if ch in ".!?":
            sentences.append(buf.strip())
            buf = ""
            if len(sentences) >= max_sentences:
                break
    if buf.strip() and len(sentences) < max_sentences:
        sentences.append(buf.strip())
    summary = " ".join(sentences)
    return summary[:1200] + ("…" if len(summary) > 1200 else "")


def is_file_input_error(exc: Exception) -> bool:
    """True when the provider rejected native PDF-file input (e.g. minimum-balance rule)."""
    msg = str(exc).lower()
    return "balance for files" in msg or ("file" in msg and "402" in msg)
