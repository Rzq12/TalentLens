"""Agent #6 — ATS Scoring: deterministic keyword/format compliance.

Reports whether a resume would pass naive ATS keyword filtering.
Explicitly NOT a fitness assessment — never blended into overall_score.
Pure regex/fuzzy matching, no LLM.

ARCHITECTURE-AGENTS.md §3.6, §4 — ATS sidecar, never merged with verdict.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel

from app.agents.agent import AgentContext, AgentResult, DeterministicAgent


class FormatIssue(BaseModel):
    """One layout/format problem detected."""

    issue: str
    severity: str = "warning"


class LayoutFlags(BaseModel):
    """Structural flags from CV Parser's page layout."""

    has_tables: bool = False
    has_text_boxes: bool = False
    has_multi_column: bool = False
    has_standard_headings: bool = True
    has_contact_block: bool = True


class AtsScoringInput(BaseModel):
    """Input for ATS Scoring agent."""

    resume_text: str = ""
    layout_flags: LayoutFlags = LayoutFlags()
    jd_keywords: list[str] = []


class AtsComplianceReport(BaseModel):
    """ATS keyword/format compliance output — sidecar, never scored."""

    resume_version_id: uuid.UUID | None = None
    keyword_coverage: float = 0.0
    matched_keywords: list[str] = []
    missing_keywords: list[str] = []
    format_flags: list[FormatIssue] = []
    compliance_score: float = 0.0
    is_ats_safe: bool = True


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class AtsScoringAgent(DeterministicAgent[AtsScoringInput, AtsComplianceReport]):
    """Keyword/format compliance check — not a candidate fitness signal."""

    name: ClassVar[str] = "ats_scoring"
    version: ClassVar[str] = "1.0.0"

    async def run(
        self, payload: AtsScoringInput, ctx: AgentContext
    ) -> AgentResult[AtsComplianceReport]:
        """Score ATS compliance deterministically.

        Returns ok always — an empty keyword list yields honest 0.0 coverage,
        not an error. Never blocks a run.
        """
        text_lower = payload.resume_text.lower()

        # Keyword matching
        matched: list[str] = []
        missing: list[str] = []
        for kw in payload.jd_keywords:
            if kw.lower() in text_lower:
                matched.append(kw)
            else:
                missing.append(kw)

        total = len(payload.jd_keywords)
        coverage = len(matched) / total if total > 0 else 0.0

        # Format checks
        flags: list[FormatIssue] = []
        lf = payload.layout_flags
        if lf.has_tables:
            flags.append(FormatIssue(issue="tables_detected", severity="warning"))
        if lf.has_multi_column:
            flags.append(FormatIssue(issue="multi_column_layout", severity="warning"))
        if not lf.has_standard_headings:
            flags.append(FormatIssue(issue="missing_standard_headings", severity="error"))
        if not lf.has_contact_block:
            flags.append(FormatIssue(issue="missing_contact_block", severity="error"))

        # Compliance: safe if >=70% keyword coverage and no format errors
        has_errors = any(f.severity == "error" for f in flags)
        is_safe = coverage >= 0.70 and not has_errors
        compliance = coverage * 0.6 + (0.4 if not has_errors else 0.0)

        output = AtsComplianceReport(
            keyword_coverage=coverage,
            matched_keywords=matched,
            missing_keywords=missing,
            format_flags=flags,
            compliance_score=round(compliance, 2),
            is_ats_safe=is_safe,
        )

        return AgentResult(
            status="ok",
            output=output,
            agent_name=self.name,
            agent_version=self.version,
        )
