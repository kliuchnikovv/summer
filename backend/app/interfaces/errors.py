"""Map domain/application errors to HTTP responses."""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import (
    InvalidPDF,
    InvalidRequest,
    NotFound,
    PageLimitExceeded,
    PayloadTooLarge,
    RateLimited,
    Unauthorized,
)

_STATUS = {
    Unauthorized: status.HTTP_401_UNAUTHORIZED,
    NotFound: status.HTTP_404_NOT_FOUND,
    PayloadTooLarge: status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    PageLimitExceeded: status.HTTP_422_UNPROCESSABLE_ENTITY,
    InvalidPDF: status.HTTP_422_UNPROCESSABLE_ENTITY,
    InvalidRequest: status.HTTP_422_UNPROCESSABLE_ENTITY,
    RateLimited: status.HTTP_429_TOO_MANY_REQUESTS,
}


def register_error_handlers(app: FastAPI) -> None:
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        code = next((c for t, c in _STATUS.items() if isinstance(exc, t)),
                    status.HTTP_500_INTERNAL_SERVER_ERROR)
        headers = {}
        if isinstance(exc, Unauthorized):
            headers["WWW-Authenticate"] = "Bearer"
        if isinstance(exc, RateLimited):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=code, content={"detail": str(exc)}, headers=headers)

    # Register one handler per known domain error type.
    for exc_type in _STATUS:
        app.add_exception_handler(exc_type, handle)
