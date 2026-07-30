# Production Security Audit — TalentLens

**Date:** 2026-07-30
**Scope:** Full project at commit `bc9d0f6`, plus fixes applied during this audit
**Result:** 5 High and 4 Medium findings confirmed and fixed. 0 Critical.

---

## 1. Summary

| Severity | Found | Fixed | Remaining |
|---|---:|---:|---:|
| Critical | 0 | 0 | 0 |
| High | 5 | 5 | 0 |
| Medium | 4 | 4 | 0 |
| Low / accepted | 6 | 0 | 6 (documented) |

Verification after fixes:

```
ruff check .          -> All checks passed!
mypy serving/app      -> Success: no issues found in 25 source files
pytest tests/         -> 65 passed
coverage              -> 91.55% (floor 80%)
pip-audit             -> No known vulnerabilities found
```

---

## 2. High-severity findings

### H-1 — Broken access control: RBAC defined but never enforced

**Category:** Authorization (OWASP A01) · **Status:** FIXED

`Principal.require_role()` existed in `security.py` but a tree-wide grep proved
it was never called. Every route depended only on `CurrentPrincipal`, which
verifies *authentication* and nothing else. Any validly signed token — including
one carrying `roles: []` or `roles: ["viewer"]` — could upload resumes, read any
of the tenant's extracted candidate text, and create job descriptions. The
`roles` claim was decorative.

**Fix.** Added a `require_roles()` dependency factory with two closed allowlists:

```python
WRITE_ROLES: Final = ("owner", "admin", "recruiter")
READ_ROLES: Final = ("owner", "admin", "recruiter", "hiring_manager", "auditor", "viewer")
```

Applied as `WritePrincipal` / `ReadPrincipal` across all six resume and job
routes. Denials are logged with `user_id`, `tenant_id`, and the required roles.

**Regression tests added (4):** a `viewer` cannot upload or create; an empty
roles list cannot write; an unrecognized role (`superuser`) grants nothing —
the allowlist fails closed rather than open.

---

### H-2 — Rate limiter keyed on proxy IP: one client can deny service to all

**Category:** Availability · **Status:** FIXED

`_is_rate_limited()` bucketed on `request.client.host`. This service is deployed
behind a reverse proxy (HF Spaces), where that value is the *proxy's* address
for every request. All callers therefore shared a single 20-requests-per-minute
bucket, so any one client could exhaust the budget for the entire tenant base.

**Fix.** `_rate_limit_key()` now prefers the authenticated subject
(`sub:<tenant>:<user>`), falling back to the address only when no usable token
is present. The token is decoded **without signature verification** purely to
derive a bucket key — it grants nothing, and real authentication remains
entirely in `app.security`.

---

### H-3 — Rate limiter memory grows without bound

**Category:** Denial of service · **Status:** FIXED

`_request_counts` was a module-global `defaultdict(list)` whose keys were
caller-controlled and never evicted. Every distinct source address created a
permanent entry. Under address churn — trivially induced — this grows until the
process exhausts memory. An unbounded map keyed on attacker-controlled input is
itself the vulnerability.

**Fix.** Added `_RATE_LIMIT_MAX_TRACKED_KEYS = 10_000`; buckets whose newest
timestamp falls outside the window are evicted once the ceiling is crossed.

---

### H-4 — CPU-bound parsing blocks the event loop

**Category:** Availability / performance · **Status:** FIXED

`parse_document()` is synchronous CPU-bound work (PyMuPDF, python-docx) and was
called inline from `async def ingest_resume`. A single large or adversarial
document pinned the event loop for its entire duration, stalling *every*
concurrent request including health checks. `ARCHITECTURE.md` §4.4 explicitly
records this failure mode as already having caused a container restart in a
sibling project.

**Fix.** Both parse call sites now dispatch via
`starlette.concurrency.run_in_threadpool`.

---

### H-5 — 10 known CVEs in dependencies

**Category:** Vulnerable components (OWASP A06) · **Status:** FIXED

`pip-audit` reported:

| Package | Was | Advisories | Now |
|---|---|---|---|
| `starlette` | 0.46.2 | PYSEC-2026-161, -248, -249, -1941, -1942, -2280, -2281 (8 total) | **1.3.1** |
| `pytest` | 8.4.2 | PYSEC-2026-1845 | **9.1.1** |

Starlette is transitive via FastAPI, and the old `fastapi>=0.115,<0.116` pin
made a safe Starlette unreachable, so FastAPI was moved to `0.141.x`.
`pytest-asyncio` was raised to `>=1.0` to match pytest 9.

Post-upgrade: **`pip-audit` reports no known vulnerabilities**, and all 65 tests
still pass — the upgrade introduced no behavioural regression.

---

## 3. Medium-severity findings

### M-1 — PDF and DOCX decompression bombs — FIXED

A file can satisfy the 10 MiB byte ceiling and still declare tens of thousands
of pages, or expand into gigabytes of text. Both are cheap to construct and
expensive to parse. Added `MAX_PAGES = 500` and
`MAX_EXTRACTED_CHARS = 5_000_000`, enforced *during* extraction so the loop
aborts rather than completing the expansion. Two regression tests cover the
boundary (exactly `MAX_PAGES` parses; `MAX_PAGES + 1` raises).

### M-2 — Internal detail leaked through HTTP error envelope — FIXED

`handle_http_error` echoed `exc.detail` verbatim at every status. Library-raised
`HTTPException`s can carry internal paths, driver messages, or query fragments.
Now 5xx returns a fixed safe message and logs the detail server-side; client
errors are truncated to 500 characters.

### M-3 — Unbounded attacker-controlled value written to logs — FIXED

`logger.warning("auth_bad_scheme", scheme=scheme)` logged the entire
`Authorization` header prefix — unbounded, attacker-controlled, and a log
flooding/injection vector. Truncated to 32 characters.

### M-4 — API documentation exposed in production — FIXED

`/docs`, `/redoc`, and `/openapi.json` were served unconditionally, publishing
every route, schema, and field name. Now disabled when
`environment == "production"`.

---

## 4. Categories audited and found clean

| Category | Finding |
|---|---|
| **SQL injection** | **Clean.** All queries use SQLAlchemy `select()` with bound parameters. No f-string or `%`-formatted SQL anywhere; no `text()` with interpolation. |
| **Path traversal** | **Clean.** `sanitize_filename()` strips directory components, normalizes Unicode to ASCII, applies a conservative character allowlist, and truncates. Storage keys are composed server-side as `tenants/<tenant>/resumes/<sha256>/<safe-name>` — the client never influences the prefix. Covered by tests for `../../etc/passwd` and `..\..\windows\system32\cmd.exe`. |
| **File upload security** | **Clean.** Media type is determined from magic bytes, never from filename or `Content-Type`. DOCX is confirmed by inspecting the archive for `word/document.xml`, so a bare `.zip` cannot pass. Size is enforced *during* a chunked read (`read_upload_bounded`, 64 KiB chunks), so an oversized payload is never fully buffered. Empty uploads rejected. |
| **XSS** | **Not applicable at this layer.** The API is JSON-only and renders no HTML. Extracted resume text is returned raw, which is correct for an API — but the React SPA **must not** pass it to `dangerouslySetInnerHTML`. Flagged for the frontend. |
| **Secrets** | **Clean.** No credential in tracked files. `JWT_SECRET` and `SUPABASE_SERVICE_KEY` have no defaults and are blank in `.env.example`. `.env` and `*.key`/`*.pem` are gitignored. The only secret-shaped strings in the repo are deliberately named test fakes (`"test-secret-not-a-real-key"`). Production rejects a `JWT_SECRET` under 32 characters via a model validator. |
| **Authentication** | **Strong.** Signature, expiry, issuer, and audience all verified; `alg=none` rejected because the algorithm allowlist is explicit; `exp` and `sub` required; a token without `tenant_id` is refused. 13 tests cover forgery, expiry, wrong issuer/audience, malformed input, and algorithm confusion. |
| **Tenant isolation** | **Strong.** Every repository query filters on `tenant_id`. A foreign row returns 404, not 403 — existence is not disclosed. Verified for both resumes and jobs. |
| **Prompt injection** | **Not currently exploitable — no LLM exists in this codebase.** See L-1. |

---

## 5. Accepted / deferred risks

| # | Risk | Severity | Rationale |
|---|---|---|---|
| L-1 | **No prompt-injection sanitization.** `ARCHITECTURE.md` §15.2 Layers 1–2 (invisible text, tiny fonts, off-canvas positioning, metadata stripping) are unimplemented. Resume text is stored exactly as extracted. | Deferred | Not exploitable today — nothing feeds this text to a model. **This is a hard blocker for Phase 2** and must land before the first LLM call, not after. |
| L-2 | **No malware scanning.** HF Spaces Docker permits no ClamAV sidecar. | Accepted | Mitigated by strict magic-byte validation, size ceilings, parse limits, and `defusedxml`. A `MalwareScanner` port exists with a no-op default so enabling a scanning service later is a config change. |
| L-3 | **Rate limiter is per-process.** | Accepted | Correct for the current single-container deployment. Must move to a shared store (Redis) before horizontal scaling — noted in the module docstring. |
| L-4 | **No Alembic migrations.** Schema comes from `Base.metadata`. | Open | `CLAUDE.md` mandates Alembic. Required before any shared database. |
| L-5 | **No Postgres RLS.** Tenancy is enforced at the repository layer only. | Open | Repository scoping is tested and holds, but RLS as defense-in-depth is absent. |
| L-6 | **No dependency lockfile.** `pyproject.toml` pins ranges. | Open | CI and local can resolve differently; reproducibility is a stated project principle. |

---

## 6. Files changed by this audit

| File | Change |
|---|---|
| `serving/app/main.py` | Rate-limit key derivation, bucket eviction, `reset_rate_limiter()`, error-detail sanitization, production docs gating |
| `serving/app/security.py` | `require_roles()`, `WRITE_ROLES`/`READ_ROLES`, `WritePrincipal`/`ReadPrincipal`, log truncation |
| `serving/app/routers/resumes.py` | RBAC guards on all three routes; pagination cursor correctness |
| `serving/app/routers/jobs.py` | RBAC guards on all three routes |
| `serving/app/services/parser.py` | `MAX_PAGES`, `MAX_EXTRACTED_CHARS`, streaming enforcement |
| `serving/app/services/ingestion.py` | Threadpool offload for both parse call sites |
| `serving/app/logging.py` | Typed return via `cast` (mypy strict) |
| `pyproject.toml` | FastAPI 0.141.x, Starlette >=1.3.1, pytest 9.x, pytest-asyncio >=1.0 |
| `tests/conftest.py` | Autouse rate-limiter reset fixture |
| `tests/unit/test_auth.py` | 4 RBAC regression tests |
| `tests/unit/test_parser.py` | 2 resource-ceiling regression tests |

No application logic was altered beyond these security fixes. No files were
deleted.
