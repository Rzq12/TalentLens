"""Agent #8 — Skill Gap: rank requirement gaps from completed verdicts.

Consumes verdicts as ground truth. Does not re-judge. T1, light reasoning
over small structured input — lowest injection surface of any LLM agent.

ARCHITECTURE-AGENTS.md §3.8
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

import structlog
from pydantic import BaseModel

from app.agents.agent import AgentResult, LLMAgent
from app.agents.base import FailoverChain, LLMRequest

logger = structlog.get_logger(__name__)
PROMPT_VERSION = "skill-gap-v1"

_SYSTEM = """\
You analyse skill gaps from candidate verdicts. Given a set of requirement \
verdicts (met/partial/missing/unclear), rank the gaps by severity and suggest \
targeted interview probes for the most significant ones.

Return a single JSON object: {"gaps": [{"requirement_id": str, "severity": str, \
"gap_type": str, "suggested_probe": str|null, "weight": float}]}

Rules:
- severity: critical (must-have missing), high (partial on must-have), \
medium (missing nice-to-have), low (partial nice-to-have)
- gap_type: skill_missing, experience_shortfall, education_gap, certification_gap
- suggested_probe: one concrete interview question that would verify the gap
- Only include requirements with verdict missing or partial
- Order by severity then weight descending"""


class SkillGapInput(BaseModel):
    verdicts_json: str = ""


class SkillGapItem(BaseModel):
    requirement_id: str = ""
    severity: str = "low"
    gap_type: str = "skill_missing"
    suggested_probe: str | None = None
    weight: float = 0.0


class SkillGapOutput(BaseModel):
    gaps: list[SkillGapItem] = []


@dataclass
class SkillGapAgent(LLMAgent[SkillGapInput, SkillGapOutput]):
    name: ClassVar[str] = "skill_gap"
    version: ClassVar[str] = "1.0.0"
    prompt_version: ClassVar[str] = PROMPT_VERSION
    pii_tier: ClassVar[str] = "T1"
    requires: ClassVar[frozenset[str]] = frozenset({"requirement_verdicts"})
    produces: ClassVar[frozenset[str]] = frozenset({"skill_gaps"})

    chain: FailoverChain

    def build_request(self, payload, ctx):
        prompt = f"Analyse gaps from these verdicts:\n\n{payload.verdicts_json}\n\nReturn the gap analysis as JSON."
        return LLMRequest(prompt=prompt, system=_SYSTEM, pii_tier="T1")

    def parse_response(self, text, payload):
        raw = json.loads(self._extract_json(text))
        gaps = raw.get("gaps") or []
        return SkillGapOutput(
            gaps=[SkillGapItem(**g) for g in gaps if isinstance(g, dict)]
        )

    def _extract_json(self, text):
        s = text.find("{")
        e = text.rfind("}")
        if s >= 0 and e > s:
            return text[s:e + 1]
        return "{}"

    async def run(self, payload, ctx):
        request = self.build_request(payload, ctx)
        for attempt in (1, 2):
            try:
                response = await self.chain.generate(request)
                output = self.parse_response(response.text, payload)
                return AgentResult(status="ok", output=output,
                                   agent_name=self.name, agent_version=self.version,
                                   prompt_version=self.prompt_version,
                                   model=response.model, provider=response.provider)
            except Exception:
                if attempt == 1:
                    request = LLMRequest(
                        prompt=f"{request.prompt}\n\nReturn ONLY valid JSON.",
                        system=request.system, pii_tier=request.pii_tier)
                continue
        return AgentResult(status="degraded", agent_name=self.name,
                           agent_version=self.version, prompt_version=self.prompt_version,
                           warnings=["Skill gap analysis unavailable this run."])
