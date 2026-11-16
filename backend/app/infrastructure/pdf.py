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


def open_pdf(raw: bytes):
    """Open a PDF for page-by-page rendering (PyMuPDF)."""
    import pymupdf

    return pymupdf.open(stream=raw, filetype="pdf")


def render_page_png(doc, index: int, dpi: int = 150, max_pixels: int | None = None) -> bytes:
    """Rasterize ONE page to PNG, scaling down so width*height stays under max_pixels.

    Rendering one page at a time (not a whole-document list) bounds worker memory, and the
    pixel cap stops a maliciously huge page from exhausting memory regardless of the cap.
    """
    import pymupdf

    page = doc[index]
    scale = dpi / 72.0
    w, h = float(page.rect.width) * scale, float(page.rect.height) * scale
    if max_pixels and w * h > max_pixels > 0:
        scale *= (max_pixels / (w * h)) ** 0.5
    return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png")
