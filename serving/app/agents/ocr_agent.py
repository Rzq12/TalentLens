"""Agent #2 — OCR: Tesseract-based text extraction for scanned documents.

Wraps pytesseract as a DeterministicAgent. Invoked only when CV Parser's
needs_ocr flag is set. Renders page images via PyMuPDF, runs Tesseract,
returns word-level confidence and bounding boxes for evidence anchoring.

ARCHITECTURE-AGENTS.md §3.2 — heuristic, not LLM, CPU-bound via ProcessPool.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import BaseModel

from app.agents.agent import AgentContext, AgentResult, DeterministicAgent
from app.logging import get_logger

logger = get_logger(__name__)


class WordBox(BaseModel):
    text: str = ""
    confidence: float = 0.0
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class PageOcrResult(BaseModel):
    page: int = 0
    text: str = ""
    confidence: float = 0.0
    word_boxes: list[WordBox] = []


class OcrInput(BaseModel):
    document_id: uuid.UUID
    page_images: list[bytes] = []
    dpi: int = 300
    language: str = "eng+ind"


class OcrOutput(BaseModel):
    text_by_page: list[PageOcrResult] = []
    mean_confidence: float = 0.0
    parse_status: Literal["ok", "low_confidence", "failed"] = "ok"


@dataclass
class OcrAgent(DeterministicAgent[OcrInput, OcrOutput]):
    name: ClassVar[str] = "ocr"
    version: ClassVar[str] = "1.0.0"

    async def run(self, payload: OcrInput, ctx: AgentContext) -> AgentResult[OcrOutput]:
        try:
            import io

            import pytesseract
            from PIL import Image
        except ImportError:
            return AgentResult(
                status="failed",
                agent_name=self.name,
                agent_version=self.version,
                warnings=["pytesseract or PIL not installed"],
            )

        results: list[PageOcrResult] = []
        for i, img_bytes in enumerate(payload.page_images):
            loop = asyncio.get_running_loop()
            page_result = await loop.run_in_executor(
                None,
                self._ocr_page,
                img_bytes,
                payload.language,
            )
            page_result.page = i + 1
            results.append(page_result)

        confidences = [r.confidence for r in results if r.confidence > 0]
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
        status: Literal["ok", "low_confidence", "failed"] = (
            "ok" if mean_conf >= 0.6 else "low_confidence"
        )

        return AgentResult(
            status="ok",
            output=OcrOutput(
                text_by_page=results,
                mean_confidence=round(mean_conf, 2),
                parse_status=status,
            ),
            agent_name=self.name,
            agent_version=self.version,
        )

    @staticmethod
    def _ocr_page(img_bytes: bytes, language: str) -> PageOcrResult:
        import io

        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(img_bytes))
        data = pytesseract.image_to_data(img, lang=language, output_type="dict")
        text = " ".join(
            w for w in data.get("text", []) if isinstance(w, str) and w.strip()
        )
        confidences = [
            c for c in data.get("conf", []) if isinstance(c, (int, float)) and c > 0
        ]
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

        words = []
        for j in range(len(data.get("text", []))):
            w = data["text"][j]
            if isinstance(w, str) and w.strip():
                words.append(WordBox(
                    text=w,
                    confidence=float(data["conf"][j]) if data["conf"][j] != "-1" else 0.0,
                    x=data["left"][j],
                    y=data["top"][j],
                    width=data["width"][j],
                    height=data["height"][j],
                ))

        return PageOcrResult(
            text=text.strip(),
            confidence=round(mean_conf, 2),
            word_boxes=words,
        )
