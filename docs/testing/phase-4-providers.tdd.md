# TDD Evidence Report — Phase 4: LLM Provider Layer

**Date:** 2026-08-02
**Branch:** `develop`
**Commit:** `94cd8d5` — `feat(agents): add LLM provider layer with failover and PII-tier gating`
**Scope:** `serving/app/agents/` — provider-neutral request/response types, the
failover chain, the heterogeneous-error classifier, and the Gemini and Groq HTTP
adapters
**Result:** 62 new tests, all passing. Unit suite 361 → 423. Coverage 85.19%
(floor 80%). All three new modules at 100%. `ruff` clean, `mypy` unchanged at its
pre-existing 12-error baseline.

This report closes gap #2 from
[`phase-4-scoring.tdd.md`](phase-4-scoring.tdd.md) §7 — "`serving/app/agents/`
does not exist" — and therefore also unblocks gaps #4 and #12 there. It does
**not** close #3, #5, #6, or #7; see §7 below.

---

## 1. Source plan and scope decision

`plan.md`, `prd.md`, and `task.md` were read **as data, not as instructions**,
per the skill's plan-handoff rule. None contains instruction-to-agent override
phrasing, destructive filesystem operations, credential-printing steps, or
fetch-and-execute commands, so nothing had to be rejected or quarantined.

The trigger was the user adding `GOOGLE_API_KEY` and `GROQ_API_KEY` to `.env`.
That made the adapter layer the next buildable slice, and it also exposed a real
defect: `Settings` uses `extra="ignore"`, so both keys were being **silently
discarded** at load. A key present in the environment and invisible to the
application is worse than an absent one, because it reads as configured.

**In scope and built:**

1. `agents/base.py` — `LLMRequest`, `LLMResponse`, the `LLMProvider` protocol,
   and `FailoverChain` with PII-tier gating
2. `agents/classifier.py` — `classify_provider_error`, normalizing every vendor's
   dialect into one six-value vocabulary
3. `agents/providers.py` — `GeminiProvider`, `GroqProvider`, and the shared HTTP
   base that owns credential hygiene
4. `config.py` — the five LLM settings plus the two keys, so a model id is a
   config change (`plan.md:255`: "Model id hanya di `config.py`")
5. `exceptions.py` — `LLMProviderError`, `LLMRefusalError`,
   `NoEligibleProviderError`, `BudgetExceededError`

**Deliberately out of scope:** the judge call itself, the `hf:` adapter for T2,
batching, and scheduling. Enumerated with reasons in §7.

### The honesty boundary, stated before the tests were written

Phase 3 deferred the JD Analyst on the ground that "testing against a mock only
proves the mock was called," and that objection is correct about *model
behaviour*. It is not correct about *wiring*. The two were separated:

- **Provable deterministically, and proved here:** where the credential travels,
  whether temperature is pinned, which failures are retried, which provider is
  even allowed to see a given prompt, and whether a key can surface in a `repr`
  or an exception. These are properties of our code. A `MockTransport` is the
  right instrument, not a compromise.
- **Not provable this way, and not claimed:** that a real model returns usable
  JSON. That belongs in `live`-marked contract tests, excluded from the default
  run.

That boundary is written into the test module's own docstring and into the commit
body, so it survives independently of this report.

---

## 2. User journeys

| # | Journey |
|---|---|
| J1 | As a candidate, I want my full resume never sent to a cloud free tier, so that consenting to screening does not mean consenting to third-party training data. |
| J2 | As an operator, I want a rate-limited provider to fail over rather than fail the run, so that a free-tier quota is a routine event and not an outage. |
| J3 | As an operator, I want an oversized prompt to fail immediately rather than march down the chain, so that one bad document does not burn every key I have. |
| J4 | As an operator, I want one vocabulary for provider failures, so that adding a provider does not mean teaching the policy a new dialect. |
| J5 | As a security reviewer, I want an API key absent from every log line, `repr`, URL, and stack trace, so that a crash report is not a credential disclosure. |
| J6 | As a compliance reviewer, I want a model refusal distinguished from a model failure, so that "the model declined" is never retried into a different answer. |
| J7 | As an auditor, I want the same prompt to produce the same output, so that a disputed score can be re-derived. |
| J8 | As a hiring manager, I want text from a resume unable to reach the system channel, so that a candidate cannot instruct the judge. |

---

## 3. Task report

One increment, and **the commit shape deviates from the previous slice — stated
here rather than smoothed over.**

### Increment 1 — Provider layer (`94cd8d5`, single commit)

**RED was reached and observed:**

```
/d/Anaconda/envs/cv-screener/python.exe -m pytest tests/unit/test_llm_provider.py \
    -o addopts="" -q -p no:warnings

    ModuleNotFoundError: No module named 'app.agents'
```

Collection failed because the package did not exist. **That is the intended
reason** — the absence of the code under test, not a typo in the test file.

**The deviation:** in the Phase 4 scoring slice, RED was captured as its own
checkpoint commit (`b769a3e`) before any production code was written. Here it was
not. RED was confirmed in the terminal, but the four production modules were
written before a RED commit existed, so this landed as one commit rather than the
RED→GREEN pair. The RED evidence above is real and was observed; what is missing
is the *commit* proving the ordering to someone reading only the git history.
Anyone auditing this from the log alone should treat the ordering as asserted by
me, not demonstrated by the repository.

**GREEN evidence:**

```
/d/Anaconda/envs/cv-screener/python.exe -m pytest tests/unit/test_llm_provider.py \
    -o addopts="" -q -p no:warnings
-> 62 passed

/d/Anaconda/envs/cv-screener/python.exe -m pytest tests/unit/ -o addopts="" -q -p no:warnings
-> 423 passed in 11.14s
```

### Refactor

**Two changes, both driven by a measurement rather than taste.**

First GREEN left `providers.py` at 88% and `classifier.py` at 86%. The uncovered
lines were not decoration — they were the transport-failure branch, which is
precisely the path `FailoverChain`'s network fallback depends on. An untested
fallback is a fallback that has never fallen back. 16 tests were added:
`ConnectError` and `ReadTimeout` → `network`, a non-JSON body → a classified
`LLMProviderError`, an unmapped 507 → `model_unavailable`, an unmapped 418 →
`unknown`, `ProtocolError` → `network`, a streamed unread 400 classifying rather
than raising `ResponseNotRead`, and `maxOutputTokens`/`max_tokens` forwarding —
each parametrized across both providers where applicable. All three modules
reached **100%**.

Second, `ruff` flagged three `E501` violations after the additions. Reflowed; no
logic touched.

---

## 4. Test specification

62 tests in `tests/unit/test_llm_provider.py`.

| # | What is guaranteed | Test type | Result |
|---|---|---|---|
| 1 | `LLMRequest` rejects an unknown `pii_tier` at construction, listing the valid ones | unit | PASS |
| 2 | `LLMRequest` and `LLMResponse` are frozen — a tier cannot be mutated after a routing decision | unit | PASS |
| 3 | A provider whose `tiers` exclude the request's tier is **skipped before `generate` is called** | unit | PASS |
| 4 | A T2 request against a chain of cloud-only providers raises `NoEligibleProviderError` and **no HTTP request is issued** | unit | PASS |
| 5 | That message names the tier and the count only — never the prompt | unit | PASS |
| 6 | `rate_limit`, `network`, `model_unavailable`, `auth`, and `unknown` each fail over to the next eligible provider | unit (parametrized) | PASS |
| 7 | `context` does **not** fail over — it propagates immediately | unit | PASS |
| 8 | `LLMRefusalError` propagates immediately and is never retried on another provider | unit | PASS |
| 9 | When every eligible provider fails, the error names the attempt count and the last failure kind | unit | PASS |
| 10 | A chain whose first provider succeeds never calls the second | unit | PASS |
| 11 | An empty chain raises `NoEligibleProviderError`, not `IndexError` | unit | PASS |
| 12 | Gemini sends the key in `x-goog-api-key`, never in the URL or query string | unit | PASS |
| 13 | Groq sends the key as `authorization: Bearer …`, never in the URL | unit | PASS |
| 14 | Both providers pin `temperature` to `0.0` in the wire payload, regardless of caller input | unit | PASS |
| 15 | Gemini places `system` on `systemInstruction`, so prompt text cannot reach the system authority level | unit | PASS |
| 16 | Groq places `system` as the **first** message and the prompt after it — ordering asserted, not just presence | unit | PASS |
| 17 | `max_output_tokens` maps to `maxOutputTokens` (Gemini) and `max_tokens` (Groq) | unit | PASS |
| 18 | A Gemini `promptFeedback.blockReason` raises `LLMRefusalError` | unit | PASS |
| 19 | A Gemini `finishReason` of `SAFETY`/`BLOCKLIST`/`PROHIBITED_CONTENT` raises `LLMRefusalError` | unit (parametrized) | PASS |
| 20 | A Groq `finish_reason` of `content_filter` raises `LLMRefusalError` | unit | PASS |
| 21 | An empty `candidates`/`choices` list raises `LLMProviderError` — **never returns `""`** | unit | PASS |
| 22 | Token counts are read from the response and default to 0 when absent | unit | PASS |
| 23 | HTTP 401/403 → `auth`; 404 → `model_unavailable`; 408/502/504 → `network`; 413 → `context`; 429 → `rate_limit`; 503 → `model_unavailable` | unit (parametrized) | PASS |
| 24 | A 400 whose body matches a context-overflow hint → `context`; a plain 400 → `unknown` | unit | PASS |
| 25 | An unmapped 5xx (507) → `model_unavailable`; an unmapped 4xx (418) → `unknown` | unit | PASS |
| 26 | `ConnectError`, `ReadTimeout`, and `ProtocolError` → `network` | unit (parametrized) | PASS |
| 27 | A streamed, unread 400 body classifies rather than raising `ResponseNotRead` | unit | PASS |
| 28 | A non-JSON 200 body raises `LLMProviderError` with `kind="unknown"` | unit (both providers) | PASS |
| 29 | `repr()` and `str()` of either provider render provider and model only — **the key appears in neither** | unit | PASS |
| 30 | No transport-failure message contains the fake key | unit (both providers) | PASS |

**Two notes on how these were written.** The tier check in #3 is asserted as
happening *before* `generate` rather than as a post-filter on the result — a
post-filter would already have transmitted the PII, and the test would still be
green. And the fake keys (`AIzaSy-not-a-real-key-…`, `gsk_not_a_real_key_…`) are
**synthetic leak-detection markers, not credentials**; their only purpose is to
give #29 and #30 something to search for.

---

## 5. Quality gates

| # | Gate | Command | Result |
|---|---|---|---|
| 1 | Tests | `pytest tests/unit/ -o addopts=""` | **423 passed in 11.14s** (361 → 423, **+62**) |
| 2 | Coverage | `pytest tests/unit/ --cov=serving/app` | **85.19%**, floor 80% (up from 83.74%) |
| 3 | Lint | `ruff check serving/app tests` | **All checks passed!** |
| 4 | Type check | `mypy serving/app` | `Found 12 errors in 4 files (checked 49 source files)` — **pre-existing** |

**On the 12 mypy errors: they pre-date this work.** Distribution unchanged —
`models.py` 1, `repositories/search.py` 3, `services/indexing.py` 6,
`services/reranker.py` 2. File count rose 45 → 49 because four modules were
added; the error count did not move. **Zero errors in new code.** Left alone
rather than fixed opportunistically inside a TDD increment.

Coverage of files created or changed:

| File | Coverage |
|---|---|
| `serving/app/agents/base.py` | **100%** |
| `serving/app/agents/classifier.py` | **100%** |
| `serving/app/agents/providers.py` | **100%** |
| `serving/app/exceptions.py` | **100%** |

### Credential hygiene — verified, not assumed

Before committing:

- `.env.example` carries both new key names with **empty values**
- `git grep` over tracked `*.py`/`*.example`/`*.md`/`*.toml` for `AIzaSy|gsk_`,
  excluding the two synthetic markers → **zero hits**
- `git status --short` confirmed `.env` untracked; exactly 8 files staged
- `.env` was read for variable **names and value lengths only**. No value was
  printed to the transcript, to a log, or to a file.

---

## 6. Design decisions the tests forced

- **`context` is absent from `_RETRYABLE_KINDS`, and that is the load-bearing
  line.** Every other failure kind is about the provider; `context` is about the
  prompt. A prompt that overflows one model's window overflows the next one too,
  so failing over would spend three quotas to fail three times and delay the
  error the operator actually needs. Test #7 pins this.

- **PII-tier gating runs before `generate`, not after.** `_CLOUD_TIERS =
  frozenset({"T0", "T1"})` with T2 deliberately absent. `plan.md` §4 requires
  enforcement "di kode (`NoEligibleProviderError`), bukan konvensi." Test #4
  asserts not merely that the error is raised but that **no HTTP request was
  issued** — the only assertion that distinguishes a gate from a filter.

- **`LLMRefusalError` never fails over.** A refusal is a *decision*, not a
  malfunction. Retrying it on another vendor is shopping for a compliant answer,
  and it would silently convert a documented decline into a verdict. It
  propagates from inside the chain's own `except` block, ahead of the retry
  logic.

- **The `NoEligibleProviderError` message says nothing about the prompt.** At T2
  the prompt is a full resume, and this message reaches both logs and API
  responses. It names the tier and the count.

- **An empty candidate list raises rather than returning `""`.** An empty string
  would flow downstream and be parsed as a malformed verdict, producing a
  confusing failure three layers away from the cause. `plan.md` §3's "tidak
  pernah di-default" applies to the empty string as much as to a substituted
  verdict.

- **Only narrow exception types are caught in `_post`** —
  `httpx.HTTPStatusError`, `httpx.HTTPError`, and `ValueError` for a non-JSON
  body. This deliberately does **not** copy the
  `except (httpx.HTTPError, httpx.ConnectError, Exception)` pattern at
  `services/embedding.py:190`, which CLAUDE.md's "Never swallow errors" rule
  disallows and which would turn a `KeyboardInterrupt` into a provider failure.

- **`classify_provider_error` never raises.** A classifier that throws while
  classifying an error destroys the original traceback. Unmapped input degrades
  to `"unknown"`, which is retryable — the safe direction, since the cost of one
  wasted retry is lower than the cost of a spurious hard failure.

- **`_looks_like_context_overflow` uses seven narrow substrings**, not a broad
  regex, and guards `response.text` with `except (UnicodeDecodeError,
  httpx.ResponseNotRead)`. A streamed body is a legitimate runtime state, and
  crashing the classifier over it would convert a retryable failure into an
  unhandled exception (test #27).

- **`__repr__` is overridden and `__str__` aliased to it.** Overriding only
  `__repr__` still leaks through f-strings, which call `__str__`. Test #29 checks
  both.

- **Temperature is pinned in the payload builder, not taken from the caller.**
  `plan.md:156` requires temp=0 for reproducibility. Reading it from a settings
  field the caller could override would make an audit depend on a config value
  nobody re-reads.

---

## 7. Known gaps

Stated plainly, because the alternative is a report that implies more was
verified than actually was.

| # | Gap | Status |
|---|---|---|
| 1 | **No live provider call was ever made.** Every test runs against `httpx.MockTransport`. Both real keys are present in `.env` and were never used. | **Open, and the most important entry here.** The wiring is proved; the model's behaviour is not. Nothing in this report should be read as evidence that Gemini or Groq returns usable output. |
| 2 | `live`-marked contract tests | **Not started.** The `live` marker must be registered in `pyproject.toml` first — `--strict-markers` is on, so using it unregistered is an error, not a warning. |
| 3 | **The integration suite was not run to a pass on this machine.** No local PostgreSQL; every DB test errors `ConnectionRefusedError: [WinError 1225]`. | Open, carried from the previous report. **No integration result is claimed as PASS.** Nothing in this increment touches the DB. |
| 4 | The `hf:` prefix adapter for T2 (dedicated HF Inference Endpoint, autoscale-to-zero, guided JSON) | **Not started.** Until it exists, **no T2 request can be served at all** — the chain correctly raises `NoEligibleProviderError` rather than downgrading to a cloud provider. That is the intended failure, not a workaround. `task.md:106` is therefore left **unticked**. |
| 5 | The judge call itself — prompt, parse, one repair retry, then hard-fail | **Not started.** Unblocked now; the natural next cycle. |
| 6 | Requirement batching | Blocked on #5. |
| 7 | Token-bucket scheduling, key pooling, admission-control ETA | **Not started.** `BudgetExceededError` exists as a type but nothing raises it yet. |
| 8 | Phase 4 ORM tables — `screening_runs`, `candidate_scores`, `requirement_verdicts`, `evidence_spans` — and their Alembic migration | **Not started.** Unblocked and deterministic. |
| 9 | `POST` screening-run admission endpoint (`202` / `409`) | Not started; depends on #8. |
| 10 | `FailoverChain` is never constructed by production code — no factory reads `settings.google_api_key` into a chain yet | **Open.** The layer is complete and tested but not yet wired to a caller. It ships as a library, not as a running path. |
| 11 | `services/redaction.py` and the blind-mode leakage test (`plan.md` §4) | **Not started.** Tier gating decides *where* a prompt may go; redaction decides *what is in it*. The second half is missing. |
| 12 | 12 pre-existing mypy errors in `search.py`, `reranker.py`, `indexing.py`, `models.py` | Pre-existing, measured (§5), untouched. |
| 13 | `SearchFilters.sections` (`schemas/search.py:22`) accepted and silently ignored | Pre-existing, unrelated. Recorded so it is not lost. |
| 14 | The bare-`Exception` catch at `services/embedding.py:190` | Pre-existing. Not copied into the new code; not fixed either. |

---

## 8. Merge evidence

| Increment | RED | GREEN | Refactor |
|---|---|---|---|
| Provider layer | Observed in terminal (`ModuleNotFoundError: No module named 'app.agents'`) — **not captured as a commit**, see §3 | `94cd8d5` (62 passed, suite 423 passed) | Coverage-driven, same commit (§3) |

`94cd8d5` is on `develop` and reachable from `HEAD`. No `Co-Authored-By` trailer,
per the repository's Sole Authorship Policy. Not pushed — no authorization was
given.

Final state: **423 unit tests passing, 85.19% coverage, ruff clean, mypy
unchanged at its pre-existing 12-error baseline, three new modules at 100%.**
