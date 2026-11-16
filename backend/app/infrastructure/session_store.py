"""Redis-backed SessionStore: login tokens + API-key resolution."""
from __future__ import annotations

import secrets

import redis.asyncio as aioredis

from app.domain.errors import Unauthorized
from app.domain.models import Principal
from app.infrastructure.config import get_settings


def _session_key(token: str) -> str:
    return f"session:{token}"


class RedisSessionStore:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    async def create(self, username: str, password: str) -> tuple[str, str, int]:
        settings = get_settings()
        account = settings.account_map().get(username)
        if not account or not secrets.compare_digest(account["password"], password):
            raise Unauthorized("Invalid username or password.")
        principal = account["principal"]
        daily_limit = account["daily_limit"] if account["daily_limit"] is not None else settings.daily_limit
        token = secrets.token_urlsafe(32)
        await self.redis.hset(_session_key(token), mapping={
            "principal": principal, "username": username, "daily_limit": str(daily_limit),
        })
        await self.redis.expire(_session_key(token), settings.session_ttl_seconds)
        return token, principal, daily_limit

    async def destroy(self, token: str) -> None:
        await self.redis.delete(_session_key(token))

    async def principal_from_token(self, token: str) -> Principal | None:
        data = await self.redis.hgetall(_session_key(token))
        if not data:
            return None
        dl = data.get("daily_limit")
        return Principal(id=data["principal"], credential=token,
                         daily_limit=int(dl) if dl and dl.isdigit() else None)

    def principal_from_api_key(self, key: str) -> Principal | None:
        principal_id = get_settings().api_key_map().get(key)
        if not principal_id:
            return None
        return Principal(id=principal_id, credential=key, daily_limit=None)
