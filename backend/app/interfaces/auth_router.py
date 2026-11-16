"""HTTP routes for authentication: login, logout, whoami."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.application.auth_service import AuthService
from app.application.dto import LoginRequest, LoginResponse
from app.domain.models import Principal
from app.infrastructure.config import get_settings
from app.infrastructure.ratelimit import RedisRateLimiter
from app.infrastructure.redis_client import get_redis
from app.interfaces.deps import auth_service, require_principal

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request, svc: AuthService = Depends(auth_service)) -> LoginResponse:
    # Throttle brute-force attempts by username + client IP before checking the password.
    ip = request.client.host if request.client else "unknown"
    await RedisRateLimiter(get_redis()).check_login(f"{body.username}:{ip}")
    return await svc.login(body.username, body.password)


@router.post("/auth/logout")
async def logout(
    principal: Principal = Depends(require_principal),
    svc: AuthService = Depends(auth_service),
) -> dict:
    await svc.logout(principal.credential)
    return {"ok": True}


@router.get("/auth/me")
async def me(principal: Principal = Depends(require_principal)) -> dict:
    limit = principal.daily_limit if principal.daily_limit is not None else get_settings().daily_limit
    return {"principal": principal.id, "daily_limit": limit}
