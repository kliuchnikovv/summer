"""Pure domain services: deterministic rules with no I/O."""
from __future__ import annotations

import hashlib
import re

from app.domain.models import TERMINAL_STATUSES, DocStatus, ParserType

# Marker the markdown parser asks the model to put between pages.
PAGE_BREAK_MARKER = "<!--PAGE-BREAK-->"
PAGE_DELIM = f"\n\n{PAGE_BREAK_MARKER}\n\n"

_PAGE_SPLIT_RE = re.compile(r"\s*<!--\s*PAGE-BREAK\s*-->\s*", re.IGNORECASE)


def make_doc_id(content_hash: str, parser: ParserType, principal: str) -> str:
    """Deterministic, per-principal document id.

    Same file + parser + owner -> same id (idempotency within an account), while
    different owners never collide on, or can read, each other's documents.
    """
    return hashlib.sha256(f"{content_hash}:{parser.value}:{principal}".encode()).hexdigest()[:16]


def is_terminal(status: DocStatus) -> bool:
    return status in TERMINAL_STATUSES


def split_pages(markdown: str) -> list[str]:
    """Split a full-document markdown into pages on the page-break marker.

    Tolerant of surrounding whitespace/casing the model may emit; drops empty chunks;
    falls back to a single page when no marker is present.
    """
    chunks = [c.strip() for c in _PAGE_SPLIT_RE.split(markdown)]
    pages = [c for c in chunks if c]
    return pages or [markdown.strip()]
