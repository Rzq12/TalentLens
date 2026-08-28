"""OCR fallback behavior for scanned PDF resumes."""

from __future__ import annotations

import uuid

import pytest

from app.agents.agent import AgentResult
from app.agents.ocr_agent import OcrOutput, PageOcrResult, _parse_confidence
from app.services.ocr_fallback import apply_ocr_fallback
from app.services.parser import parse_document


class StubOcr:
    """Returns configured OCR output without requiring Tesseract."""

    def __init__(self, result: AgentResult[OcrOutput]) -> None:
        """Store the result to return from the stub."""
        self.result = result
        self.calls = 0

    async def run(self, payload: object, ctx: object) -> AgentResult[OcrOutput]:
        """Return the configured result."""
        self.calls += 1
        return self.result


def test_parse_confidence_accepts_tesseract_string_values() -> None:
    """Tesseract commonly returns confidence as strings, not numeric values."""
    assert _parse_confidence("87.5") == 87.5
    assert _parse_confidence("-1") == 0.0
    assert _parse_confidence("unavailable") == 0.0


@pytest.mark.anyio
async def test_ocr_replaces_low_yield_pdf_text_with_anchored_page_text(
    scanned_pdf_bytes: bytes,
) -> None:
    """OCR output becomes the sanitized/indexed parser payload when available."""
    parsed = parse_document(scanned_pdf_bytes, "application/pdf")
    ocr = StubOcr(
        AgentResult(
            output=OcrOutput(
                text_by_page=[PageOcrResult(page=1, text="Jane Doe\nPython", confidence=0.9)],
                mean_confidence=0.9,
                parse_status="ok",
            )
        )
    )

    result = await apply_ocr_fallback(
        parsed=parsed,
        content=scanned_pdf_bytes,
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        ocr=ocr,
        render_pages=lambda content: [b"rendered-page"],
    )

    assert ocr.calls == 1
    assert result.text == "Jane Doe\nPython"
    assert result.pages[0].start_char == 0
    assert result.pages[0].end_char == len(result.pages[0].text)
    assert result.needs_ocr is False
    assert result.parse_status == "ok"
    assert result.parser_version.endswith("+ocr-1.0.0")


@pytest.mark.anyio
async def test_ocr_failure_retains_original_low_yield_parse(scanned_pdf_bytes: bytes) -> None:
    """Unavailable OCR cannot block intake or invent a parser success."""
    parsed = parse_document(scanned_pdf_bytes, "application/pdf")
    ocr = StubOcr(AgentResult(status="failed"))

    result = await apply_ocr_fallback(
        parsed=parsed,
        content=scanned_pdf_bytes,
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        ocr=ocr,
        render_pages=lambda content: [b"rendered-page"],
    )

    assert ocr.calls == 1
    assert result is parsed
    assert result.text == ""
    assert result.needs_ocr is True
    assert result.parse_status == "low_yield"


@pytest.mark.anyio
async def test_ocr_is_skipped_for_text_bearing_pdf(minimal_pdf_bytes: bytes) -> None:
    """Text-bearing documents must not spend CPU on OCR."""
    parsed = parse_document(minimal_pdf_bytes, "application/pdf")
    ocr = StubOcr(AgentResult(output=OcrOutput()))

    result = await apply_ocr_fallback(
        parsed=parsed,
        content=minimal_pdf_bytes,
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        ocr=ocr,
    )

    assert ocr.calls == 0
    assert result is parsed
