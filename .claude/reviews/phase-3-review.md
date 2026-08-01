# Code Review: Phase 3 — Rubric Authoring, Versioning, and Weight Normalization

**Reviewed:** 2026-08-01
**Branch:** `develop` (local review — no PR open)
**Range reviewed:** `86108cc..HEAD` (12 commits) plus the uncommitted fix set
**Decision:** APPROVE — qualified, see [Validation Results](#validation-results)

## Summary

Phase 3 delivers immutable rubric versioning with exact weight normalization behind a
POST/GET-only API. The layered structure, tenant scoping, and error taxonomy match project
convention. Review found **eight confirmed defects** — two of them cross-tenant or
availability-relevant — every one of which is now fixed and pinned by a regression test. No
CRITICAL or HIGH severity issue remains on the reviewed surface.

The qualification on the decision is not a finding: the integration suite cannot be executed in
this environment (no local PostgreSQL), so its result is unknown rather than passing.

## Review Scope

| Category | Result |
|---|---|
| Architecture | 1 finding — a router raised its own 404, bypassing the service layer |
| Security | 3 findings — cross-tenant authoring, unthrottled endpoints, unbounded payload |
| Maintainability | Pass — status constants centralized; no magic numbers left inline |
| Performance | 1 finding — the existence probe loaded a full job body |
| Scalability | Folded into the unbounded-payload finding (write amplification) |
| Testing | Pass — 146 rubric tests; all four Phase 3 modules at 100% statement coverage |
| API consistency | 2 findings — response types looser than request types; non-standard 404 |
| Error handling | 1 finding — a concurrent mint surfaced as 500 |
| Logging | Pass — no raw payloads, secrets, or PII logged on any rubric path |
| Type safety | 1 finding — four response fields typed `str`; 0 mypy errors in Phase 3 files |

## Findings

Every finding below was reproduced against the running app before it was fixed, and every fix is
held in place by a named test. "Probe" records what the code did before the change.

### CRITICAL

**C1 — A rubric could be authored against another tenant's job, or against no job at all**
`serving/app/services/rubric.py` · `create_draft_rubric`

`job_id` arrives in the request body and nothing on the path constrained it. The
`rubric_versions.job_id` foreign key only requires the row to reference *a* job, not one the
caller can see, so a tenant could mint `version=1` against a job belonging to someone else.

- Probe: tenant A posting tenant B's `job_id` → `HTTP 201, version=1`.
- Fix: `create_draft_rubric` now calls `rubric_repo.job_exists(principal.tenant_id, job_id)` and
  raises `ResourceNotFoundError("Job not found.")` when it returns `False`. A cross-tenant read
  and a genuinely missing job are reported identically, so the response does not confirm that
  another tenant's job exists.
- Pinned by: `test_create_draft_rubric_rejects_another_tenants_job` (also asserts
  `repo.versions == {}`), `test_create_draft_rubric_rejects_a_job_that_does_not_exist`,
  `test_authoring_against_an_invisible_job_is_a_404`, `test_a_rejected_job_stores_nothing`.

### HIGH

**H1 — The rubric endpoints were entirely unthrottled**
`serving/app/main.py` · `_RATE_LIMITED_PREFIXES`

The tuple listed `/api/v1/resumes`, `/api/v1/jobs`, and `/api/v1/search` but omitted
`/api/v1/rubrics`. Rubric creation writes one row per requirement, so an unthrottled endpoint is
a write-amplification lever against a shared database.

- Probe: 60 rapid POSTs → `429` count of `0`.
- Fix: `/api/v1/rubrics` added to the prefix tuple.
- Pinned by: `test_rubric_authoring_is_rate_limited` (loops `_RATE_LIMIT_REQUESTS + 5` and asserts
  a 429 appears), `test_the_rate_limit_refusal_uses_the_standard_error_envelope`.

**H2 — The requirement list was unbounded**
`serving/app/schemas/rubric.py` · `RubricCreateRequest`, `RequirementReplaceRequest`

Neither request model carried `max_length`. The list drives one INSERT per element plus a sort.

- Probe: 50,000 requirements → `HTTP 201`.
- Fix: `MAX_REQUIREMENTS = 200` applied to both models. The ceiling also keeps the set clear of
  the 10,000 available weight quanta, past which criteria cannot all carry a non-zero normalized
  weight.
- Pinned by: `test_a_requirement_list_beyond_the_ceiling_is_rejected` (422, reads the constant
  from the schema rather than hardcoding 200), `test_a_requirement_list_at_the_ceiling_is_accepted`.

**H3 — Positive weights could normalize to zero and be stored silently**
`serving/app/services/rubric.py` · `normalize_weights`

Largest-remainder apportionment over `WEIGHT_UNITS = 10_000` quanta gives a large-enough set no
units at all. Those criteria would sit in an approved rubric contributing nothing to any score,
with nothing in the response saying so.

- Probe: `normalize_weights([Decimal("1")] * 20_000)` → 10,000 weights at `0.0000`.
- Fix: after flooring, any criterion whose caller-supplied weight was `> 0` but which received
  zero units raises `ValidationFailedError` naming `WEIGHT_QUANTUM` as the smallest representable
  share. A weight given as exactly `0` is left alone — that caller asked for an unscored criterion.
- Pinned by: `test_normalize_weights_rejects_a_positive_weight_too_small_to_store`,
  `test_normalize_weights_rejects_a_set_too_large_to_weight`,
  `test_normalize_weights_allows_a_weight_the_author_set_to_zero`,
  `test_normalize_weights_still_sums_to_one_at_the_representable_limit`
  (`[Decimal("1")] * 10_000` still sums to exactly `Decimal("1.0000")`).

**H4 — The seniority floor accepted arbitrary free text**
`serving/app/schemas/rubric.py` · `RequirementInput.min_seniority`

The field was `str | None`. A floor only means something if both sides read it the same way; free
text lets `"Sr."` and `"senior"` express the same requirement while comparing unequal, which makes
the floor unenforceable downstream.

- Probe: `min_seniority="<script>alert(1)</script>"` → `HTTP 201`.
- Fix: narrowed to `SeniorityLevel`, a nine-member `Literal`.
- Pinned by: `test_a_free_text_seniority_floor_is_rejected`, parametrized over
  `["<script>alert(1)</script>", "Sr.", "very senior", "SENIOR", ""]` → all 422.

### MEDIUM

**M1 — A concurrent mint surfaced as HTTP 500**
`serving/app/repositories/rubric.py` · `add_version`

Two authors minting the same successor simultaneously both pass the in-Python version check; the
loser hits the `uq_rubric_versions_job_version` unique constraint. An `IntegrityError` escaping
the repository is an unhandled 500 — the caller cannot tell a retryable race from a server fault.

- Fix: the flush is wrapped, and a violation of that named constraint becomes
  `ResourceConflictError` (`CONFLICT` / 409) with wording that tells the caller to retry. Any
  other `IntegrityError` is re-raised untouched. The `_violates` helper reads
  `error.orig.constraint_name` where asyncpg provides it and falls back to a substring check for
  drivers that only render the name into the message.
- Pinned by: `test_add_version_maps_a_duplicate_version_to_a_conflict`,
  `test_add_version_reraises_an_unrelated_integrity_error`,
  `test_add_version_recognizes_a_constraint_named_only_in_the_message`.

**M2 — Response types were looser than the request types that produce them**
`serving/app/schemas/rubric.py` · `RequirementResponse`, `RubricResponse`

`min_seniority`, `category`, `status`, and `source` were published as `str`. That tells a client
the fields are arbitrary text and leaves it unable to branch exhaustively, even though nothing can
store anything else: the columns are only ever written from a validated `RequirementInput`, and
the copy made by minting a successor carries values that already passed that check.

- Fix: narrowed to `SeniorityLevel`, `RequirementCategory`, `RubricStatus`, and `RubricSource`.
- Pinned by: `test_the_seniority_floor_reads_the_same_on_the_way_in_and_out`,
  `test_the_documented_rubric_status_matches_what_the_service_can_set` (ties the published
  `RubricStatus` literal to the `EDITABLE_STATUS` / `APPROVED_STATUS` / `SUPERSEDED_STATUS`
  constants the service actually assigns, so the two cannot drift).

**M3 — The read endpoint raised its own 404, bypassing the service layer**
`serving/app/routers/rubric.py` · `read_rubric`

The router queried the repository directly and raised a bare `ResourceNotFoundError` with its own
wording. Two problems: it violated `routers/ → services/ → repositories/`, and a cross-tenant read
was worded differently from every other path that reports the same condition.

- Fix: added `read_rubric` to the service layer and delegated to it. The import of
  `ResourceNotFoundError` is gone from the router.
- Pinned by: `test_read_rubric_words_a_missing_rubric_the_same_way_every_path_does` (asserts
  `str(read_error.value) == str(approve_error.value)`),
  `test_a_missing_rubric_answers_with_the_standard_error_envelope`.

**M4 — The existence check loaded a full job body**
`serving/app/repositories/rubric.py` · `job_exists`

The natural implementation of the C1 fix would `select(Job)`, pulling `description_raw` — a full
text column nothing on this path reads — on every rubric creation.

- Fix: `job_exists` selects `literal(1)` with `.select_from(Job)` and `.limit(1)`.
- Pinned by: `test_job_exists_does_not_load_the_job_body` (asserts `"description_raw" not in sql`
  and `"limit" in sql`), plus three behavioural `job_exists` tests.

### LOW

None outstanding. Two conventions were checked and deliberately left alone, as both are
project-wide patterns rather than Phase 3 defects:

- No router anywhere in the project declares `responses=` for its error codes.
- Routers instantiate `RubricRepository(session)` inline rather than through `Depends()` —
  `jobs.py:136,172` and `resumes.py:104,150` do the same.

## Validation Results

Run with the project interpreter, `/d/Anaconda/envs/cv-screener/python.exe` (pytest 9.1.1). The
default `python` on PATH is a different environment without `structlog` and cannot collect this
suite.

| Check | Command | Result |
|---|---|---|
| Tests (unit) | `-m pytest tests/unit/ -o addopts="" -q -p no:warnings` | **Pass** — 301 passed in 6.94s |
| Lint | `-m ruff check serving/app tests` | **Pass** — All checks passed! |
| Type check | `-m mypy serving/app` | **Pass for Phase 3** — Found 12 errors in 4 files (checked 44 source files); zero in Phase 3 files |
| Coverage | `-m pytest tests/unit/ --cov=serving/app --cov-report=term` | **Pass** — total 82.69%, threshold 80.0% |
| Tests (integration) | `-m pytest tests/integration/` | **Skipped — could not be executed.** No local PostgreSQL; every DB test errors with `ConnectionRefusedError: [WinError 1225]`. Not reported as passing. |

**4 of 5 checks passed; 1 could not be executed.**

The 12 mypy errors are the unchanged pre-existing baseline outside Phase 3 —
`serving/app/models.py` (1), `repositories/search.py` (3), `services/indexing.py` (6),
`services/reranker.py` (2). The count is identical before and after this change set.

Per-module coverage for the reviewed surface:

| Module | Statements | Missed | Coverage |
|---|---|---|---|
| `serving/app/repositories/rubric.py` | 40 | 0 | **100%** |
| `serving/app/routers/rubric.py` | 45 | 0 | **100%** |
| `serving/app/schemas/rubric.py` | 52 | 0 | **100%** |
| `serving/app/services/rubric.py` | 115 | 0 | **100%** |

Rubric test counts (`--collect-only -q | grep -c "::"`):

| File | Before | After |
|---|---|---|
| `tests/unit/test_rubric_service.py` | 33 | **47** |
| `tests/unit/test_rubric_repository.py` | 20 | **27** |
| `tests/unit/test_rubric_api.py` | 43 | **59** |
| `tests/unit/test_rubric_models.py` | 13 | **13** |
| Total | 109 | **146** (+37) |

## Files Reviewed

Source (all Modified):

| File | Δ | Change |
|---|---|---|
| `serving/app/main.py` | +7/-1 | Rubric prefix added to the rate-limit tuple (H1) |
| `serving/app/repositories/rubric.py` | +66 | `job_exists` probe (M4); `IntegrityError` → 409 (M1) |
| `serving/app/routers/rubric.py` | +10/-6 | Read delegated to the service layer (M3) |
| `serving/app/schemas/rubric.py` | +39 | `MAX_REQUIREMENTS` (H2); `SeniorityLevel` (H4); response narrowing (M2) |
| `serving/app/services/rubric.py` | +59 | Job-existence check (C1); weight-starvation guard (H3); `read_rubric` (M3) |

Tests (all Modified):

| File | Δ |
|---|---|
| `tests/unit/test_rubric_api.py` | +227 |
| `tests/unit/test_rubric_repository.py` | +153 |
| `tests/unit/test_rubric_service.py` | +345/-23 |

Totals: **8 files, 876 insertions, 30 deletions.**

Read in full for context, not modified: `serving/app/security.py`,
`serving/app/exceptions.py`, `tests/conftest.py`, `tests/unit/test_rubric_models.py`.

## Known Gaps

- **Integration suite unverified here.** `tests/integration/` needs a live PostgreSQL with
  pgvector. It must be run in CI or against a local instance before this reaches an environment
  that matters.
- **12 pre-existing mypy errors** outside Phase 3 (search, indexing, reranker, models). Out of
  scope for this review; unchanged by it.
- **`SearchFilters.sections`** (`serving/app/schemas/search.py:22`) is accepted and silently
  ignored. Pre-existing, outside Phase 3.
- **Test placement.** The jobs-list tests currently live in `tests/unit/test_rubric_api.py` and
  belong in `tests/unit/test_jobs_api.py`. Cosmetic; no behaviour affected.
