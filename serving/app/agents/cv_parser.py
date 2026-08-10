"""Agent #1 — CV Parser: deterministic document extraction.

Wraps the existing PyMuPDF/pdfplumber/python-docx extraction pipeline
as a ``DeterministicAgent`` so the orchestrator can invoke it uniformly.

ARCHITECTURE-AGENTS.md §3.1 — not an LLM, exact character offsets.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import BaseModel

from app.agents.agent import AgentContext, AgentResult, DeterministicAgent
from app.exceptions import DocumentParseError, UnsupportedMediaTypeError
from app.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class PageLayout(BaseModel):
    """Layout metadata for one page — per-span positioning data for sanitizer."""

    page: int = 0
    width: float = 0.0
    height: float = 0.0
    spans: list[dict] = []


class CvParseInput(BaseModel):
    """Input for CV Parser agent."""

    document_id: uuid.UUID
    mime_type: str
    content: bytes
    filename_sanitized: str = ""


class CvParseOutput(BaseModel):
    """Output of CV Parser — raw text + layout + OCR flag."""

    text: str = ""
    pages: list[PageLayout] = []
    page_count: int = 0
    parse_status: Literal["ok", "low_yield", "failed"] = "ok"
    parser_version: str = ""
    needs_ocr: bool = False


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class CvParserAgent(DeterministicAgent[CvParseInput, CvParseOutput]):
    """Extract raw text and layout from PDF/DOCX resumes.

    Does NOT: OCR (delegates to #2), sanitize, extract skills/experience.
    These are separate pipeline stages.
    """

    name: ClassVar[str] = "cv_parser"
    version: ClassVar[str] = "1.0.0"

    async def run(
        self, payload: CvParseInput, ctx: AgentContext
    ) -> AgentResult[CvParseOutput]:
        """Parse one resume document into text and layout.

        Try PyMuPDF → pdfplumber → flag needs_ocr. DOCX via python-docx.
        Hard-fails on unparseable documents — never degrades to a
        guessed/partial profile.
        """
        try:
            from app.services.parser import get_parser_version  # noqa: F401 — used below
        except ImportError as exc:
            return AgentResult(
                status="failed",
                agent_name=self.name,
                agent_version=self.version,
                warnings=[f"Parser module unavailable: {exc}"],
            )

        try:
            # Delegate to existing extraction pipeline
            text, page_count = await self._extract(payload)
        except (DocumentParseError, UnsupportedMediaTypeError) as exc:
            return AgentResult(
                status="failed",
                agent_name=self.name,
                agent_version=self.version,
                warnings=[str(exc)],
            )

        needs_ocr = page_count > 0 and len(text.strip()) < 100

        output = CvParseOutput(
            text=text,
            pages=[],
            page_count=page_count,
            parse_status="low_yield" if needs_ocr else "ok",
            parser_version=get_parser_version(),
            needs_ocr=needs_ocr,
        )

        return AgentResult(
            status="ok",
            output=output,
            agent_name=self.name,
            agent_version=self.version,
        )

    async def _extract(self, payload: CvParseInput) -> tuple[str, int]:
        """Run the extraction pipeline. Returns (text, page_count)."""
        import io

        if payload.mime_type == "application/pdf":
            import fitz  # PyMuPDF

            doc = fitz.open(stream=payload.content, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
            page_count = len(doc)
            doc.close()
            return text, page_count

        docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if payload.mime_type == docx_mime:
            from docx import Document

            doc = Document(io.BytesIO(payload.content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text)
            return text, 1

        raise UnsupportedMediaTypeError(
            f"Unsupported document type: {payload.mime_type}"
        )
