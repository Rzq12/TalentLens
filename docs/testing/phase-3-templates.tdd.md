# TDD Evidence — Rubric template catalogue over HTTP

**Task:** Phase 3 open item *"Template rubric per role family"*
**Branch:** `develop`
**Commits:** `7326dc9` (catalogue service), `47deaaf` (HTTP surface)
**Date:** 2026-08-02

## Source

No `*.plan.md` was used. The journeys below derive from the Phase 3 checklist in
`task.md` and from the gap found while auditing it: the catalogue service landed
in `7326dc9` with 33 passing unit tests, but a grep across `serving/app/` proved
nothing imported it. The feature was complete and unreachable.

## User journeys

1. As a recruiter, I want to browse the starter rubrics so I do not have to
   author a rubric from an empty form.
2. As a recruiter, I want to read a template's criteria before committing to it,
   so I can tell whether it is close enough to my role to be worth editing.
3. As a recruiter, I want to seed a draft from a template and then edit it, so
   the shipped criteria are a starting point rather than a verdict.
4. As an auditor, I want to see what templates the product ships without being
   able to create anything.

## Task report

### 1. RED — failing tests first

19 tests appended to `tests/unit/test_rubric_api.py` before any production code.

```
$ python -m pytest tests/unit/test_rubric_api.py -o addopts="" -q -p no:warnings -k template
11 failed, 3 passed, 68 deselected in 3.29s
```

Every failure was a `404` or `422` from a route that did not exist. The three
passes were the unknown-key 404 assertions passing *vacuously* — with no route
registered, any path 404s naturally. They became meaningful once the endpoints
existed, and are counted here as a weakness of the RED signal rather than as
evidence.

### 2. GREEN — endpoints implemented

Three routes added to `serving/app/routers/rubric.py`, four schemas to
`serving/app/schemas/rubric.py`.

```
$ python -m pytest tests/unit/test_rubric_api.py -o addopts="" -q -p no:warnings
82 passed in 5.88s
```

Suite-wide, with no regressions elsewhere:

```
$ python -m pytest tests/unit -o addopts="" -q -p no:warnings
541 passed in 7.71s
```

### 3. Lint

```
$ python -m ruff check serving/app tests
All checks passed!
```

`ruff format` reformatted `tests/unit/test_rubric_api.py`; the three files
touched by this change are clean afterwards. The other 37 files it reports as
unformatted are pre-existing and untouched here.

## What the routing-order test exists for

`GET /rubrics/templates` and `GET /rubrics/{rubric_version_id}` match the same
path shape. FastAPI resolves in declaration order, so with the parameterized
route first the literal string `templates` is bound to `rubric_version_id`,
fails UUID coercion, and the listing answers **422** — the catalogue would be
unreachable while every service-level test still passed.

`test_the_template_listing_is_not_shadowed_by_the_version_detail_route` asserts
`200` on that path. It is the one test here that cannot be pushed down a layer:
the defect is a property of the router's declaration order, not of any function.

## Test specification

| #  | What is guaranteed | Test | Type | Result |
|----|--------------------|------|------|--------|
| 1  | The listing is not shadowed by the version-detail route | `test_the_template_listing_is_not_shadowed_by_the_version_detail_route` | unit | PASS |
| 2  | The listing covers every key in the catalogue | listing coverage test | unit | PASS |
| 3  | The listing is ordered by display name | listing order test | unit | PASS |
| 4  | Each entry reports how many criteria it carries | requirement-count test | unit | PASS |
| 5  | The listing omits the criteria themselves | listing omission test | unit | PASS |
| 6  | Read-only roles may browse the catalogue | parametrized over viewer/auditor/hiring_manager | unit | PASS |
| 7  | Browsing without a token is refused | unauthenticated browse test | unit | PASS |
| 8  | Detail returns criteria in template order | detail order test | unit | PASS |
| 9  | Published weights are relative, not normalized | relative-weight test | unit | PASS |
| 10 | An unknown key is 404, not 500 | unknown-key test | unit | PASS |
| 11 | The 404 does not echo the requested key | reflection test | unit | PASS |
| 12 | Instantiating yields a draft with no content hash | draft-status test | unit | PASS |
| 13 | Every criterion carries over | criteria-carryover test | unit | PASS |
| 14 | Must-have flags carry over | must-have test | unit | PASS |
| 15 | Weights are normalized to exactly `1.0000` | normalization test | unit | PASS |
| 16 | `source` is recorded as `template` | provenance test | unit | PASS |
| 17 | An invisible job is 404 and stages no rows | job-visibility test | unit | PASS |
| 18 | The tenant comes from the token, not the payload | tenant-scoping test | unit | PASS |
| 19 | Read-only roles cannot instantiate | parametrized over read-only roles | unit | PASS |

Exact test names are in the "Starter templates" section of
`tests/unit/test_rubric_api.py`. The catalogue itself (shape, fairness,
immutability, lookup) is pinned separately by the 33 tests in
`tests/unit/test_rubric_templates.py`.

## Coverage

```
serving\app\routers\rubric.py                 73      9    88%   476-498
serving\app\schemas\rubric.py                 88      0   100%
serving\app\services\rubric_templates.py      31      0   100%
TOTAL                                       2395    333    86%
```

The nine uncovered lines in the router are the score-preview body, which is
exercised by `tests/integration/test_rubric_score_preview.py` — a suite that
cannot run on this machine (see below).

## Known gaps

- **No integration test for these three endpoints.** This machine has no local
  PostgreSQL; `pytest tests/integration/` fails with `ConnectionRefusedError:
  [WinError 1225]` for every DB-backed test. The unit tests run the real router
  against a stub session, so routing, auth, and response shape are genuinely
  covered, but the actual `INSERT` of a template-seeded draft is not.
- **Whether a template's criteria are the *right* criteria for a role** is a
  recruiting judgement, not a testable property. It is the reason instantiating
  produces an editable draft rather than an approved rubric.

## Phase 3 status after this change

Closed: template catalogue, and the `409` guard now that `score:preview` maps
`ensure_approved_for_scoring` onto an HTTP response.

Still open, unchanged: skill-taxonomy linking (blocked — ESCO/O*NET tables not
ingested), the UI rubric editor (different repo), golden-set labelling (needs a
recruiter panel), and the three end-to-end verification items (need a real
PostgreSQL).
