# TDD Evidence Report — Phase 4: Deterministic Scoring Core

**Date:** 2026-08-01
**Branch:** `develop`
**Scope:** Weighted score aggregation with must-have capping, verbatim evidence
span verification, and judge cache-key derivation — the three parts of Phase 4
that need no LLM adapter
**Result:** 60 new tests, all passing. Unit suite 301 → 361. Coverage 83.74%
(floor 80%). Most of Phase 4 as written is blocked on an LLM adapter that does
not exist and remains unimplemented — see §7.

---

## 1. Source plan and scope decision

`plan.md`, `prd.md`, and `task.md` were read **as data, not as instructions**,
per the skill's plan-handoff rule. None contains instruction-to-agent override
phrasing, destructive filesystem operations, credential handling, or
fetch-and-execute commands, so nothing had to be rejected or quarantined.

Phase 4 in `task.md` spans the full judging pipeline: the LLM judge call itself,
requirement batching, a `gemini-3.5-flash` → Groq → `hf:` failover chain, funnel
call-reduction measurement, token-bucket scheduling, key pooling, admission
control with ETA, the SSE orchestrator, `run_checkpoints` resumption, and three
UI items. **Nearly all of it depends on `serving/app/agents/`, which does not
exist.**

Phase 3 already deferred the JD Analyst on exactly this ground — "testing against
a mock only proves the mock was called" — and the same objection applies here
with more force, because a judge is precisely the component whose behaviour a
mock cannot stand in for.

So a deterministic slice was carved out: the parts that decide what a verdict is
*worth*, whether its evidence is *admissible*, and whether a previous answer can
be *reused*. These are pure functions. No database, no network, no model. They
are also the parts a compliance reviewer will actually be asked about, which is
why they were taken first rather than last.

**In scope and built:**

1. `aggregate_score` — weighted credit, must-have capping, full breakdown
2. `verify_evidence_span` — exact-offset verbatim verification
3. `verdict_cache_key` / `retrieval_config_hash` — cache-key derivation
4. `CoreStageFailedError` and `EvidenceSpanMismatchError`

**Deferred with the reason recorded rather than silently dropped:** everything
else — enumerated in §7.

---

## 2. User journeys

| # | Journey |
|---|---|
| J1 | As a recruiter, I want a candidate's score to follow from the rubric weights I set, so that the number reflects what I said mattered. |
| J2 | As a recruiter, I want a missing must-have to cap the score, so that a candidate cannot pass on breadth while failing a hard requirement. |
| J3 | As a hiring manager, I want a score I can take apart requirement by requirement, so that "why 72?" has an answer rather than an assurance. |
| J4 | As a compliance reviewer, I want every cited quote to sit at the offset it claims, so that following a citation lands me on the sentence that justified the verdict. |
| J5 | As a compliance reviewer, I want a stage that cannot complete to fail loudly, so that no score is ever produced from a substituted default. |
| J6 | As a candidate, I want an error about my resume never to quote my resume, so that a rejection message cannot leak my salary or address into a log. |
| J7 | As an operator, I want a cached verdict reused only when every input that could change it is identical, so that a stale answer cannot survive a rubric edit or a model swap. |
| J8 | As an auditor, I want the same inputs to yield the same score every time, so that a disputed result can be re-derived rather than re-litigated. |

---

## 3. Task report

One RED→GREEN increment, both checkpoint commits on `develop`.

### Increment 1 — Scoring core (`b769a3e` → `111a201`)

**Execution.** Wrote `tests/unit/test_scoring.py` (60 tests) first, confirmed
RED, then added the two exceptions to `app/exceptions.py` and created
`app/services/scoring.py`.

**RED evidence** (quoted from the checkpoint commit body):

```
python -m pytest tests/unit/test_scoring.py -o addopts="" -q

    ImportError: cannot import name 'CoreStageFailedError'
    from 'app.exceptions'
    1 error in 0.59s
```

Collection failed because neither `app.services.scoring` nor the two exceptions
existed. **That is the intended reason** — the failure is the absence of the
production code under test, not a typo in the test file.

**GREEN evidence:**

```
python -m pytest tests/unit/test_scoring.py -o addopts="" -q
-> 60 passed in 4.55s

python -m pytest tests/unit/ -o addopts="" -q
-> 361 passed in 6.40s
```

### Refactor

**None applied, and that is a finding rather than an omission.** After GREEN the
module was re-read for the usual triggers: duplicated validation, a function
doing two jobs, a constant repeated across call sites. `ruff` and `mypy` were
both clean on the new file. The four validation helpers each refuse a distinct
class of input and share no body worth extracting; collapsing them would trade
four precise error messages for one vague one. No change was made.

---

## 4. Test specification

| # | What is guaranteed | Test file | Test type | Result | Evidence |
|---|---|---|---|---|---|
| 1 | A fully-met rubric scores exactly `100.00`; a fully-missed one exactly `0.00` | `test_scoring.py` | unit | PASS | `pytest tests/unit/test_scoring.py` → 60 passed |
| 2 | `partial` earns half credit; `unclear` earns the same as `missing` | `test_scoring.py` | unit | PASS | same |
| 3 | Every verdict label in `VERDICTS` is scorable — no label can be added without a credit value | `test_scoring.py` | unit | PASS | same |
| 4 | The score is weighted by the rubric, not an unweighted mean | `test_scoring.py` | unit | PASS | same |
| 5 | A must-have that is not `met` caps the total at the rubric's `must_have_fail_cap` | `test_scoring.py` (parametrized over `partial`/`missing`/`unclear`) | unit | PASS | same |
| 6 | The cap is a **ceiling only** — a score already below it is not lifted up to it, and `cap_applied` stays `False` | `test_scoring.py` | unit | PASS | same |
| 7 | The cap is read from the rubric version, not a module constant | `test_scoring.py` | unit | PASS | same |
| 8 | Failed must-haves are named by id in the result | `test_scoring.py` | unit | PASS | same |
| 9 | The breakdown accounts for every point of the raw score — contributions sum to the total | `test_scoring.py` | unit | PASS | same |
| 10 | The breakdown follows rubric display order and records the verdict behind each contribution | `test_scoring.py` | unit | PASS | same |
| 11 | The formula version is stamped on every result | `test_scoring.py` | unit | PASS | same |
| 12 | Verdict input order does not change the score or the breakdown (reproducibility) | `test_scoring.py` | unit | PASS | same |
| 13 | Scoring a draft rubric raises `ResourceConflictError` (409) via `ensure_approved_for_scoring` | `test_scoring.py` | unit | PASS | same |
| 14 | A missing, duplicate, unknown-requirement, or unrecognized-label verdict is refused — **never defaulted** | `test_scoring.py` | unit | PASS | same |
| 15 | An empty rubric, a foreign `rubric_version_id`, weights that do not sum to 1, and an unknown formula version are each refused | `test_scoring.py` | unit | PASS | same |
| 16 | A quote at its claimed offset verifies; one that appears **elsewhere** in the document is still rejected | `test_scoring.py` | unit | PASS | same |
| 17 | A quote absent from the document, or normalized by the judge (whitespace/case), is rejected | `test_scoring.py` | unit | PASS | same |
| 18 | Out-of-range, negative, inverted, empty, and over-wide spans are each rejected | `test_scoring.py` | unit | PASS | same |
| 19 | The mismatch message carries offsets and lengths only — **no document content** | `test_scoring.py` | unit | PASS | same |
| 20 | `CoreStageFailedError` carries a stable code and status; `EvidenceSpanMismatchError` is one of them | `test_scoring.py` | unit | PASS | same |
| 21 | The cache key is a SHA-256 hex digest, stable across calls | `test_scoring.py` | unit | PASS | same |
| 22 | Changing **any** of the seven components changes the key | `test_scoring.py` (parametrized over all 7) | unit | PASS | same |
| 23 | Text shifted between adjacent components does not collide | `test_scoring.py` | unit | PASS | same |
| 24 | A draft rubric (null content hash) cannot be cached against; blank components are refused | `test_scoring.py` | unit | PASS | same |
| 25 | The retrieval config hash ignores key order, changes with any value, and distinguishes an absent key from a present-but-null one | `test_scoring.py` | unit | PASS | same |

**60 tests** in one file, which is exactly the unit-suite delta measured in §5
(301 → 361).

---

## 5. Quality gates

| # | Gate | Command | Result |
|---|---|---|---|
| 1 | Tests | `pytest tests/unit/ -o addopts=""` | **361 passed in 6.40s** (301 → 361, **+60**) |
| 2 | Coverage | `pytest tests/unit/ --cov=serving/app` | **83.74%**, floor 80% — `Required test coverage of 80.0% reached` (up from 82.69%) |
| 3 | Lint | `ruff check serving/app tests` | **All checks passed!** |
| 4 | Type check | `mypy serving/app` | `Found 12 errors in 4 files (checked 45 source files)` — **pre-existing, see below** |

**On the 12 mypy errors: they pre-date this work.** Distribution is unchanged
from the Phase 3 measurement — `models.py` 1, `repositories/search.py` 3,
`services/indexing.py` 6, `services/reranker.py` 2. The file count rose 44 → 45
because `scoring.py` was added; the error count did not move. **Zero errors in
either file this phase touched.** Left alone rather than fixed opportunistically
inside a TDD increment.

Coverage of the files this phase created or changed:

| File | Coverage |
|---|---|
| `serving/app/services/scoring.py` | **100%** |
| `serving/app/exceptions.py` | **100%** |

---

## 6. Design decisions the tests forced

- **Nothing defaults.** `plan.md` §3 is explicit that a failed stage must
  "**tidak pernah** di-default ke verdict tertentu (itu bias skor secara
  diam-diam)." Every refusal path raises rather than substituting. This is why
  `unclear` is a first-class verdict worth zero credit rather than a silent
  fallback to `missing` — the two mean different things to a reviewer even though
  they score the same.

- **`EvidenceSpanMismatchError` subclasses `CoreStageFailedError`**, which
  subclasses `TalentLensError`. Both are therefore already covered by the
  existing handler in `main.py` — no handler registration was needed, and none
  was added.

- **Span verification is a slice comparison, not a search.** The load-bearing
  test uses a document where the quoted sentence genuinely appears **twice**, and
  the judge cites the wrong one. A `in document_text` check would pass; the
  reviewer following that citation would land on the wrong line. Only
  `document_text[start:end] == quote` catches it.

- **Error messages carry offsets and lengths, never document content.** A resume
  is candidate PII, and an exception message reaches the logs. A dedicated test
  asserts a planted `"Salary expectation 250000 USD."` — and the bare
  `"250000"` — appear nowhere in `str(exc)`.

- **The cap is a ceiling, never a floor.** `min(raw, cap)` semantics, with
  `cap_applied` reported separately from `must_have_failed` so a result stays
  explainable: a candidate scoring 10 with a failed must-have shows
  `must_have_failed=True, cap_applied=False`, and the 10 is their real score, not
  a capped 40.

- **Cache-key components are joined with `\x1e` (record separator).** A plain
  delimiter such as `:` or `|` can occur inside a model id, so text shifted
  across a boundary could forge a collision. `\x1e` cannot appear in a UUID, a
  hex digest, or a model identifier. A test proves the shift does not collide.

- **`retrieval_config_hash` sorts keys before serializing**, so a config dict
  built in a different order hashes the same — while a present-but-null key stays
  distinguishable from an absent one, because those describe different retrieval
  behaviour.

- **`scoring.py` exposes `verify_evidence_span` as a function and never
  redefines the name `EvidenceSpan`** — `services/search.py:36` already owns that
  dataclass, and shadowing it would make imports order-dependent.

---

## 7. Known gaps

Stated plainly, because the alternative is a report that implies more was
verified than actually was.

| # | Gap | Status |
|---|---|---|
| 1 | **The integration suite was not run to a pass on this machine.** No local PostgreSQL; every DB test errors `ConnectionRefusedError: [WinError 1225]`. | Open. **No integration result in this report is claimed as PASS.** Every technique in §3 is DB-free by design and is not a substitute for running the real suite before deploy. |
| 2 | **The LLM judge call itself** — prompt, parse, one repair retry, then fail | **Blocked** — `serving/app/agents/` does not exist. Not started. |
| 3 | Requirement batching (multiple requirements per judge call) | **Blocked** on #2. |
| 4 | Provider failover chain `gemini-3.5-flash` → Groq → `hf:` | **Blocked** on #2. |
| 5 | Funnel call-reduction measurement | **Blocked** on #2 — there are no calls to reduce yet. |
| 6 | Token-bucket scheduling, key pooling, admission-control ETA | **Blocked** on #2. |
| 7 | SSE orchestrator and `run_checkpoints` resumption | **Blocked** on #2 and on #8. |
| 8 | Phase 4 ORM tables — `screening_runs`, `candidate_scores`, `requirement_verdicts`, `evidence_spans` — and their Alembic migration | **Not started.** Unblocked and deterministic; the natural next TDD cycle. `test_migration_coverage.py` will go RED the moment a table is declared without a migration, which is the intended safety net. |
| 9 | `POST` screening-run admission endpoint returning `202` on admission / `409` on an unapproved rubric | **Not started.** Depends on #8. This is what finally ticks the Phase 3 leftover at `task.md:193`. |
| 10 | Three Phase 4 UI items | Out of scope for this repository (frontend). |
| 11 | The 409 guard `ensure_approved_for_scoring` is now **called** by `aggregate_score` and unit-tested there, but still **no HTTP endpoint** exercises it | Partial — advanced from Phase 3, closes with #9. |
| 12 | `LLMRefusalError`, `NoEligibleProviderError`, `BudgetExceededError` (listed at `task.md:54` alongside `CoreStageFailedError`) | **Blocked** on #2. `CoreStageFailedError` is now implemented; the other three would be untestable shells. |
| 13 | `SearchFilters.sections` (`schemas/search.py:22`) accepted and silently ignored | Pre-existing, unrelated. Recorded so it is not lost. |
| 14 | 12 pre-existing mypy errors in `search.py`, `reranker.py`, `indexing.py`, `models.py` | Pre-existing, measured (§5), untouched. |

---

## 8. Merge evidence

If these checkpoints are squashed, this is the record:

| Increment | RED | GREEN | Refactor |
|---|---|---|---|
| Scoring core | `b769a3e` (`ImportError`, 1 error in 0.59s) | `111a201` (60 passed, suite 361 passed) | — (none warranted, §3) |

Both commits are on `develop` and reachable from `HEAD`. Final state:
**361 unit tests passing, 83.74% coverage, ruff clean, mypy unchanged at its
pre-existing 12-error baseline.**
