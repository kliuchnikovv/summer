"""Login sessions + per-account daily limit."""
from __future__ import annotations

import httpx
import pytest

from app.infrastructure.config import get_settings
from app.main import app


@pytest.fixture
async def client(redis):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_login_success_and_me(client, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("ACCOUNTS", "tester:test-pass-123:tester:10")
    get_settings.cache_clear()
    r = await client.post("/auth/login", json={"username": "tester", "password": "test-pass-123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["principal"] == "tester"
    assert body["daily_limit"] == 10
    token = body["token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == {"principal": "tester", "daily_limit": 10}
    get_settings.cache_clear()


async def test_login_bad_password(client, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("ACCOUNTS", "tester:test-pass-123:tester:10")
    get_settings.cache_clear()
    r = await client.post("/auth/login", json={"username": "tester", "password": "wrong"})
    assert r.status_code == 401
    get_settings.cache_clear()


async def test_logout_invalidates_token(client, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("ACCOUNTS", "tester:test-pass-123:tester:10")
    get_settings.cache_clear()
    token = (await client.post("/auth/login", json={"username": "tester", "password": "test-pass-123"})).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/auth/me", headers=h)).status_code == 200
    assert (await client.post("/auth/logout", headers=h)).status_code == 200
    assert (await client.get("/auth/me", headers=h)).status_code == 401  # token gone
    get_settings.cache_clear()


async def test_login_brute_force_throttled(client, monkeypatch):
    """Repeated login attempts are rate-limited (429) to blunt brute-forcing."""
    monkeypatch.setenv("ACCOUNTS", "tester:test-pass-123:tester:10")
    monkeypatch.setenv("LOGIN_MAX_PER_MIN", "5")
    get_settings.cache_clear()
    codes = []
    for _ in range(6):
        r = await client.post("/auth/login", json={"username": "tester", "password": "wrong"})
        codes.append(r.status_code)
    assert codes[:5] == [401] * 5   # wrong password
    assert codes[5] == 429          # throttled after the limit
    get_settings.cache_clear()


async def test_account_daily_limit_enforced(client, pdf_factory, monkeypatch):
    """The test account is capped at 10 uploads/day -> 11th is 429."""
    get_settings.cache_clear()
    monkeypatch.setenv("ACCOUNTS", "tester:test-pass-123:tester:10")
    monkeypatch.setenv("MAX_CONCURRENT", "50")  # don't let concurrency mask the daily cap
    get_settings.cache_clear()
    token = (await client.post("/auth/login", json={"username": "tester", "password": "test-pass-123"})).json()["token"]
    h = {"X-API-Key": token}

    statuses = []
    for i in range(11):
        # distinct valid PDFs (different page counts) so idempotency doesn't dedupe
        files = {"files": (f"f{i}.pdf", pdf_factory(i + 1), "application/pdf")}
        r = await client.post("/documents", data={"parser": "pypdf"}, files=files, headers=h)
        statuses.append(r.status_code)

    assert statuses[:10].count(202) == 10  # first 10 accepted
    assert statuses[10] == 429            # 11th over the daily cap
    get_settings.cache_clear()
