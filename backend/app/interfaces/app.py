"""FastAPI application assembly."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.infrastructure import openrouter
from app.infrastructure.config import get_settings
from app.infrastructure.queue import RedisStreamQueue
from app.infrastructure.redis_client import close_redis, get_redis
from app.interfaces.auth_router import router as auth_router
from app.interfaces.documents_router import router as documents_router
from app.interfaces.errors import register_error_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await RedisStreamQueue(get_redis()).ensure_group()
    yield
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(title="Summer — Async PDF Processing", version="0.2.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    register_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(documents_router)

    @app.get("/health")
    async def health() -> dict:
        redis = get_redis()
        try:
            await redis.ping()
            redis_ok = True
        except Exception:  # noqa: BLE001
            redis_ok = False
        settings = get_settings()
        mode = "real" if openrouter.available() else "mock"
        return {
            "status": "ok" if redis_ok else "degraded",
            "redis": redis_ok,
            "ai_mode": mode,
            "models": {
                "parse": settings.openrouter_parse_model,
                "summary": settings.openrouter_summary_model,
                "ocr": settings.openrouter_ocr_model,
            } if mode == "real" else None,
            "max_upload_bytes": settings.max_upload_bytes,
            "parsers": ["pypdf", "gemini", "openai"],
        }

    return app


app = create_app()
