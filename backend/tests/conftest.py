"""Shared fixtures: fake Redis + small valid PDFs."""
from __future__ import annotations

import io

import fakeredis.aioredis
import pytest

from app.infrastructure import redis_client
from app.infrastructure.config import get_settings


@pytest.fixture(autouse=True)
def _force_mock_mode(monkeypatch):
    """Keep tests hermetic: ignore any real OpenRouter key in the environment."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    redis_client._client = client
    yield client
    await client.flushall()
    redis_client._client = None


def _make_pdf(num_pages: int = 2) -> bytes:
    """A valid multi-page PDF (blank pages) via pypdf — reliable page count."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def pdf_bytes() -> bytes:
    return _make_pdf(2)


@pytest.fixture
def pdf_factory():
    return _make_pdf
