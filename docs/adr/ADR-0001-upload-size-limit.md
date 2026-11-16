# ADR-0001 — Cap PDF uploads at 20 MB (+ Gemini page cutoff) and store raw bytes in Redis

**Status:** Accepted · **Date:** 2026-11-15

## Context

The service accepts arbitrary user PDFs, which can be very large. Unbounded uploads threaten four
things:

- **API memory** if the request body is buffered whole.
- **Redis memory**, since we stage raw bytes and per-page markdown there.
- **Worker latency/cost** for the AI parsers.
- **Downstream provider limits** — research into Gemini's document processing shows an inline
  request-size ceiling around **~20 MB** (above which the File API is required) **and** a page
  ceiling of **≤ 1,000 pages per PDF**, independent of bytes.

A `Content-Length` header is attacker-controllable and cannot be trusted. We want the simplest
bound that keeps every parser within Gemini's inline limit and the system stable/demoable within
the assessment scope, without introducing a full object-storage tier.

## Decision

1. **Hard ingest cap of 20 MB per file** (`MAX_UPLOAD_BYTES`, default `20971520`), deliberately
   aligned to **Gemini's ~20 MB inline-request limit** so every accepted upload fits inline and we
   **avoid the File API** (and its upload step + 48 h retention). One global cap for all parsers.
   - The header is only a fast-path (`Content-Length` already over cap → immediate **413**).
   - The **authoritative check is the streaming byte count**: the body is read in chunks and the
     request is **aborted with 413 the moment the real count exceeds the cap** — even if the header
     claimed less. We never buffer or persist more than `cap` bytes; no partial oversized file is
     stored.
2. **Page-count cutoff:** Gemini also caps pages (~1000), independent of bytes. The Gemini path
   reads `page_count` (via PyPDF) **before** the API call and **rejects with 422 if >
   `GEMINI_MAX_PAGES` (default 1000)**. PyPDF itself has no page limit.
3. **Stream** the upload and **process per page**, keeping API and worker memory bounded.
4. Store raw bytes in **Redis with a TTL**; the 20 MB cap keeps the Redis footprint small.

## Consequences

**Positive**
- One simple limit, no File API complexity.
- Predictable, small memory use; early rejection of oversized uploads.
- Honest handling of Gemini's page limit.
- Easy to test; per-page persistence also powers resumability (stage-skip).

**Negative / accepted trade-offs**
- 20 MB rejects some legitimately large PDFs that PyPDF alone could handle — accepted for a
  uniform, Gemini-safe limit.
- Raw bytes in Redis is convenient but not how we'd run at scale.

**Future work (out of scope)**
- Object storage (S3/MinIO) + Gemini File API for a higher cap.
- Chunked/resumable upload (tus); virus scanning.
- Split >1000-page PDFs into sub-jobs; tier-dependent caps.

## Alternatives considered

- **No limit** — rejected: OOM / provider errors.
- **100 MB with a File-API path for Gemini** — rejected: extra complexity and retention handling
  for little assessment value.
- **Per-parser byte caps** — rejected: a file succeeding on one parser but 413-ing on another is
  confusing.

A single 20 MB cap matched to Gemini's inline limit is the simplest correct choice.

## Sources

Gemini limits (verify against official docs before production):

- <https://ai.google.dev/gemini-api/docs/document-processing?hl=en>
- <https://firebase.google.com/docs/vertex-ai/input-file-requirements>
- <https://www.cometapi.com/gemini-api-what-file-sizes--input-methods-are-supported-now/>
