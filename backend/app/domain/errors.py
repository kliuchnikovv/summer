"""Domain and application errors.

These are framework-agnostic; the HTTP layer maps them to status codes, and the worker
maps them to failed-document outcomes. The domain never raises HTTP exceptions.
"""
from __future__ import annotations


class DomainError(Exception):
    """Base for all domain/application errors."""


# --- document / parsing ---
class InvalidPDF(DomainError):
    """The uploaded bytes are not a readable PDF (-> 422)."""


class ParserError(DomainError):
    """A parser could not process the document (-> failed document)."""


class PageLimitExceeded(ParserError):
    """Document has more pages than the provider allows (-> 422 at upload)."""


# --- use-case / request errors (mapped to HTTP in the interface layer) ---
class Unauthorized(DomainError):
    """Missing or invalid credentials (-> 401)."""


class NotFound(DomainError):
    """Resource does not exist or is not visible to the caller (-> 404)."""


class InvalidRequest(DomainError):
    """Bad input the caller must fix (-> 422)."""


class PayloadTooLarge(DomainError):
    """Upload exceeds the configured size cap (-> 413)."""


class RateLimited(DomainError):
    """A per-principal limit was exceeded (-> 429)."""

    def __init__(self, detail: str, retry_after: int):
        super().__init__(detail)
        self.detail = detail
        self.retry_after = retry_after
