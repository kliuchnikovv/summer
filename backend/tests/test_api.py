"""End-to-end API tests via httpx ASGITransport (no network, fake Redis)."""
from __future__ import annotations

import httpx
import pytest

from app.infrastructure.config import get_settings
from app.main import app

HEADERS = {"X-API-Key": "demo-key"}


@pytest.fixture
async def client(redis):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_requires_api_key(client, pdf_bytes):
    r = await client.post("/documents", data={"parser": "pypdf"},
                          files={"files": ("a.pdf", pdf_bytes, "application/pdf")})
    assert r.status_code == 401


async def test_invalid_api_key(client, pdf_bytes):
    r = await client.post("/documents", data={"parser": "pypdf"},
                          files={"files": ("a.pdf", pdf_bytes, "application/pdf")},
                          headers={"X-API-Key": "nope"})
    assert r.status_code == 401


async def test_upload_accepted_and_idempotent(client, pdf_bytes):
    r1 = await client.post("/documents", data={"parser": "pypdf"},
                           files={"files": ("a.pdf", pdf_bytes, "application/pdf")}, headers=HEADERS)
    assert r1.status_code == 202, r1.text
    body1 = r1.json()
    doc_id = body1["documents"][0]["id"]
    assert body1["documents"][0]["duplicate"] is False

    r2 = await client.post("/documents", data={"parser": "pypdf"},
                           files={"files": ("a.pdf", pdf_bytes, "application/pdf")}, headers=HEADERS)
    assert r2.status_code == 202
    body2 = r2.json()
    assert body2["documents"][0]["id"] == doc_id  # same id
    assert body2["documents"][0]["duplicate"] is True  # not re-enqueued


async def test_oversized_file_rejected(client, pdf_factory, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "200")  # 200-byte cap
    get_settings.cache_clear()
    big = pdf_factory(2)  # ~550-byte PDF, above the cap
    assert len(big) > 200
    r = await client.post("/documents", data={"parser": "pypdf"},
                          files={"files": ("big.pdf", big, "application/pdf")}, headers=HEADERS)
    assert r.status_code == 413
    get_settings.cache_clear()


async def test_invalid_pdf_rejected(client):
    r = await client.post("/documents", data={"parser": "pypdf"},
                          files={"files": ("x.pdf", b"not a pdf at all", "application/pdf")}, headers=HEADERS)
    assert r.status_code == 422


async def test_ownership_isolation(client, redis, pdf_bytes, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEYS", "k-alice:alice,k-bob:bob")
    get_settings.cache_clear()
    r = await client.post("/documents", data={"parser": "pypdf"},
                          files={"files": ("a.pdf", pdf_bytes, "application/pdf")},
                          headers={"X-API-Key": "k-alice"})
    doc_id = r.json()["documents"][0]["id"]
    # Bob cannot see Alice's document.
    r_bob = await client.get(f"/documents/{doc_id}", headers={"X-API-Key": "k-bob"})
    assert r_bob.status_code == 404
    # Alice can.
    r_alice = await client.get(f"/documents/{doc_id}", headers={"X-API-Key": "k-alice"})
    assert r_alice.status_code == 200
    get_settings.cache_clear()


async def test_list_documents_scoped_and_metadata_only(client, redis, pdf_bytes, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("API_KEYS", "k-alice:alice,k-bob:bob")
    get_settings.cache_clear()
    # Alice uploads two files.
    for name in ("a.pdf", "b.pdf"):
        await client.post("/documents", data={"parser": "pypdf"},
                          files={"files": (name, pdf_bytes + name.encode(), "application/pdf")},
                          headers={"X-API-Key": "k-alice"})
    # Alice sees her two docs; the list carries metadata but no pages/summary fields.
    r = await client.get("/documents", headers={"X-API-Key": "k-alice"})
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 2
    assert {d["filename"] for d in docs} == {"a.pdf", "b.pdf"}
    assert "pages" not in docs[0] and "summary" not in docs[0]  # metadata only
    # Bob sees none of Alice's documents.
    rb = await client.get("/documents", headers={"X-API-Key": "k-bob"})
    assert rb.json() == []
    get_settings.cache_clear()


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["ai_mode"] in ("mock", "real")
