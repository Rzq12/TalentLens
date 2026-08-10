"""Tests for Agent #7 — Semantic Matching (LLM judge)."""

from __future__ import annotations

import json
import uuid

import pytest

from app.agents.agent import AgentContext, OutputParseError
from app.agents.base import FailoverChain, LLMRequest, LLMResponse
from app.agents.semantic_matching import (
    JUDGE_PROMPT_VERSION,
    EvidenceChunk,
    JudgeInput,
    JudgeOutput,
    RubricRequirement,
    SemanticMatchingAgent,
    build_judge_prompt,
    compute_cache_key,
    parse_judge_response,
)

# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def sample_requirements() -> list[RubricRequirement]:
    return [
        RubricRequirement(
            requirement_id=str(uuid.uuid4()),
            index=0,
            text="Python proficiency",
            category="skill",
            is_must_have=True,
            weight=3.0,
        ),
        RubricRequirement(
            requirement_id=str(uuid.uuid4()),
            index=1,
            text="Team leadership experience",
            category="experience",
            is_must_have=False,
            weight=2.0,
            min_years=3,
        ),
    ]


@pytest.fixture
def sample_evidence() -> list[EvidenceChunk]:
    return [
        EvidenceChunk(
            chunk_id=str(uuid.uuid4()),
            content="5 years of Python development at Acme Corp.",
            section="experience",
            page_from=1,
            page_to=1,
            start_char=0,
            end_char=50,
        ),
        EvidenceChunk(
            chunk_id=str(uuid.uuid4()),
            content="Led a team of 4 engineers on a 2-year project.",
            section="experience",
            page_from=1,
            page_to=1,
            start_char=51,
            end_char=100,
        ),
    ]


@pytest.fixture
def sample_input(sample_requirements, sample_evidence) -> JudgeInput:
    return JudgeInput(
        requirements=sample_requirements,
        evidence=sample_evidence,
        resume_version_id=str(uuid.uuid4()),
        rubric_content_hash="abc123",
        job_title="Senior Backend Engineer",
    )


@pytest.fixture
def ctx() -> AgentContext:
    return AgentContext(
        request_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        idempotency_key="test-key",
    )


# --------------------------------------------------------------------------- #
# Prompt assembly                                                              #
# --------------------------------------------------------------------------- #


def test_build_judge_prompt_returns_t1_request(sample_requirements, sample_evidence):
    req = build_judge_prompt(
        requirements=sample_requirements,
        evidence=sample_evidence,
        job_title="Backend Engineer",
    )
    assert isinstance(req, LLMRequest)
    assert req.pii_tier == "T1"
    assert "Backend Engineer" in req.prompt
    assert "Python proficiency" in req.prompt
    assert "5 years of Python" in req.prompt
    assert "MUST-HAVE" in req.prompt
    assert "min 3 years" in req.prompt
    assert req.system is not None and "untrusted" in req.system


def test_build_judge_prompt_closes_evidence_block(sample_requirements, sample_evidence):
    req = build_judge_prompt(
        requirements=sample_requirements,
        evidence=sample_evidence,
        job_title="Engineer",
    )
    assert '<candidate_evidence untrusted="true">' in req.prompt
    assert "</candidate_evidence>" in req.prompt


# --------------------------------------------------------------------------- #
# Cache key                                                                    #
# --------------------------------------------------------------------------- #


def test_cache_key_is_deterministic():
    a = compute_cache_key(
        resume_version_id="v1",
        requirement_ids=["r2", "r1"],
        rubric_content_hash="abc",
    )
    b = compute_cache_key(
        resume_version_id="v1",
        requirement_ids=["r1", "r2"],
        rubric_content_hash="abc",
    )
    assert a == b  # ordering is normalized


def test_cache_key_changes_on_version_drift():
    a = compute_cache_key(
        resume_version_id="v1",
        requirement_ids=["r1"],
        rubric_content_hash="abc",
        judge_prompt_version="v1",
    )
    b = compute_cache_key(
        resume_version_id="v1",
        requirement_ids=["r1"],
        rubric_content_hash="abc",
        judge_prompt_version="v2",
    )
    assert a != b


def test_cache_key_changes_on_rubric_change():
    a = compute_cache_key(
        resume_version_id="v1",
        requirement_ids=["r1"],
        rubric_content_hash="hash-a",
    )
    b = compute_cache_key(
        resume_version_id="v1",
        requirement_ids=["r1"],
        rubric_content_hash="hash-b",
    )
    assert a != b


def test_cache_key_changes_on_resume_version():
    a = compute_cache_key(resume_version_id="v1", requirement_ids=["r1"], rubric_content_hash="abc")
    b = compute_cache_key(resume_version_id="v2", requirement_ids=["r1"], rubric_content_hash="abc")
    assert a != b


# --------------------------------------------------------------------------- #
# Response parsing                                                             #
# --------------------------------------------------------------------------- #


def test_parse_valid_response():
    text = (
        '{"verdicts": ['
        '{"requirement_index": 0, "verdict": "met", "confidence": 0.9, '
        '"reasoning": "Clear Python experience.", "evidence_quote": "5 years of Python", '
        '"years_evidenced": 5.0}, '
        '{"requirement_index": 1, "verdict": "partial", "confidence": 0.6, '
        '"reasoning": "Some leadership.", "evidence_quote": "Led a team", '
        '"years_evidenced": 2.0}'
        "]}"
    )
    result = parse_judge_response(text, expected_count=2)
    assert isinstance(result, JudgeOutput)
    assert len(result.verdicts) == 2
    assert result.verdicts[0].verdict == "met"
    assert result.verdicts[0].confidence == 0.9
    assert result.verdicts[1].verdict == "partial"


def test_parse_response_with_markdown_fence():
    v = (
        '{"verdicts": '
        '[{"requirement_index": 0, "verdict": "met", "confidence": 0.8, '
        '"reasoning": "Ok.", "evidence_quote": null, "years_evidenced": null}]}'
    )
    text = f"```json\n{v}\n```"''
    result = parse_judge_response(text, expected_count=1)
    assert len(result.verdicts) == 1


def test_parse_response_wrong_count_raises_output_parse_error():
    text = (
        '{"verdicts": [{"requirement_index": 0, "verdict": "met", "confidence": 0.8,'
        ' "reasoning": "Ok.", "evidence_quote": null, "years_evidenced": null}]}'
    )
    with pytest.raises(OutputParseError, match="expected 3"):
        parse_judge_response(text, expected_count=3)


def test_parse_response_no_verdicts_raises():
    text = '{"verdicts": "not-a-list"}'
    with pytest.raises(OutputParseError, match="no 'verdicts' list"):
        parse_judge_response(text, expected_count=1)


def test_parse_response_invalid_verdict_value_raises():
    text = (
        '{"verdicts": [{"requirement_index": 0, "verdict": "excellent", "confidence": 0.8,'
        ' "reasoning": "Ok.", "evidence_quote": null, "years_evidenced": null}]}'
    )
    with pytest.raises(OutputParseError):
        parse_judge_response(text, expected_count=1)


def test_parse_response_not_json_raises():
    with pytest.raises(OutputParseError, match="not valid JSON|no JSON object"):
        parse_judge_response("this is not json at all", expected_count=1)


# --------------------------------------------------------------------------- #
# Agent integration                                                            #
# --------------------------------------------------------------------------- #


class _MockProvider:
    """A provider that returns a fixed response."""

    def __init__(self, answer: LLMResponse | None = None) -> None:
        self._answer = answer or LLMResponse(text="{}", model="mock", provider="mock")
        self.name = "mock"
        self.model = "mock-model"
        self.tiers = frozenset({"T0", "T1"})

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return self._answer


def _judge_response_for(reqs: list[RubricRequirement]) -> LLMResponse:
    """Build a valid LLM response matching the given requirements."""
    verdicts = [
        {
            "requirement_index": r.index,
            "verdict": "met",
            "confidence": 0.9,
            "reasoning": "Good match.",
            "evidence_quote": "Some text",
            "years_evidenced": 5.0,
        }
        for r in reqs
    ]
    return LLMResponse(
        text=json.dumps({"verdicts": verdicts}),
        model="mock-model",
        provider="mock",
        prompt_tokens=100,
        completion_tokens=50,
    )


@pytest.mark.asyncio
async def test_agent_run_ok(sample_input, ctx):
    agent = SemanticMatchingAgent(
        chain=FailoverChain(
            providers=[_MockProvider(_judge_response_for(sample_input.requirements))]
        )
    )
    result = await agent.run(sample_input, ctx)
    assert result.status == "ok"
    assert result.agent_name == "semantic_matching"
    assert result.prompt_version == JUDGE_PROMPT_VERSION
    assert result.output is not None
    assert len(result.output.verdicts) == 2


@pytest.mark.asyncio
async def test_agent_run_repair_on_first_parse_failure(sample_input, ctx):

    call_count = [0]

    class _FailingThenOk(_MockProvider):
        async def generate(self, request: LLMRequest) -> LLMResponse:
            call_count[0] += 1
            if call_count[0] == 1:
                return LLMResponse(text="invalid json {{", model="m", provider="p")
            return _judge_response_for(sample_input.requirements)

    agent = SemanticMatchingAgent(chain=FailoverChain(providers=[_FailingThenOk()]))
    result = await agent.run(sample_input, ctx)
    assert result.status == "ok"
    assert call_count[0] == 2  # first failed, repair succeeded
    assert result.output is not None
    assert len(result.output.verdicts) == 2


@pytest.mark.asyncio
async def test_agent_run_fails_after_two_parse_failures(sample_input, ctx):
    class _AlwaysInvalid(_MockProvider):
        async def generate(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(text="still not json {", model="m", provider="p")

    agent = SemanticMatchingAgent(chain=FailoverChain(providers=[_AlwaysInvalid()]))
    result = await agent.run(sample_input, ctx)
    assert result.status == "failed"
    assert result.output is None
    assert any("unparseable" in w for w in result.warnings)
