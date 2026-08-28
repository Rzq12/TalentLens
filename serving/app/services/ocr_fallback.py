"""Best-effort OCR fallback for PDFs with an insufficient text layer."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Protocol

from app.agents.agent import AgentContext, AgentResult
from app.agents.ocr_agent import OcrInput, OcrOutput
from app.services.parser import PAGE_SEPARATOR, ParsedDocument, ParsedPage


class Ocr(Protocol):
    """Extracts text from rendered document pages."""

    async def run(
        self, payload: OcrInput, ctx: AgentContext
    ) -> AgentResult[OcrOutput]: ...


async def apply_ocr_fallback(
    *,
    parsed: ParsedDocument,
    content: bytes,
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    ocr: Ocr,
    render_pages: Callable[[bytes], list[bytes]] | None = None,
) -> ParsedDocument:
    """Return OCR text for a low-yield PDF, or retain the parser result."""
    if not parsed.needs_ocr or parsed.media_type != "application/pdf":
        return parsed

    renderer = render_pages or _render_pdf_pages
    try:
        page_images = await asyncio.to_thread(renderer, content)
        result = await ocr.run(
            OcrInput(document_id=document_id, page_images=page_images),
            AgentContext(
                request_id=uuid.uuid4(),
                tenant_id=tenant_id,
                pii_tier="T0",
                idempotency_key=f"{document_id}:ocr",
            ),
        )
    except Exception:
        return parsed

    if result.status != "ok" or result.output is None:
        return parsed
    pages = [page.text.strip() for page in result.output.text_by_page]
    if not any(pages):
        return parsed
    return _parsed_ocr_pages(parsed, pages, result.output.parse_status)


def _render_pdf_pages(content: bytes) -> list[bytes]:
    """Render PDF pages at OCR resolution using the existing PyMuPDF dependency."""
    import fitz

    document = fitz.open(stream=content, filetype="pdf")
    try:
        return [
            page.get_pixmap(dpi=300, alpha=False).tobytes("png") for page in document
        ]
    finally:
        document.close()


def _parsed_ocr_pages(
    parsed: ParsedDocument, pages: list[str], status: str
) -> ParsedDocument:
    """Rebuild exact per-page offsets from OCR text."""
    offset = 0
    parsed_pages: list[ParsedPage] = []
    for number, text in enumerate(pages, start=1):
        start = offset
        end = start + len(text)
        parsed_pages.append(ParsedPage(page=number, text=text, start_char=start, end_char=end))
        offset = end + len(PAGE_SEPARATOR)
    return ParsedDocument(
        text=PAGE_SEPARATOR.join(pages),
        pages=tuple(parsed_pages),
        page_count=parsed.page_count,
        media_type=parsed.media_type,
        parser_version=f"{parsed.parser_version}+ocr-1.0.0",
        needs_ocr=status != "ok",
        parse_status="ok" if status == "ok" else "low_yield",
        warnings=parsed.warnings,
        spans=parsed.spans,
        metadata=parsed.metadata,
    )
