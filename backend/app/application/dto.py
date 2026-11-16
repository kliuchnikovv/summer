"""Application-level request/response DTOs (transport-agnostic)."""
from __future__ import annotations

from pydantic import BaseModel

from app.domain.models import DocStatus


class UploadAccepted(BaseModel):
    id: str
    filename: str
    status: DocStatus
    duplicate: bool = False


class UploadResponse(BaseModel):
    batch_id: str
    documents: list[UploadAccepted]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    principal: str
    daily_limit: int
