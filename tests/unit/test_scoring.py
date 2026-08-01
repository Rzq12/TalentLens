"""Unit tests for the deterministic scoring surface.

Three things are covered here, and all three are pure functions: score
aggregation from verdicts, verbatim verification of a cited evidence span, and
derivation of the judge cache key. Nothing in this file touches a database, a
network, or a model — that is the point. The LLM judge that *produces* the
verdicts is out of scope for this phase; what is testable today is everything
that happens to a verdict once it exists.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

import pytest

from app.exceptions import (
    CoreStageFailedError,
    EvidenceSpanMismatchError,
    ResourceConflictError,
    TalentLensError,
)
from app.models import Requirement, RubricVersion
from app.services.rubric import (
    APPROVED_STATUS,
    DEFAULT_AGGREGATION_FORMULA_VERSION,
    DEFAULT_MUST_HAVE_FAIL_CAP,
    EDITABLE_STATUS,
)
from app.services.scoring import (
    SUPPORTED_FORMULA_VERSIONS,
    VERDICT_MET,
    VERDICT_MISSING,
    VERDICT_PARTIAL,
    VERDICT_UNCLEAR,
    VERDICTS,
    Verdict,
    aggregate_score,
    retrieval_config_hash,
    verdict_cache_key,
    verify_evidence_span,
)

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #


def _rubric(
    *,
    must_have_fail_cap: int = DEFAULT_MUST_HAVE_FAIL_CAP,
    formula_version: str = DEFAULT_AGGREGATION_FORMULA_VERSION,
    status: str = APPROVED_STATUS,
) -> RubricVersion:
    """Build an in-memory rubric version.

    Column defaults are applied by the database on insert, so every field the
    aggregator reads is set explicitly here.
    """
    return RubricVersion(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        job_id=uuid.uuid4(),
        version=1,
        status=status,
        source="manual",
        content_hash="a" * 64 if status == APPROVED_STATUS else None,
        must_have_fail_cap=must_have_fail_cap,
        aggregation_formula_version=formula_version,
    )


def _requirement(
    rubric: RubricVersion,
    *,
    weight: str,
    is_must_have: bool = False,
    ordinal: int = 0,
    text: str = "criterion",
) -> Requirement:
    """Build one in-memory requirement belonging to ``rubric``."""
    return Requirement(
        id=uuid.uuid4(),
        tenant_id=rubric.tenant_id,
        rubric_version_id=rubric.id,
        ordinal=ordinal,
        text=text,
        category="skill",
        is_must_have=is_must_have,
        weight=Decimal(weight),
    )


def _verdicts(*pairs: tuple[Requirement, str]) -> list[Verdict]:
    """Pair each requirement with a verdict label."""
    return [Verdict(requirement_id=req.id, verdict=label) for req, label in pairs]


# --------------------------------------------------------------------------- #
# aggregate_score — verdict credit                                             #
# --------------------------------------------------------------------------- #


def test_a_rubric_fully_met_scores_one_hundred():
    rubric = _rubric()
    reqs = [
        _requirement(rubric, weight="0.6000", ordinal=0),
        _requirement(rubric, weight="0.4000", ordinal=1),
    ]

    result = aggregate_score(
        rubric=rubric,
        requirements=reqs,
        verdicts=_verdicts((reqs[0], VERDICT_MET), (reqs[1], VERDICT_MET)),
    )

    assert result.score == Decimal("100.00")
    assert result.must_have_failed is False
    assert result.cap_applied is False


def test_a_rubric_met_nowhere_scores_zero():
    rubric = _rubric()
    reqs = [
        _requirement(rubric, weight="0.5000", ordinal=0),
        _requirement(rubric, weight="0.5000", ordinal=1),
    ]

    result = aggregate_score(
        rubric=rubric,
        requirements=reqs,
        verdicts=_verdicts((reqs[0], VERDICT_MISSING), (reqs[1], VERDICT_MISSING)),
    )

    assert result.score == Decimal("0.00")


def test_a_partial_verdict_earns_half_credit():
    rubric = _rubric()
    req = _requirement(rubric, weight="1.0000")

    result = aggregate_score(
        rubric=rubric, requirements=[req], verdicts=_verdicts((req, VERDICT_PARTIAL))
    )

    assert result.score == Decimal("50.00")


def test_an_unclear_verdict_earns_the_same_as_a_missing_one():
    # A judge that could not tell must not hand out the benefit of the doubt:
    # an unreadable resume would otherwise outscore a readable weak one.
    rubric = _rubric()
    req = _requirement(rubric, weight="1.0000")

    unclear = aggregate_score(
        rubric=rubric, requirements=[req], verdicts=_verdicts((req, VERDICT_UNCLEAR))
    )
    missing = aggregate_score(
        rubric=rubric, requirements=[req], verdicts=_verdicts((req, VERDICT_MISSING))
    )

    assert unclear.score == missing.score == Decimal("0.00")


def test_the_score_is_weighted_by_the_rubric():
    rubric = _rubric()
    heavy = _requirement(rubric, weight="0.7000", ordinal=0)
    light = _requirement(rubric, weight="0.3000", ordinal=1)

    result = aggregate_score(
        rubric=rubric,
        requirements=[heavy, light],
        verdicts=_verdicts((heavy, VERDICT_MET), (light, VERDICT_MISSING)),
    )

    assert result.score == Decimal("70.00")


def test_every_verdict_label_is_scorable():
    # Guards the credit table against drift: adding a verdict to the enum
    # without giving it a credit would otherwise fail only in production.
    rubric = _rubric()
    for label in VERDICTS:
        req = _requirement(rubric, weight="1.0000")
        result = aggregate_score(
            rubric=rubric, requirements=[req], verdicts=_verdicts((req, label))
        )
        assert Decimal("0.00") <= result.score <= Decimal("100.00")


# --------------------------------------------------------------------------- #
# aggregate_score — must-have capping                                          #
# --------------------------------------------------------------------------- #


def test_a_missing_must_have_caps_the_score():
    rubric = _rubric(must_have_fail_cap=40)
    gate = _requirement(rubric, weight="0.1000", is_must_have=True, ordinal=0)
    rest = _requirement(rubric, weight="0.9000", ordinal=1)

    result = aggregate_score(
        rubric=rubric,
        requirements=[gate, rest],
        verdicts=_verdicts((gate, VERDICT_MISSING), (rest, VERDICT_MET)),
    )

    assert result.raw_score == Decimal("90.00")
    assert result.score == Decimal("40.00")
    assert result.must_have_failed is True
    assert result.cap_applied is True


@pytest.mark.parametrize("label", [VERDICT_PARTIAL, VERDICT_MISSING, VERDICT_UNCLEAR])
def test_only_a_met_verdict_satisfies_a_must_have(label: str):
    # Must-haves are binary by design. If partial credit were meaningful for a
    # criterion, it would not have been marked must-have in the first place.
    rubric = _rubric(must_have_fail_cap=40)
    gate = _requirement(rubric, weight="0.1000", is_must_have=True, ordinal=0)
    rest = _requirement(rubric, weight="0.9000", ordinal=1)

    result = aggregate_score(
        rubric=rubric,
        requirements=[gate, rest],
        verdicts=_verdicts((gate, label), (rest, VERDICT_MET)),
    )

    assert result.must_have_failed is True
    assert result.score == Decimal("40.00")


def test_a_met_must_have_leaves_the_score_alone():
    rubric = _rubric(must_have_fail_cap=40)
    gate = _requirement(rubric, weight="0.5000", is_must_have=True, ordinal=0)
    rest = _requirement(rubric, weight="0.5000", ordinal=1)

    result = aggregate_score(
        rubric=rubric,
        requirements=[gate, rest],
        verdicts=_verdicts((gate, VERDICT_MET), (rest, VERDICT_MET)),
    )

    assert result.must_have_failed is False
    assert result.cap_applied is False
    assert result.score == Decimal("100.00")


def test_a_failed_must_have_below_the_cap_is_not_lifted_to_it():
    # The cap is a ceiling, never a floor. A candidate scoring 10 who also
    # fails a must-have must not be promoted to the 40 cap.
    rubric = _rubric(must_have_fail_cap=40)
    gate = _requirement(rubric, weight="0.9000", is_must_have=True, ordinal=0)
    rest = _requirement(rubric, weight="0.1000", ordinal=1)

    result = aggregate_score(
        rubric=rubric,
        requirements=[gate, rest],
        verdicts=_verdicts((gate, VERDICT_MISSING), (rest, VERDICT_MET)),
    )

    assert result.score == Decimal("10.00")
    assert result.must_have_failed is True
    assert result.cap_applied is False


def test_the_cap_is_read_from_the_rubric_version():
    # Stored per version so tightening the cap cannot silently re-rank
    # candidates already scored under the old one.
    lenient = _rubric(must_have_fail_cap=40)
    strict = _rubric(must_have_fail_cap=25)

    scores = []
    for rubric in (lenient, strict):
        gate = _requirement(rubric, weight="0.1000", is_must_have=True, ordinal=0)
        rest = _requirement(rubric, weight="0.9000", ordinal=1)
        scores.append(
            aggregate_score(
                rubric=rubric,
                requirements=[gate, rest],
                verdicts=_verdicts((gate, VERDICT_MISSING), (rest, VERDICT_MET)),
            ).score
        )

    assert scores == [Decimal("40.00"), Decimal("25.00")]


def test_the_failed_must_haves_are_named_in_the_breakdown():
    rubric = _rubric()
    failed = _requirement(rubric, weight="0.3000", is_must_have=True, ordinal=0)
    passed = _requirement(rubric, weight="0.3000", is_must_have=True, ordinal=1)
    other = _requirement(rubric, weight="0.4000", ordinal=2)

    result = aggregate_score(
        rubric=rubric,
        requirements=[failed, passed, other],
        verdicts=_verdicts(
            (failed, VERDICT_MISSING), (passed, VERDICT_MET), (other, VERDICT_MISSING)
        ),
    )

    assert result.failed_must_have_ids == (failed.id,)


# --------------------------------------------------------------------------- #
# aggregate_score — the breakdown                                              #
# --------------------------------------------------------------------------- #


def test_the_breakdown_accounts_for_every_point_of_the_raw_score():
    rubric = _rubric()
    reqs = [
        _requirement(rubric, weight="0.3333", ordinal=0),
        _requirement(rubric, weight="0.3333", ordinal=1),
        _requirement(rubric, weight="0.3334", ordinal=2),
    ]

    result = aggregate_score(
        rubric=rubric,
        requirements=reqs,
        verdicts=_verdicts(
            (reqs[0], VERDICT_MET), (reqs[1], VERDICT_PARTIAL), (reqs[2], VERDICT_MISSING)
        ),
    )

    assert sum(c.points for c in result.contributions) == result.raw_score


def test_the_breakdown_follows_rubric_display_order():
    rubric = _rubric()
    reqs = [
        _requirement(rubric, weight="0.3000", ordinal=0, text="first"),
        _requirement(rubric, weight="0.3000", ordinal=1, text="second"),
        _requirement(rubric, weight="0.4000", ordinal=2, text="third"),
    ]
    shuffled = _verdicts(
        (reqs[2], VERDICT_MET), (reqs[0], VERDICT_MET), (reqs[1], VERDICT_MISSING)
    )

    result = aggregate_score(rubric=rubric, requirements=reqs, verdicts=shuffled)

    assert [c.ordinal for c in result.contributions] == [0, 1, 2]
    assert [c.text for c in result.contributions] == ["first", "second", "third"]


def test_the_breakdown_records_the_verdict_behind_each_contribution():
    rubric = _rubric()
    reqs = [
        _requirement(rubric, weight="0.5000", ordinal=0),
        _requirement(rubric, weight="0.5000", ordinal=1),
    ]

    result = aggregate_score(
        rubric=rubric,
        requirements=reqs,
        verdicts=_verdicts((reqs[0], VERDICT_MET), (reqs[1], VERDICT_UNCLEAR)),
    )

    assert [c.verdict for c in result.contributions] == [VERDICT_MET, VERDICT_UNCLEAR]
    assert [c.weight for c in result.contributions] == [Decimal("0.5000"), Decimal("0.5000")]


def test_the_formula_version_is_recorded_on_the_result():
    rubric = _rubric()
    req = _requirement(rubric, weight="1.0000")

    result = aggregate_score(
        rubric=rubric, requirements=[req], verdicts=_verdicts((req, VERDICT_MET))
    )

    assert result.formula_version == rubric.aggregation_formula_version
    assert result.formula_version in SUPPORTED_FORMULA_VERSIONS


# --------------------------------------------------------------------------- #
# aggregate_score — reproducibility                                            #
# --------------------------------------------------------------------------- #


def test_verdict_order_does_not_change_the_score():
    rubric = _rubric()
    reqs = [
        _requirement(rubric, weight="0.2000", ordinal=0),
        _requirement(rubric, weight="0.3000", ordinal=1),
        _requirement(rubric, weight="0.5000", ordinal=2),
    ]
    pairs = [(reqs[0], VERDICT_MET), (reqs[1], VERDICT_PARTIAL), (reqs[2], VERDICT_MISSING)]

    forward = aggregate_score(rubric=rubric, requirements=reqs, verdicts=_verdicts(*pairs))
    reverse = aggregate_score(
        rubric=rubric, requirements=reqs, verdicts=_verdicts(*reversed(pairs))
    )

    assert forward == reverse


def test_the_same_inputs_produce_an_identical_breakdown():
    rubric = _rubric()
    reqs = [
        _requirement(rubric, weight="0.4000", is_must_have=True, ordinal=0),
        _requirement(rubric, weight="0.6000", ordinal=1),
    ]
    verdicts = _verdicts((reqs[0], VERDICT_PARTIAL), (reqs[1], VERDICT_MET))

    first = aggregate_score(rubric=rubric, requirements=reqs, verdicts=verdicts)
    second = aggregate_score(rubric=rubric, requirements=reqs, verdicts=verdicts)

    assert first == second


# --------------------------------------------------------------------------- #
# aggregate_score — refusals                                                   #
# --------------------------------------------------------------------------- #


def test_scoring_a_draft_rubric_is_refused():
    rubric = _rubric(status=EDITABLE_STATUS)
    req = _requirement(rubric, weight="1.0000")

    with pytest.raises(ResourceConflictError):
        aggregate_score(
            rubric=rubric, requirements=[req], verdicts=_verdicts((req, VERDICT_MET))
        )


def test_a_requirement_without_a_verdict_is_refused():
    rubric = _rubric()
    judged = _requirement(rubric, weight="0.5000", ordinal=0)
    skipped = _requirement(rubric, weight="0.5000", ordinal=1)

    with pytest.raises(CoreStageFailedError) as excinfo:
        aggregate_score(
            rubric=rubric,
            requirements=[judged, skipped],
            verdicts=_verdicts((judged, VERDICT_MET)),
        )

    assert str(skipped.id) in str(excinfo.value)


def test_a_verdict_for_an_unknown_requirement_is_refused():
    rubric = _rubric()
    req = _requirement(rubric, weight="1.0000")
    stray = Verdict(requirement_id=uuid.uuid4(), verdict=VERDICT_MET)

    with pytest.raises(CoreStageFailedError):
        aggregate_score(
            rubric=rubric,
            requirements=[req],
            verdicts=[*_verdicts((req, VERDICT_MET)), stray],
        )


def test_a_duplicate_verdict_is_refused():
    # Last-one-wins would make the score depend on judge response ordering.
    rubric = _rubric()
    req = _requirement(rubric, weight="1.0000")

    with pytest.raises(CoreStageFailedError):
        aggregate_score(
            rubric=rubric,
            requirements=[req],
            verdicts=_verdicts((req, VERDICT_MET), (req, VERDICT_MISSING)),
        )


def test_an_unrecognized_verdict_label_is_refused():
    rubric = _rubric()
    req = _requirement(rubric, weight="1.0000")

    with pytest.raises(CoreStageFailedError):
        aggregate_score(
            rubric=rubric, requirements=[req], verdicts=_verdicts((req, "probably"))
        )


def test_an_empty_rubric_is_refused():
    rubric = _rubric()

    with pytest.raises(CoreStageFailedError):
        aggregate_score(rubric=rubric, requirements=[], verdicts=[])


@pytest.mark.parametrize("weights", [("0.5000", "0.4000"), ("0.6000", "0.5000")])
def test_weights_that_do_not_sum_to_one_are_refused(weights: tuple[str, str]):
    rubric = _rubric()
    reqs = [
        _requirement(rubric, weight=weights[0], ordinal=0),
        _requirement(rubric, weight=weights[1], ordinal=1),
    ]

    with pytest.raises(CoreStageFailedError):
        aggregate_score(
            rubric=rubric,
            requirements=reqs,
            verdicts=_verdicts((reqs[0], VERDICT_MET), (reqs[1], VERDICT_MET)),
        )


def test_requirements_from_another_rubric_version_are_refused():
    # Scoring version 2's verdicts against version 1's weights would produce a
    # number attributable to no rubric at all.
    rubric = _rubric()
    other = _rubric()
    mine = _requirement(rubric, weight="0.5000", ordinal=0)
    theirs = _requirement(other, weight="0.5000", ordinal=1)

    with pytest.raises(CoreStageFailedError):
        aggregate_score(
            rubric=rubric,
            requirements=[mine, theirs],
            verdicts=_verdicts((mine, VERDICT_MET), (theirs, VERDICT_MET)),
        )


def test_an_unknown_formula_version_is_refused():
    # Data written by a newer deployment must not be reinterpreted under an
    # older formula and published as if the two agreed.
    rubric = _rubric(formula_version="v99")
    req = _requirement(rubric, weight="1.0000")

    with pytest.raises(CoreStageFailedError):
        aggregate_score(
            rubric=rubric, requirements=[req], verdicts=_verdicts((req, VERDICT_MET))
        )


# --------------------------------------------------------------------------- #
# Exceptions                                                                   #
# --------------------------------------------------------------------------- #


def test_a_core_stage_failure_carries_a_stable_code_and_status():
    error = CoreStageFailedError()

    assert isinstance(error, TalentLensError)
    assert error.error_code == "CORE_STAGE_FAILED"
    assert error.status_code == 500


def test_an_evidence_span_mismatch_is_a_core_stage_failure():
    error = EvidenceSpanMismatchError()

    assert isinstance(error, CoreStageFailedError)
    assert error.error_code == "EVIDENCE_SPAN_MISMATCH"
    assert error.status_code == 500


# --------------------------------------------------------------------------- #
# verify_evidence_span                                                         #
# --------------------------------------------------------------------------- #

DOCUMENT = "Led the payments team.\nBuilt a Kafka pipeline.\nLed the payments team."


def test_a_quote_at_the_claimed_offset_verifies():
    quote = "Built a Kafka pipeline."
    start = DOCUMENT.index(quote)

    verify_evidence_span(
        document_text=DOCUMENT,
        start_char=start,
        end_char=start + len(quote),
        quoted_text=quote,
    )


def test_a_quote_that_appears_elsewhere_is_still_rejected():
    # The load-bearing case. "Led the payments team." really is in the
    # document, twice — but not at the offset the judge claimed. Accepting it
    # would let a judge cite a span it never actually read.
    quote = "Led the payments team."
    wrong_start = DOCUMENT.index("Built")

    with pytest.raises(EvidenceSpanMismatchError):
        verify_evidence_span(
            document_text=DOCUMENT,
            start_char=wrong_start,
            end_char=wrong_start + len(quote),
            quoted_text=quote,
        )


def test_a_quote_absent_from_the_document_is_rejected():
    with pytest.raises(EvidenceSpanMismatchError):
        verify_evidence_span(
            document_text=DOCUMENT,
            start_char=0,
            end_char=len("Shipped a Rust compiler."),
            quoted_text="Shipped a Rust compiler.",
        )


def test_a_quote_normalized_by_the_judge_is_rejected():
    # "Verbatim" is the whole guarantee. A judge that tidies whitespace is
    # paraphrasing, and a reviewer clicking through to the offset would see
    # something other than what the verdict quoted.
    quote = "Led  the payments team."
    with pytest.raises(EvidenceSpanMismatchError):
        verify_evidence_span(
            document_text=DOCUMENT, start_char=0, end_char=len(quote), quoted_text=quote
        )


def test_a_span_reaching_past_the_end_of_the_document_is_rejected():
    with pytest.raises(EvidenceSpanMismatchError):
        verify_evidence_span(
            document_text=DOCUMENT,
            start_char=len(DOCUMENT) - 3,
            end_char=len(DOCUMENT) + 50,
            quoted_text="team.",
        )


def test_a_negative_offset_is_rejected():
    with pytest.raises(EvidenceSpanMismatchError):
        verify_evidence_span(
            document_text=DOCUMENT, start_char=-5, end_char=10, quoted_text="Led the"
        )


def test_an_inverted_span_is_rejected():
    with pytest.raises(EvidenceSpanMismatchError):
        verify_evidence_span(
            document_text=DOCUMENT, start_char=20, end_char=5, quoted_text="Led the"
        )


def test_an_empty_span_is_rejected():
    # An empty quote trivially "matches" an empty slice at any offset, which
    # would make evidence-free verdicts verifiable.
    with pytest.raises(EvidenceSpanMismatchError):
        verify_evidence_span(
            document_text=DOCUMENT, start_char=4, end_char=4, quoted_text=""
        )


def test_a_span_wider_than_the_quote_is_rejected():
    quote = "Led the"
    with pytest.raises(EvidenceSpanMismatchError):
        verify_evidence_span(
            document_text=DOCUMENT, start_char=0, end_char=len(quote) + 6, quoted_text=quote
        )


def test_the_mismatch_message_does_not_echo_the_document():
    secret = "Salary expectation 250000 USD."
    document = f"Summary line.\n{secret}\n"

    with pytest.raises(EvidenceSpanMismatchError) as excinfo:
        verify_evidence_span(
            document_text=document, start_char=0, end_char=len(secret), quoted_text=secret
        )

    assert secret not in str(excinfo.value)
    assert "250000" not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# verdict_cache_key                                                            #
# --------------------------------------------------------------------------- #


def _key_args() -> dict[str, object]:
    """A complete, valid set of cache-key components."""
    return {
        "resume_version_id": uuid.UUID("44444444-4444-4444-4444-444444444444"),
        "requirement_id": uuid.UUID("55555555-5555-5555-5555-555555555555"),
        "rubric_content_hash": "b" * 64,
        "judge_prompt_version": "judge-v1",
        "judge_model": "gemini-3.5-flash",
        "judge_effort": "low",
        "retrieval_config_hash": "c" * 64,
    }


def test_the_cache_key_is_a_sha256_hex_digest():
    key = verdict_cache_key(**_key_args())

    assert len(key) == len(hashlib.sha256(b"").hexdigest())
    assert set(key) <= set("0123456789abcdef")


def test_the_cache_key_is_stable_across_calls():
    assert verdict_cache_key(**_key_args()) == verdict_cache_key(**_key_args())


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("resume_version_id", uuid.UUID("99999999-9999-9999-9999-999999999999")),
        ("requirement_id", uuid.UUID("88888888-8888-8888-8888-888888888888")),
        ("rubric_content_hash", "d" * 64),
        ("judge_prompt_version", "judge-v2"),
        ("judge_model", "groq/llama-3.3-70b"),
        ("judge_effort", "high"),
        ("retrieval_config_hash", "e" * 64),
    ],
)
def test_changing_any_component_changes_the_cache_key(field: str, replacement: object):
    # Every component is part of the identity of a verdict. A component that
    # did not move the key would let a stale verdict be served after the thing
    # it depended on changed.
    baseline = verdict_cache_key(**_key_args())
    changed = _key_args()
    changed[field] = replacement

    assert verdict_cache_key(**changed) != baseline


def test_text_moved_between_components_does_not_collide():
    # Naive concatenation would hash "judge-v1" + "low" identically to
    # "judge-v" + "1low".
    left = _key_args()
    left["judge_prompt_version"] = "judge-v1"
    left["judge_effort"] = "low"

    right = _key_args()
    right["judge_prompt_version"] = "judge-v"
    right["judge_effort"] = "1low"

    assert verdict_cache_key(**left) != verdict_cache_key(**right)


def test_a_draft_rubric_cannot_be_cached_against():
    # `content_hash` is null until approval. Keying on a null would make every
    # draft edit collide with the verdicts computed before it.
    args = _key_args()
    args["rubric_content_hash"] = None

    with pytest.raises(CoreStageFailedError):
        verdict_cache_key(**args)


@pytest.mark.parametrize("field", ["judge_prompt_version", "judge_model", "judge_effort"])
def test_a_blank_cache_key_component_is_refused(field: str):
    args = _key_args()
    args[field] = ""

    with pytest.raises(CoreStageFailedError):
        verdict_cache_key(**args)


# --------------------------------------------------------------------------- #
# retrieval_config_hash                                                        #
# --------------------------------------------------------------------------- #


def test_the_retrieval_config_hash_ignores_key_order():
    # Two runs configured identically must share a cache, whatever order the
    # settings happened to be assembled in.
    assert retrieval_config_hash({"top_k": 20, "reranker": "bge-m3"}) == retrieval_config_hash(
        {"reranker": "bge-m3", "top_k": 20}
    )


def test_the_retrieval_config_hash_changes_with_any_value():
    baseline = retrieval_config_hash({"top_k": 20, "reranker": "bge-m3"})

    assert retrieval_config_hash({"top_k": 50, "reranker": "bge-m3"}) != baseline
    assert retrieval_config_hash({"top_k": 20, "reranker": "none"}) != baseline


def test_the_retrieval_config_hash_distinguishes_a_missing_key_from_a_null_one():
    assert retrieval_config_hash({"top_k": 20}) != retrieval_config_hash(
        {"top_k": 20, "reranker": None}
    )


def test_the_retrieval_config_hash_is_a_sha256_hex_digest():
    digest = retrieval_config_hash({"top_k": 20})

    assert len(digest) == len(hashlib.sha256(b"").hexdigest())
    assert set(digest) <= set("0123456789abcdef")
