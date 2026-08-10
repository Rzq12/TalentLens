"""Agent #13 — Hiring Recommendation: synthesize score, verdicts, gaps, flags
into an advisory recommendation.

Purely advisory — never auto-executes. Human records actual decision.
T1, low volume, most consequential output.

ARCHITECTURE-AGENTS.md §3.13
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
PROMPT_VERSION = "recommend-v1"

_SYSTEM = """\
You make hiring recommendations based on structured candidate assessment data. \
Your recommendation is purely advisory — a human makes every advance/reject \
decision and your output must state this explicitly.

Return a single JSON object: {"recommendation": str, "narrative": str, \
"confidence": float, "uncertainties": [str]}

Rules:
- recommendation: strong_advance (clear fit, evidence strong), advance \
(good fit, minor gaps), hold (too close to call, need more info), \
not_a_fit (significant gaps or fraud flags)
- narrative: 2-3 sentences summarising the assessment and key factors
- confidence: 0.0-1.0, how confident you are in this recommendation
- uncertainties: list specific things you are unsure about
- If fraud signals are present, state them clearly in the narrative
- If bias flags exist, note that the underlying assessment may be affected"""


class RecommendInput(BaseModel):
    score_json: str = ""
    verdicts_json: str = ""
    gaps_json: str = "[]"
    fraud_signals_json: str = "[]"
    bias_findings_json: str = "[]"


class RecommendOutput(BaseModel):
    recommendation: str = "hold"
    narrative: str = ""
    confidence: float = 0.0
    uncertainties: list[str] = []


@dataclass
class RecommendAgent(LLMAgent[RecommendInput, RecommendOutput]):
    name: ClassVar[str] = "recommendation"
    version: ClassVar[str] = "1.0.0"
    prompt_version: ClassVar[str] = PROMPT_VERSION
    pii_tier: ClassVar[str] = "T1"

    chain: FailoverChain

    def build_request(self, payload, ctx):
        prompt = (
            f"Make a hiring recommendation.\n\nScore: {payload.score_json}\n"
            f"Verdicts: {payload.verdicts_json}\nGaps: {payload.gaps_json}\n"
            f"Fraud signals: {payload.fraud_signals_json}\n"
            f"Bias findings: {payload.bias_findings_json}\n\n"
            "Return the recommendation as JSON."
        )
        return LLMRequest(prompt=prompt, system=_SYSTEM, pii_tier="T1")

    def parse_response(self, text, payload):
        s = text.find("{"); e = text.rfind("}")
        raw = json.loads(text[s:e + 1] if s >= 0 and e > s else "{}")
        return RecommendOutput(
            recommendation=raw.get("recommendation", "hold"),
            narrative=raw.get("narrative", ""),
            confidence=float(raw.get("confidence", 0)),
            uncertainties=raw.get("uncertainties") or [],
        )

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
                           warnings=["Recommendation unavailable this run."])
