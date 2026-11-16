"""Domain entities and value objects."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ParserType(str, Enum):
    PYPDF = "pypdf"
    GEMINI = "gemini"
    OPENAI = "openai"  # GPT-5 Mini OCR


class DocStatus(str, Enum):
    QUEUED = "queued"
    PARSING = "parsing"
    PARSED = "parsed"
    SUMMARIZING = "summarizing"
    DONE = "done"
    FAILED = "failed"


TERMINAL_STATUSES = {DocStatus.DONE, DocStatus.FAILED}


class Principal(BaseModel):
    """An authenticated caller (via API key or a login session)."""
    id: str
    credential: str
    daily_limit: int | None = None  # per-account override of the global daily quota


class DocumentState(BaseModel):
    """Document metadata (no page/summary content)."""
    id: str
    principal: str
    parser: ParserType
    filename: str
    status: DocStatus
    content_hash: str
    batch_id: str
    page_count: int | None = None
    error: str | None = None
    created_at: float
    updated_at: float


class DocumentResult(BaseModel):
    """Full document view: metadata + per-page markdown + summary."""
    id: str
    principal: str
    parser: ParserType
    filename: str
    status: DocStatus
    page_count: int | None = None
    error: str | None = None
    pages: list[str] = []
    summary: str | None = None
    created_at: float
    updated_at: float
