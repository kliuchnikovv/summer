"""Use cases for authentication: login, logout, resolve a caller."""
from __future__ import annotations

from app.application.dto import LoginResponse
from app.application.ports import SessionStore
from app.domain.errors import Unauthorized
from app.domain.models import Principal


class AuthService:
    def __init__(self, sessions: SessionStore):
        self._sessions = sessions

    async def login(self, username: str, password: str) -> LoginResponse:
        token, principal, daily_limit = await self._sessions.create(username, password)
        return LoginResponse(token=token, principal=principal, daily_limit=daily_limit)

    async def logout(self, token: str) -> None:
        await self._sessions.destroy(token)

    async def resolve(self, credential: str | None) -> Principal:
        """Resolve a caller from a login session token or an API key."""
        if not credential:
            raise Unauthorized("Missing credentials (login token or API key).")
        principal = await self._sessions.principal_from_token(credential)
        if principal is None:
            principal = self._sessions.principal_from_api_key(credential)
        if principal is None:
            raise Unauthorized("Invalid or expired credentials.")
        return principal
