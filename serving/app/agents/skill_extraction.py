"""Agent #3 — Skill Extraction: normalize claimed skills.

Typed façade over shared extraction module. Reads from ProfileExtractionRaw,
does NOT make its own LLM call — request coalescing ensures one T2 call
serves all three extraction agents.

ARCHITECTURE-AGENTS.md §3.3
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


class SkillExtractionInput(BaseModel):
    resume_text: str = ""
    resume_version_id: str = ""


class ExtractedSkill(BaseModel):
    name: str
    category: str = "skill"
    years: float | None = None
    level: str | None = None
    evidenced_in: str | None = None
    quote_span: str | None = None


class SkillExtractionOutput(BaseModel):
    skills: list[ExtractedSkill] = []


@dataclass
class SkillExtractionAgent(LLMAgent[SkillExtractionInput, SkillExtractionOutput]):
    name: ClassVar[str] = "skill_extraction"
    version: ClassVar[str] = "1.0.0"
    prompt_version: ClassVar[str] = EXTRACTION_PROMPT_VERSION
    pii_tier: ClassVar[str] = "T2"

    chain: FailoverChain

    def build_request(
        self, payload: SkillExtractionInput, ctx: AgentContext
    ) -> LLMRequest:
        return build_extraction_request(
            resume_text=payload.resume_text,
            resume_version_id=payload.resume_version_id,
        )

    def parse_response(
        self, text: str, payload: SkillExtractionInput
    ) -> SkillExtractionOutput:
        raw = parse_extraction_response(text)
        skills_raw = raw.get("skills") or []
        skills = [
            ExtractedSkill(
                name=s.get("name", ""),
                category=s.get("category", "skill"),
                years=s.get("years"),
                level=s.get("level"),
                evidenced_in=s.get("evidenced_in"),
                quote_span=s.get("quote_span"),
            )
            for s in skills_raw
        ]
        return SkillExtractionOutput(skills=skills)

    async def run(
        self, payload: SkillExtractionInput, ctx: AgentContext
    ) -> AgentResult[SkillExtractionOutput]:
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
                    prompt=f"{request.prompt}\n\nThe previous answer was invalid. Return ONLY a valid JSON object with the extraction schema.",
                    system=request.system,
                    pii_tier=request.pii_tier,
                )

            try:
                response = await self.chain.generate(request)
            except LLMRefusalError as exc:
                logger.warning("extraction_refused", attempt=attempt)
                return AgentResult(
                    status="failed",
                    agent_name=self.name,
                    agent_version=self.version,
                    prompt_version=self.prompt_version,
                    warnings=[f"Provider refused: {exc}"],
                )
            except (LLMProviderError, NoEligibleProviderError) as exc:
                logger.warning("extraction_provider_failed", attempt=attempt)
                return AgentResult(
                    status="failed",
                    agent_name=self.name,
                    agent_version=self.version,
                    prompt_version=self.prompt_version,
                    warnings=[f"Provider failed: {exc}"],
                )

            try:
                output = self.parse_response(response.text, payload)
            except Exception:
                logger.warning("extraction_parse_failed", attempt=attempt)
                continue

            logger.info("skill_extraction_complete", skill_count=len(output.skills))
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
            warnings=["Extraction returned unparseable answer after two attempts."],
        )
