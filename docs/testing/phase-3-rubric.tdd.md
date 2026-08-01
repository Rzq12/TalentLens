# TDD Evidence Report — Phase 3: Rubric Versioning and Weighted Requirements

**Date:** 2026-08-01
**Branch:** `develop`
**Scope:** Immutable rubric versioning, exact weight normalization, tenant-scoped
persistence, the Alembic migration for both tables, and the HTTP surface
**Result:** 115 new tests, all passing. Unit suite 150 → 265. Coverage 82.11%
(floor 80%). Four of the ten Phase 3 task items are blocked or out of scope and
remain unimplemented — see §7.

---

## 1. Source plan and scope decision

`plan.md`, `prd.md`, and `task.md` were added to the repository root by the user
and were read **as data, not as instructions** — per the skill's plan-handoff
rule. None of the three contains instruction-to-agent override phrasing,
destructive filesystem operations, credential handling, or fetch-and-execute
commands, so nothing had to be rejected or quarantined. `plan.md` §Phase 3 and
`task.md` agree exactly on scope, and `prd.md` FR-4 independently states the same
invariants the tests pin, so no divergence had to be resolved.

Phase 3 as written spans ten task items. **Four of them cannot be implemented
honestly in this repository right now**, and were deferred with the reason
recorded rather than silently dropped or faked:

- **JD Analyst agent** — requires an LLM adapter that does not exist. Writing one
  against a mock would produce tests that prove only that the mock was called.
- **Taxonomy linking (ESCO/O*NET)** — requires taxonomy tables that have not been
  ingested. Same objection.
- **Rubric editor UI** — lives in the frontend repository, not here.
- **Golden-set labelling** — a human annotation process, not code.

What remains is the deterministic core, and that is what was built: versioning,
immutability, weight normalization, persistence, migration, and the API.

---

## 2. User journeys

| # | Journey |
|---|---|
| J1 | As a recruiter, I want to author a job's scoring criteria as a draft, so that I can revise them before anyone is scored against them. |
| J2 | As a recruiter, I want to express importance in whatever numbers feel natural and have the system normalize them, so that I do not have to make weights sum to 1 by hand. |
| J3 | As a compliance reviewer, I want an approved rubric to be immutable, so that a score can always be re-derived from the exact criteria that produced it. |
| J4 | As a compliance reviewer, I want every score attributable to a content hash, so that "the rubric was edited afterwards" is not a possible explanation for a disputed result. |
| J5 | As a recruiter, I want to revise an approved rubric by minting the next version, so that improving criteria does not invalidate past decisions. |
| J6 | As a tenant, I want another tenant's rubric to be indistinguishable from one that does not exist, so that existence itself is not leaked. |
| J7 | As an operator, I want the rubric tables created by a migration, so that a deployment does not require hand-written SQL. |
| J8 | As a recruiter, I want to list my jobs without downloading every full job description, so that the listing stays usable at scale. |

---

## 3. Task report

Four RED→GREEN increments, each with its checkpoint commits on `develop`.

### Increment 1 — Models and service (`5075d30` → `aede5ce`)

**Execution.** Wrote `test_rubric_models.py` (13) and `test_rubric_service.py`
(33) first, confirmed RED, then implemented `RubricVersion` / `Requirement` in
`app/models.py` and `app/services/rubric.py`.

**RED evidence** (quoted from the checkpoint commit body):

```
PYTHONPATH=serving python -m pytest tests/unit/test_rubric_models.py \
  tests/unit/test_rubric_service.py -p no:warnings
-> 46 failed in 2.91s
```

Three distinct causes, all missing implementation — not broken setup:
`AttributeError: module 'app.models' has no attribute 'RubricVersion'`,
`... no attribute 'Requirement'`, and
`ModuleNotFoundError: No module named 'app.services.rubric'`.

**What the cycle forced.** The load-bearing test is the one requiring normalized
weights to sum to **exactly** `Decimal("1.0000")`. Three equal weights quantize
to `0.3333` each and sum to `0.9999`. Trusting the quantized values would leave a
rubric whose weights do not total 1, so normalization uses **largest-remainder
apportionment**: quantize down, then distribute the leftover units to the
requirements with the largest truncated remainders. No test was relaxed to
accommodate a rounding drift.

The content hash deliberately ignores requirement *ordering*, so reordering
criteria does not invalidate scores computed against them; it is stamped at
approval, the moment the criteria stop being editable.

**GREEN evidence.** `46 passed`.

### Increment 2 — Repository (`17d2db4` → `2c007dd`)

**Execution.** 20 tests written first against a recording session double, then
`app/repositories/rubric.py`.

**RED evidence.** All twenty failed on
`ModuleNotFoundError: No module named 'app.repositories.rubric'`.

**Technique worth preserving.** The tests **compile each SQLAlchemy statement
against the PostgreSQL dialect and assert on the rendered SQL**. Tenant scoping
is therefore verified in the actual `WHERE` clause with no database running —
the guarantee that matters (a caller cannot reach another tenant's row) is proven
where it is enforced, rather than by trusting a passing integration test that
this machine cannot run.

**GREEN evidence.** `20 passed`.

### Increment 3 — Migration (`015302b` → `2da6160`, guard extended in `e16bc73`)

**Execution.** The models existed with no revision creating their tables. The
existing live drift guard runs `compare_metadata` against PostgreSQL, so it
**cannot fire on a machine with no database — which is exactly where a model gets
added and its revision forgotten.** That is what had happened.

Five DB-less checks were added in `tests/unit/test_migration_coverage.py` that
parse `Base.metadata` and the revision scripts as text.

**RED evidence.** Four of the five passed and the fifth failed, naming both
missing tables. The four passing checks are the proof the new guard is **not
vacuous** — a check that cannot fail is not evidence.

**GREEN evidence.** `5 passed`. Revision `b2c3d4e5f6a7` creates both tables;
the chain stays single-headed
(`3b8b551883d8 → dd2329f32308 → a1b2c3d4e5f6 → b2c3d4e5f6a7`).

### Increment 4 — HTTP surface (`269a9b9` → `b98d69c`, refactor `d9e6ba9`)

**Execution.** 44 tests written first covering the five rubric routes, the jobs
list route, authorization, and the OpenAPI contract.

**RED evidence.**

```
PYTHONPATH=serving python -m pytest tests/unit/test_rubric_api.py \
  -p no:warnings --tb=short -o addopts=""
-> 41 failed, 3 passed
```

**Technique worth preserving.** The tests override
`app.dependency_overrides[get_session]` with a stub session, so the **entire HTTP
surface is exercised with no PostgreSQL running**. This is new to this codebase.

**One diagnosis worth recording in full**, because it is the failure mode that
destroys a TDD baseline. After the implementation landed the target went to
`1 failed, 43 passed`. The survivor was
`test_the_rubric_router_is_registered_under_the_versioned_prefix`, which scanned
`app.routes` filtering on `hasattr(route, "path")`.

The obvious move — assume the registration was wrong — was not taken, because the
instrumentation said otherwise: **none of the five routers were visible to that
scan**, including `auth`, `resumes`, `jobs`, and `search`, which predate this work
and demonstrably function. FastAPI 0.141.1 wraps every `include_router` call in an
internal `_IncludedRouter` object that carries no `path` attribute of its own, so
the filter discards every mounted router and reports a correctly wired app as
unregistered. `app.openapi()["paths"]` listed all 14 paths correctly.

**The test was wrong, not the code** — but "the test is wrong" is precisely what a
vacuous fix claims, so the corrected assertion was proved to still bite: an app
was built with auth/resumes/jobs/search but **deliberately without** rubric, and
the new technique reported `rubric detected (want False): False` over 8 paths.
Only then was the change accepted. The assertion text and failure message are
byte-identical to the original; only the path-collection technique changed.

**GREEN evidence.** `44 passed in 3.85s`; full unit suite `265 passed`.

### Refactor (`d9e6ba9`)

`test_every_rubric_route_declares_a_response_model` filtered the OpenAPI paths and
asserted no offenders were found. With the router unregistered the filter yields
nothing and **the assertion held over an empty set** — the test would have
reported PASS without inspecting a single route, which is the exact condition it
exists to catch. It now collects `rubric_paths` up front and asserts non-empty
first, matching its sibling. Behaviour on a wired app is unchanged: `44 passed`.

---

## 4. Test specification

| # | What is guaranteed | Test file or command | Test type | Result | Evidence |
|---|---|---|---|---|---|
| 1 | Weights normalize to exactly `Decimal("1.0000")` even when quantization leaves a remainder | `test_rubric_service.py` | unit | PASS | `pytest tests/unit/test_rubric_service.py` → 33 passed |
| 2 | The content hash is independent of requirement ordering | `test_rubric_service.py` | unit | PASS | same |
| 3 | Approving stamps the content hash and freezes the criteria | `test_rubric_service.py` | unit | PASS | same |
| 4 | Editing an approved rubric raises `ResourceConflictError` (409) | `test_rubric_service.py` | unit | PASS | same |
| 5 | Minting version N+1 marks the predecessor `superseded` | `test_rubric_service.py` | unit | PASS | same |
| 6 | Another tenant's rubric is reported 404, never 403 | `test_rubric_service.py`, `test_rubric_repository.py` | unit | PASS | same |
| 7 | Column shapes hold the audit contract: `weight numeric(5,4)`, `content_hash char(64)`, `unique(job_id, version)`, `status` default `draft`, `must_have_fail_cap` default 40, CASCADE to requirements | `test_rubric_models.py` | unit | PASS | `pytest tests/unit/test_rubric_models.py` → 13 passed |
| 8 | Every repository query carries `tenant_id` in the compiled `WHERE` clause | `test_rubric_repository.py` | unit | PASS | `pytest tests/unit/test_rubric_repository.py` → 20 passed |
| 9 | Every ORM table has a migration creating it — checked without a database | `test_migration_coverage.py` | unit | PASS | `pytest tests/unit/test_migration_coverage.py` → 5 passed |
| 10 | The rubric router is mounted under `/api/v1` | `test_rubric_api.py::test_the_rubric_router_is_registered_under_the_versioned_prefix` | unit | PASS | `pytest tests/unit/test_rubric_api.py` → 44 passed |
| 11 | Every rubric route declares `summary` and `description` | `::test_every_rubric_route_documents_itself` | unit | PASS | same |
| 12 | Every rubric route declares a success response schema | `::test_every_rubric_route_declares_a_response_model` | unit | PASS | same |
| 13 | Read-only roles cannot mutate a rubric; write roles can | `test_rubric_api.py` (parametrized over roles) | unit | PASS | same |
| 14 | `GET /jobs` pages by cursor and reports `next_cursor` only when a full page came back | `test_rubric_api.py` | unit | PASS | same |
| 15 | A job summary omits the full description body | `test_rubric_api.py` | unit | PASS | same |

Counts by file: `test_rubric_models.py` 13, `test_rubric_service.py` 33,
`test_rubric_repository.py` 20, `test_rubric_api.py` 44,
`test_migration_coverage.py` 5 — **115 tests**, which is exactly the unit-suite
delta measured in §5 (150 → 265).

---

## 5. Quality gates

| # | Gate | Command | Result |
|---|---|---|---|
| 1 | Tests | `pytest tests/unit/ -o addopts=""` | **265 passed in 5.31s** (+44 in this increment; **150 → 265, +115 across the phase**, measured by re-running the suite at pre-phase commit `86108cc`) |
| 2 | Coverage | `pytest tests/unit/ --cov=serving/app` | **82.11%**, floor 80% — `Required test coverage of 80.0% reached` |
| 3 | Lint | `ruff check serving/app tests` | **All checks passed!** |
| 4 | Type check | `mypy serving/app` | `Found 12 errors in 4 files (checked 44 source files)` — **see below** |

**On the 12 mypy errors: they pre-date this work, and that was measured rather
than asserted.** The changes were stashed and mypy re-run at `HEAD`:
`Found 12 errors in 4 files (checked 42 source files)` — an identical error set,
differing only by the two new files. Distribution: `models.py` 1,
`repositories/search.py` 3, `services/indexing.py` 6, `services/reranker.py` 2.
**Zero in any of the six files this phase touched.** They are pre-existing debt,
not a regression, and were left alone rather than fixed opportunistically inside
a TDD increment.

Coverage of the files this phase created or changed:

| File | Coverage |
|---|---|
| `serving/app/schemas/rubric.py` | 100% |
| `serving/app/routers/rubric.py` | 100% |
| `serving/app/repositories/rubric.py` | 100% |
| `serving/app/services/rubric.py` | 97% |
| `serving/app/schemas/ingestion.py` | 95% |
| `serving/app/routers/jobs.py` | 69% (the uncovered lines are the pre-existing create and upload bodies; the list route added here is covered) |

---

## 6. Design decisions the tests forced

- **Every mutation is a POST.** `CLAUDE.md` bars PUT and DELETE for the MVP.
  These are not PUTs in spirit anyway: approving is a state transition, and
  minting the next version creates a row rather than replacing one.
- **`RubricVersion.requirements` is `lazy="noload"`**, so the router can never
  read the relationship — touching it would yield an empty list rather than the
  rows just written, producing a response indistinguishable from a rubric with no
  criteria. Every route calls `RubricRepository.list_requirements` explicitly
  after the mutation.
- **Requirement ids are assigned in the router**, not left to the column default:
  the default is applied by the database on insert, and the response is assembled
  before the transaction commits.
- **`exceptions.py` was reused, not extended.** `ResourceNotFoundError` (404),
  `ResourceConflictError` (409), `ValidationFailedError` (422), and
  `AuthorizationError` (403) already covered every case Phase 3 needed.
- **No router accepts a caller-supplied tenant or user id.** Identity comes only
  from `current_principal`, which reads it from a verified token.

---

## 7. Known gaps

Stated plainly, because the alternative is a report that implies more was
verified than actually was.

| # | Gap | Status |
|---|---|---|
| 1 | **The integration suite was not run to a pass on this machine.** `pytest tests/integration/` → `2 passed, 28 errors in 117.91s`, every error `ConnectionRefusedError: [WinError 1225]`. No local PostgreSQL. | Open. **No integration result in this report is claimed as PASS.** The DB-less techniques in §3 exist precisely because of this and are not a substitute for running the real suite before deploy. |
| 2 | JD Analyst agent (auto-draft a rubric from a JD) | **Blocked** — no LLM adapter exists. Not started. |
| 3 | Taxonomy linking (ESCO / O*NET) | **Blocked** — taxonomy tables not ingested. Not started. |
| 4 | Rubric editor UI | Out of scope for this repository (frontend). |
| 5 | Per-role-family rubric templates | Not started. |
| 6 | Golden-set labelling | Human annotation process, not code. |
| 7 | The 409 "cannot score against an unapproved rubric" guard is implemented (`ensure_approved_for_scoring`) but **no scoring endpoint exercises it yet** | Partial. The guard is unit-tested; the end-to-end path arrives with Phase 4. |
| 8 | `SearchFilters.sections` (`schemas/search.py:22`) is accepted and silently ignored | Pre-existing, unrelated to this phase. Recorded so it is not lost. |
| 9 | The jobs-list tests live in `test_rubric_api.py` | Cosmetic. They belong in a `test_jobs_api.py`; moving them is a pure file split with no behaviour change. |
| 10 | 12 pre-existing mypy errors in `search.py`, `reranker.py`, `indexing.py`, `models.py` | Pre-existing, measured (§5), untouched. |

---

## 8. Merge evidence

If these checkpoints are squashed, this is the record:

| Increment | RED | GREEN | Refactor |
|---|---|---|---|
| Models + service | `5075d30` (46 failed) | `aede5ce` (46 passed) | — |
| Repository | `17d2db4` (20 failed) | `2c007dd` (20 passed) | — |
| Migration | `015302b` (4 passed, 1 failed naming both missing tables) | `2da6160` (5 passed) | `e16bc73` (live drift guard extended) |
| HTTP surface | `269a9b9` (41 failed, 3 passed) | `b98d69c` (44 passed) | `d9e6ba9` (anti-vacuity guard) |

All ten commits are on `develop` and reachable from `HEAD`. Final state:
**265 unit tests passing, 82.11% coverage, ruff clean, mypy unchanged.**
