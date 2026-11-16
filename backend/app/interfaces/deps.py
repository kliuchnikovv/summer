"""Composition root: build adapters + application services, and FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends, Header

from app.application.auth_service import AuthService
from app.application.documents_service import DocumentService
from app.application.processing_service import ProcessingService
from app.domain.models import Principal
from app.infrastructure import openrouter
from app.infrastructure.config import get_settings
from app.infrastructure.parsers.registry import ParserRegistryImpl
from app.infrastructure.pdf import PdfInspectorImpl
from app.infrastructure.queue import RedisStreamQueue
from app.infrastructure.ratelimit import RedisRateLimiter
from app.infrastructure.redis_client import get_redis
from app.infrastructure.repository import RedisDocumentRepository
from app.infrastructure.session_store import RedisSessionStore
from app.infrastructure.summarizer import OpenRouterSummarizer


# --- builders (used by HTTP deps and the worker) ---
def build_document_service() -> DocumentService:
    redis = get_redis()
    s = get_settings()
    return DocumentService(
        RedisDocumentRepository(redis),
        RedisStreamQueue(redis),
        RedisRateLimiter(redis),
        PdfInspectorImpl(),
        gemini_max_pages=s.gemini_max_pages,
        gemini_page_cutoff_enabled=openrouter.available(),
    )


def build_auth_service() -> AuthService:
    return AuthService(RedisSessionStore(get_redis()))


def build_processing_service() -> ProcessingService:
    redis = get_redis()
    return ProcessingService(RedisDocumentRepository(redis), ParserRegistryImpl(), OpenRouterSummarizer())


def build_queue() -> RedisStreamQueue:
    return RedisStreamQueue(get_redis())


# --- FastAPI dependencies ---
def document_service() -> DocumentService:
    return build_document_service()


def auth_service() -> AuthService:
    return build_auth_service()


def _extract_credential(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return authorization.strip()
    return None


async def require_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    auth: AuthService = Depends(auth_service),
) -> Principal:
    return await auth.resolve(_extract_credential(authorization, x_api_key))
