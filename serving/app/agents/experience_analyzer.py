"""Agent #4 — Experience Analyzer: structure role history.

Typed façade over shared extraction module.
ARCHITECTURE-AGENTS.md §3.4
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


class ExperienceAnalyzerInput(BaseModel):
    resume_text: str = ""
    resume_version_id: str = ""


class ExtractedRole(BaseModel):
    title: str = ""
    company: str = ""
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    description: str | None = None
    achievements: list[str] = []


class ExperienceAnalysisOutput(BaseModel):
    roles: list[ExtractedRole] = []
    total_experience_months: int | None = None


@dataclass
class ExperienceAnalyzerAgent(
    LLMAgent[ExperienceAnalyzerInput, ExperienceAnalysisOutput]
):
    name: ClassVar[str] = "experience_analyzer"
    version: ClassVar[str] = "1.0.0"
    prompt_version: ClassVar[str] = EXTRACTION_PROMPT_VERSION
    pii_tier: ClassVar[str] = "T2"

    chain: FailoverChain

    def build_request(
        self, payload: ExperienceAnalyzerInput, ctx: AgentContext
    ) -> LLMRequest:
        return build_extraction_request(
            resume_text=payload.resume_text,
            resume_version_id=payload.resume_version_id,
        )

    def parse_response(
        self, text: str, payload: ExperienceAnalyzerInput
    ) -> ExperienceAnalysisOutput:
        raw = parse_extraction_response(text)
        exp_raw = raw.get("experience") or []
        roles = [
            ExtractedRole(
                title=r.get("title", ""),
                company=r.get("company", ""),
                start_date=r.get("start_date"),
                end_date=r.get("end_date"),
                is_current=r.get("is_current", False),
                description=r.get("description"),
                achievements=r.get("achievements") or [],
            )
            for r in exp_raw
        ]
        return ExperienceAnalysisOutput(
            roles=roles,
            total_experience_months=raw.get("total_experience_months"),
        )

    async def run(
        self, payload: ExperienceAnalyzerInput, ctx: AgentContext
    ) -> AgentResult[ExperienceAnalysisOutput]:
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
                logger.warning("exp_extraction_failed", attempt=attempt)
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
                logger.warning("exp_parse_failed", attempt=attempt)
                continue

            logger.info(
                "experience_extraction_complete", role_count=len(output.roles)
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
            warnings=["Experience extraction failed after two attempts."],
        )
