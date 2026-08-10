"""Agent #9 — Interview Designer: generate categorized interview questions.

Targets gaps and claims needing verification. Four question categories:
gap_probe, claim_verify, depth, scenario. T1, low volume, quality is
directly user-visible.

ARCHITECTURE-AGENTS.md §3.9
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
PROMPT_VERSION = "interview-v1"

_SYSTEM = """\
You design structured interview questions for hiring managers. Given candidate \
verdicts and gap analysis, generate categorized questions with rationale and \
expected signals.

Return a single JSON object: {"questions": [{"ordinal": int, "question": str, \
"category": str, "targets_requirement_id": str|null, "difficulty": str, \
"rationale": str|null, "expected_signal": str|null, "follow_ups": [str]}]}

Rules:
- category: gap_probe (targets a gap), claim_verify (checks a claimed skill), \
depth (tests depth beyond what resume shows), scenario (hypothetical situation)
- difficulty: easy, medium, hard
- Generate 8-12 questions covering all categories
- Every gap_probe should map to a specific gap
- Every claim_verify should target a "met" verdict with confidence < 0.9"""


class InterviewInput(BaseModel):
    verdicts_json: str = ""
    gaps_json: str = "[]"


class InterviewQuestion(BaseModel):
    ordinal: int = 0
    question: str = ""
    category: str = "gap_probe"
    targets_requirement_id: str | None = None
    difficulty: str = "medium"
    rationale: str | None = None
    expected_signal: str | None = None
    follow_ups: list[str] = []


class InterviewOutput(BaseModel):
    questions: list[InterviewQuestion] = []


@dataclass
class InterviewAgent(LLMAgent[InterviewInput, InterviewOutput]):
    name: ClassVar[str] = "interview"
    version: ClassVar[str] = "1.0.0"
    prompt_version: ClassVar[str] = PROMPT_VERSION
    pii_tier: ClassVar[str] = "T1"

    chain: FailoverChain

    def build_request(self, payload, ctx):
        prompt = (
            f"Design interview questions.\n\nVerdicts:\n{payload.verdicts_json}\n\n"
            f"Gaps:\n{payload.gaps_json}\n\nReturn the interview kit as JSON."
        )
        return LLMRequest(prompt=prompt, system=_SYSTEM, pii_tier="T1")

    def parse_response(self, text, payload):
        s = text.find("{"); e = text.rfind("}")
        raw = json.loads(text[s:e + 1] if s >= 0 and e > s else "{}")
        qs = raw.get("questions") or []
        return InterviewOutput(
            questions=[InterviewQuestion(**q) for q in qs if isinstance(q, dict)]
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
                           warnings=["Interview kit unavailable this run."])
