"""Agent #12 — Fraud Detection: flag internal inconsistencies in candidate profiles.

Cross-field reasoning over the full profile — timeline overlaps,
unverifiable credentials, narrative mismatches, template plagiarism.
Never decides fraud occurred, never triggers auto-reject.

ARCHITECTURE-AGENTS.md §3.12
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
PROMPT_VERSION = "fraud-v1"

_SYSTEM = """\
You audit candidate profiles for internal inconsistencies suggestive of \
fabrication. You never decide fraud occurred — you only flag signals for \
human review. Never trigger a rejection.

Return a single JSON object: {"signals": [{"signal_type": str, \
"description": str, "confidence": float, "related_requirement_id": str|null}]}

Rules:
- signal_type: timeline_overlap (overlapping full-time roles), \
unverifiable_credential (no issuer/institution), narrative_mismatch \
(role doesn't match claimed skills), template_plagiarism_suspected
- confidence: 0.0-1.0, how likely this is a genuine concern
- Only flag when evidence supports concern. Do not flag minor formatting issues."""


class FraudInput(BaseModel):
    profile_json: str = ""


class FraudSignal(BaseModel):
    signal_type: str = "timeline_overlap"
    description: str = ""
    confidence: float = 0.0
    related_requirement_id: str | None = None


class FraudOutput(BaseModel):
    signals: list[FraudSignal] = []


@dataclass
class FraudAgent(LLMAgent[FraudInput, FraudOutput]):
    name: ClassVar[str] = "fraud"
    version: ClassVar[str] = "1.0.0"
    prompt_version: ClassVar[str] = PROMPT_VERSION
    pii_tier: ClassVar[str] = "T1"

    chain: FailoverChain

    def build_request(self, payload, ctx):
        prompt = (
            f"Audit this candidate profile for inconsistencies:\n\n"
            f"{payload.profile_json}\n\nReturn the fraud audit as JSON."
        )
        return LLMRequest(prompt=prompt, system=_SYSTEM, pii_tier="T1")

    def parse_response(self, text, payload):
        s = text.find("{"); e = text.rfind("}")
        raw = json.loads(text[s:e + 1] if s >= 0 and e > s else "{}")
        sigs = raw.get("signals") or []
        return FraudOutput(
            signals=[FraudSignal(**f) for f in sigs if isinstance(f, dict)]
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
                           warnings=["Fraud check unavailable this run."])
