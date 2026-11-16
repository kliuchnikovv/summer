"""PDF helpers (pypdf / PyMuPDF). Implements the PdfInspector port."""
from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.errors import InvalidPDF


def _reader(raw: bytes) -> PdfReader:
    try:
        return PdfReader(io.BytesIO(raw))
    except (PdfReadError, OSError, ValueError) as exc:
        raise InvalidPDF(f"Not a readable PDF: {exc}") from exc


class PdfInspectorImpl:
    """Adapter for the PdfInspector port."""

    def count_pages(self, raw: bytes) -> int:
        return len(_reader(raw).pages)


def count_pages(raw: bytes) -> int:
    return len(_reader(raw).pages)


def extract_text_pages(raw: bytes) -> list[str]:
    """Plain text per page via pypdf."""
    reader = _reader(raw)
    out: list[str] = []
    for page in reader.pages:
        try:
            out.append((page.extract_text() or "").strip())
        except Exception:  # noqa: BLE001 - pypdf can raise many things on odd PDFs
            out.append("")
    return out


def render_pages_png(raw: bytes, dpi: int = 150) -> list[bytes]:
    """Rasterize each page to PNG via PyMuPDF (for OCR / image-based parsing)."""
    import pymupdf

    doc = pymupdf.open(stream=raw, filetype="pdf")
    return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]
