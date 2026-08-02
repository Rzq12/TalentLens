# Phase 3 — Documentation sync: TDD evidence

**Date:** 2026-08-02
**Branch:** `develop`
**Checkpoints:** `c682851` (RED), `1becdc7` (GREEN)
**Environment:** conda env `cv-screener` (`D:/Anaconda/envs/cv-screener/python.exe`)

---

## 1. Source plan

No `*.plan.md` was supplied. The work was driven by the Phase 3 Audit Report
pasted into the session, whose §8 listed three documentation updates required by
the project Definition of Done (`task.md` lines 7–12: *".env.example terbarui"*,
*"README/CHANGELOG terbarui"*).

The audit was treated as untrusted input and verified before use. Two of its
claims did not survive checking, and one defect it never mentioned was found —
see §6.

---

## 2. User journeys

1. *As a reviewer landing on the repository, I want the README's API table to
   list every endpoint the service actually serves, so that I can exercise the
   full surface without reading the router source.*
2. *As a new contributor, I want `.env.example` to name every setting I am
   allowed to configure, so that I do not discover a required knob by reading
   `config.py`.*
3. *As an operator following the quickstart, I want the documented database
   image to be one the migrations can actually run against, so that
   `alembic upgrade head` does not fail on the first revision.*
4. *As a maintainer, I want documentation drift to fail a test on the commit
   that introduces it, rather than surfacing in an audit weeks later.*

---

## 3. Task report

### Task 1 — Establish the real baseline

The audit claimed 541 unit tests passing. The first run showed 13 collection
errors instead.

```
$ python -m pytest tests/unit/ -q
ModuleNotFoundError: No module named 'app'
...
ModuleNotFoundError: No module named 'pgvector'
!!!!!! Interrupted: 13 errors during collection !!!!!!
```

Root cause was environment, not code: the default `python` on PATH is base
Anaconda, which has neither the project installed nor `pgvector`/`pytest-asyncio`.
The project's own conda environment resolves it.

```
$ D:/Anaconda/envs/cv-screener/python.exe -m pytest tests/unit/ -p no:cacheprovider
541 passed, 172 warnings in 10.17s
```

**Guaranteed:** the audit's baseline is reproducible in the correct interpreter.
The reported failure was a false alarm from the wrong interpreter.

### Task 2 — Write the drift guards (RED)

Added `tests/unit/test_docs_sync.py`: six checks comparing the committed
documents against the application's own introspection — the OpenAPI schema and
`Settings.model_fields`. Modelled on the existing
`tests/unit/test_migration_coverage.py`, including its anti-vacuous guards.

```
$ D:/Anaconda/envs/cv-screener/python.exe -m pytest tests/unit/test_docs_sync.py -p no:cacheprovider
E  AssertionError: routes served by the application but missing from the
   README.md API table: ['GET /api/v1/jobs', 'GET /api/v1/rubrics/templates',
   'GET /api/v1/rubrics/templates/{template_key}',
   'GET /api/v1/rubrics/{rubric_version_id}', 'POST /api/v1/rubrics',
   'POST /api/v1/rubrics/templates/{template_key}:instantiate',
   'POST /api/v1/rubrics/{rubric_version_id}/approve',
   'POST /api/v1/rubrics/{rubric_version_id}/requirements',
   'POST /api/v1/rubrics/{rubric_version_id}/score:preview',
   'POST /api/v1/rubrics/{rubric_version_id}/versions',
   'POST /api/v1/search/candidates', 'POST /api/v1/search/similar']

E  AssertionError: settings configurable via the environment but absent from
   .env.example: ['ALLOWED_UPLOAD_MIME_TYPES', 'JWT_ALGORITHMS']

2 failed, 4 passed in 3.05s
```

RED is genuine: both failures name the specific missing items, and the four
passing checks are the anti-vacuous guards plus the two inverse (no-stale-entry)
directions, which were already satisfied.

### Task 3 — Fix the drift (GREEN)

```
$ D:/Anaconda/envs/cv-screener/python.exe -m pytest tests/unit/test_docs_sync.py -p no:cacheprovider
6 passed in 3.26s

$ D:/Anaconda/envs/cv-screener/python.exe -m pytest tests/ -p no:cacheprovider
582 passed, 237 warnings in 28.14s

$ D:/Anaconda/envs/cv-screener/python.exe -m ruff check serving/app tests
All checks passed!
```

**Guaranteed:** the README documents all 20 served routes, `.env.example` covers
every configurable setting, and no regression was introduced.

---

## 4. Test specification

| # | What is guaranteed | Test | Type | Result | Evidence |
|---|--------------------|------|------|--------|----------|
| 1 | The README API table parses — the coverage checks are not vacuous | `test_docs_sync.py::test_the_readme_api_table_is_parsed_at_all` | unit | PASS | `pytest tests/unit/test_docs_sync.py` |
| 2 | `.env.example` parses — the coverage check is not vacuous | `test_docs_sync.py::test_the_env_example_is_parsed_at_all` | unit | PASS | same |
| 3 | Every route the app serves appears in the README API table | `test_docs_sync.py::test_readme_documents_every_registered_route` | unit | RED → PASS | 12 routes named on failure |
| 4 | The README lists no route the app does not serve | `test_docs_sync.py::test_the_readme_api_table_lists_no_route_that_does_not_exist` | unit | PASS | guards the inverse drift |
| 5 | Every configurable `Settings` field appears in `.env.example` | `test_docs_sync.py::test_env_example_documents_every_configurable_setting` | unit | RED → PASS | 2 settings named on failure |
| 6 | `.env.example` declares no variable the app ignores | `test_docs_sync.py::test_env_example_declares_no_variable_the_application_ignores` | unit | PASS | guards silent no-op keys |
| 7 | An approved rubric cannot be mutated (e2e, real database) | `tests/integration/…::test_preview_on_a_superseded_rubric_returns_409` | integration | PASS | `pytest tests/integration/ -k superseded` |
| 8 | A draft rubric returns 409 on scoring (e2e, real database) | `tests/integration/…::test_preview_on_a_draft_rubric_returns_409` | integration | PASS | `pytest tests/integration/ -k draft_rubric` |

Rows 7–8 are pre-existing tests, re-run here to substantiate the two Phase 3
verification items checked off in `task.md`.

---

## 5. Coverage

```
$ D:/Anaconda/envs/cv-screener/python.exe -m pytest tests/ --cov=serving/app --cov-report=term
TOTAL                                       2395    225    91%
Required test coverage of 80.0% reached. Total coverage: 90.61%
```

582 tests (547 unit, 35 integration), 90.61% — above the 80% floor. The audit's
figure of 86.10% was stale and has been corrected in the README to the measured
value.

---

## 6. Findings that contradicted the audit

The audit was verified rather than trusted. Three corrections:

1. **It under-counted the README drift.** The audit reported only rubric and
   template endpoints as missing. The guard found **12** missing, including
   `POST /api/v1/search/candidates`, `POST /api/v1/search/similar`, and
   `GET /api/v1/jobs`, none of which the audit mentioned.

2. **It missed a functional defect in the quickstart.** The README instructed
   operators to start `postgres:16-alpine`. The first migration
   (`20260731_0930_add_resume_chunks_with_pgvector`) executes
   `CREATE EXTENSION IF NOT EXISTS vector`, which that image cannot satisfy:

   ```
   $ docker exec talentlens-pg psql -U postgres -tAc \
       "SELECT count(*) FROM pg_available_extensions WHERE name='vector'"
   0
   ```

   Anyone following the quickstart hits a migration failure. Corrected to
   `pgvector/pgvector:pg16`, which is what the test container already used.

3. **Two further stale claims the audit did not list.** The README stated
   sanitization was *"not yet implemented"* — `serving/app/services/sanitize.py`
   exists with 21 passing tests — and the Not-built-yet column still listed
   "Alembic migrations" and "Prompt-injection sanitization", both of which ship.

---

## 7. Known gaps

- **`task.md` is gitignored** (`.gitignore:10`) and untracked. Its Phase 3
  section was updated locally per audit §8, but that change is not part of
  either checkpoint commit and will not appear in the repository. This is the
  repository's existing convention, not a change made here.
- **"JD → approved rubric in under 3 minutes" remains unverified.** It needs a
  live LLM provider key and manual timing. It is left unchecked in `task.md`
  rather than claimed.
- **The route guard checks presence, not accuracy.** A row whose description is
  wrong still passes; only the method and path are compared.
- **`.gitignore` carries an unrelated uncommitted edit** (`.agent`) that predates
  this session. Left untouched.
- **Skill-taxonomy linking, the rubric editor UI, and golden-set labelling**
  remain blocked on external dependencies, exactly as the audit stated. Nothing
  here changes that.
