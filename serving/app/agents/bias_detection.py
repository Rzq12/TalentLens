"""Agent #11 — Bias Detection: audit generated text for biased language.

Checks OTHER agents' output (verdict reasoning, interview questions,
recommendation narrative). Does NOT touch raw resume text. Must use a
different model family than the judge and recommender.

ARCHITECTURE-AGENTS.md §3.11
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
PROMPT_VERSION = "bias-v1"

_SYSTEM = """\
You audit AI-generated recruitment text for biased or stereotyped language. \
Review the provided texts and flag any instances of biased language.

Return a single JSON object: {"findings": [{"source": str, "text_excerpt": str, \
"bias_category": str, "severity": str, "rationale": str}]}

Rules:
- source: which agent produced the text (verdict_reasoning, interview_question, \
recommendation_narrative)
- bias_category: gendered_language, age_proxy, name_ethnicity_proxy, \
appearance_reference, other
- severity: critical, high, medium, low
- Only flag genuine issues. Do not flag neutral descriptions.
- Absence of flags does NOT mean the system is unbiased — state this explicitly."""


class BiasInput(BaseModel):
    generated_texts_json: str = "[]"


class BiasFinding(BaseModel):
    source: str = ""
    text_excerpt: str = ""
    bias_category: str = "other"
    severity: str = "low"
    rationale: str = ""


class BiasOutput(BaseModel):
    findings: list[BiasFinding] = []


@dataclass
class BiasAgent(LLMAgent[BiasInput, BiasOutput]):
    name: ClassVar[str] = "bias"
    version: ClassVar[str] = "1.0.0"
    prompt_version: ClassVar[str] = PROMPT_VERSION
    pii_tier: ClassVar[str] = "T1"

    chain: FailoverChain

    def build_request(self, payload, ctx):
        prompt = (
            f"Audit these generated texts for biased language:\n\n"
            f"{payload.generated_texts_json}\n\nReturn the bias audit as JSON."
        )
        return LLMRequest(prompt=prompt, system=_SYSTEM, pii_tier="T1")

    def parse_response(self, text, payload):
        s = text.find("{"); e = text.rfind("}")
        raw = json.loads(text[s:e + 1] if s >= 0 and e > s else "{}")
        findings = raw.get("findings") or []
        return BiasOutput(
            findings=[BiasFinding(**f) for f in findings if isinstance(f, dict)]
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
                if attempt == 1: continue
        return AgentResult(status="degraded", agent_name=self.name,
                           agent_version=self.version, prompt_version=self.prompt_version,
                           warnings=["Automated bias check unavailable this run."])
