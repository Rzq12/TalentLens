"""Agent #5 — Education Analyzer: structure degrees/certifications.

Typed façade over shared extraction module.
ARCHITECTURE-AGENTS.md §3.5
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel

from app.agents.agent import AgentContext, AgentResult, LLMAgent
from app.agents.base import FailoverChain, LLMRequest
from app.agents.extraction import (
    EXTRACTION_PROMPT_VERSION,
    build_extraction_request,
    parse_extraction_response,
)


class EducationAnalyzerInput(BaseModel):
    resume_text: str = ""
    resume_version_id: str = ""


class ExtractedEducation(BaseModel):
    degree: str = ""
    field: str = ""
    institution: str = ""
    start_year: int | None = None
    end_year: int | None = None
    gpa: float | None = None


class ExtractedCertification(BaseModel):
    name: str = ""
    issuer: str = ""
    year: int | None = None
    expiry: int | None = None


class EducationAnalysisOutput(BaseModel):
    education: list[ExtractedEducation] = []
    certifications: list[ExtractedCertification] = []


@dataclass
class EducationAnalyzerAgent(
    LLMAgent[EducationAnalyzerInput, EducationAnalysisOutput]
):
    name: ClassVar[str] = "education_analyzer"
    version: ClassVar[str] = "1.0.0"
    prompt_version: ClassVar[str] = EXTRACTION_PROMPT_VERSION
    pii_tier: ClassVar[str] = "T2"

    chain: FailoverChain

    def build_request(
        self, payload: EducationAnalyzerInput, ctx: AgentContext
    ) -> LLMRequest:
        return build_extraction_request(
            resume_text=payload.resume_text,
            resume_version_id=payload.resume_version_id,
        )

    def parse_response(
        self, text: str, payload: EducationAnalyzerInput
    ) -> EducationAnalysisOutput:
        raw = parse_extraction_response(text)
        edu_raw = raw.get("education") or []
        cert_raw = raw.get("certifications") or []

        education = [
            ExtractedEducation(
                degree=e.get("degree", ""),
                field=e.get("field", ""),
                institution=e.get("institution", ""),
                start_year=e.get("start_year"),
                end_year=e.get("end_year"),
                gpa=e.get("gpa"),
            )
            for e in edu_raw
        ]
        certifications = [
            ExtractedCertification(
                name=c.get("name", ""),
                issuer=c.get("issuer", ""),
                year=c.get("year"),
                expiry=c.get("expiry"),
            )
            for c in cert_raw
        ]
        return EducationAnalysisOutput(
            education=education, certifications=certifications
        )

    async def run(
        self, payload: EducationAnalyzerInput, ctx: AgentContext
    ) -> AgentResult[EducationAnalysisOutput]:
        import structlog

        from app.exceptions import (
            LLMProviderError,
            LLMRefusalError,
            NoEligibleProviderError,
        )

        logger = structlog.get_logger(__name__)
        request = self.build_request(payload, ctx)

        for attempt in (1, 2):
            if attempt == 2:
                request = LLMRequest(
                    prompt=f"{request.prompt}\n\nThe previous answer was invalid. Return ONLY a valid JSON object.",
                    system=request.system,
                    pii_tier=request.pii_tier,
                )

            try:
                response = await self.chain.generate(request)
            except (LLMRefusalError, LLMProviderError, NoEligibleProviderError) as exc:
                logger.warning("edu_extraction_failed", attempt=attempt)
                return AgentResult(
                    status="failed",
                    agent_name=self.name,
                    agent_version=self.version,
                    prompt_version=self.prompt_version,
                    warnings=[str(exc)],
                )

            try:
                output = self.parse_response(response.text, payload)
            except Exception:
                logger.warning("edu_parse_failed", attempt=attempt)
                continue

            logger.info(
                "education_extraction_complete",
                edu_count=len(output.education),
                cert_count=len(output.certifications),
            )
            return AgentResult(
                status="ok",
                output=output,
                agent_name=self.name,
                agent_version=self.version,
                prompt_version=self.prompt_version,
                model=response.model,
                provider=response.provider,
                input_tokens=response.prompt_tokens,
                output_tokens=response.completion_tokens,
            )

        return AgentResult(
            status="failed",
            agent_name=self.name,
            agent_version=self.version,
            prompt_version=self.prompt_version,
            warnings=["Education extraction failed after two attempts."],
        )
