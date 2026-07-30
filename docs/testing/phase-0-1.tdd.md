# TDD Evidence Report — Phase 0 & 1

**Date:** 2026-07-30
**Scope:** FastAPI backend, PostgreSQL, authentication, resume upload, resume parser, job-description upload
**Runner:** `pytest` (Python 3.11.15, conda env `cv-screener`)

---

## 1. Source plan

No `*.plan.md` was supplied. Journeys were derived from the user's explicit requirement list, cross-checked against `ARCHITECTURE.md` §19 and `ARCHITECTURE-AGENTS.md` §3.1/§9.

**Scope divergence, recorded rather than silently resolved.** `ARCHITECTURE.md` §19 defines Phase 1 as ingestion *and structured extraction* — it includes OCR fallback, the full §15.2 sanitization pipeline, parent-child chunking, the multi-provider LLM adapter, a vLLM T2 deployment, and the Profile Extractor agent, and it is annotated *"Blocked on open question 2a"* (requires GPU capacity). The user's requirement list excludes all of that and adds job-description upload, which §19 places in Phase 3. **The user's list was treated as authoritative.** Nothing in this build makes an LLM call.

**Environment deviation.** `CLAUDE.md` mandates Python 3.11; only 3.12.7 was installed. A dedicated conda env (`cv-screener`, Python 3.11.15) was created rather than violating the documented standard.

---

## 2. User journeys

| # | Journey |
|---|---|
| J1 | As an operator, I want the service to refuse to start without its required configuration, so that a misconfigured deployment fails loudly instead of serving insecurely. |
| J2 | As an operator, I want every response to carry a correlation id and every error to share one envelope, so that I can trace and parse failures uniformly. |
| J3 | As a recruiter, I want to authenticate with a bearer token, so that only my tenant's data is reachable. |
| J4 | As a security reviewer, I want forged, expired, unsigned, and foreign-issuer tokens rejected, so that authentication cannot be bypassed. |
| J5 | As a recruiter, I want to upload a PDF or DOCX resume and get back structured text, so that I can review candidates. |
| J6 | As a recruiter, I want the same resume arriving twice to resolve to one document, so that my pool is not fragmented. |
| J7 | As a security reviewer, I want uploads validated on content rather than filename, and oversized/empty files rejected, so that the parser never touches hostile input. |
| J8 | As a tenant, I want another tenant's resumes and jobs to be invisible to me, so that isolation holds. |
| J9 | As a recruiter, I want to create a job description by pasting text or uploading a document, so that I can start a search. |

---

## 3. Task report

### Cycle 1 — Phase 0 foundations (config, app factory, health, error envelope, auth)

- **Execution:** Wrote `tests/unit/test_foundations.py` and `tests/unit/test_auth.py` first, confirmed RED, then implemented `config.py`, `exceptions.py`, `security.py`, `main.py`, `routers/auth.py`, `schemas/auth.py`.
- **RED evidence:** `python -m pytest tests/` → `13 failed, 11 errors in 1.46s`, every failure `ModuleNotFoundError: No module named 'app.config'` / `ImportError: cannot import name 'exceptions' from 'app'`. Compile-time RED for the intended reason (missing implementation), not broken setup.
- **GREEN evidence:** `python -m pytest tests/` → `24 passed`.
- **Guarantees:** required config fails fast; settings are cached; request ids are minted and echoed; all errors share the `{request_id, error, message, status_code}` envelope; the exception hierarchy exposes stable codes.

### Cycle 2 — Resume parser (deterministic, no LLM)

- **Execution:** Wrote `tests/unit/test_parser.py` first, confirmed RED, then implemented `utils/parsing.py` and `services/parser.py`.
- **RED evidence:** `python -m pytest tests/unit/test_parser.py` → `18 failed`, all `ModuleNotFoundError: No module named 'app.utils.parsing'` / `'app.services.parser'`.
- **Defect found by the tests:** the first GREEN attempt failed on `test_corrupt_docx_raises` with a raw `zipfile.BadZipFile` escaping to the caller — `BadZipFile` is not an `OSError` subclass, so the `except` tuple missed it. Fixed by adding `zipfile.BadZipFile` to the normalization clause in `_parse_docx`. This is exactly the class of leak the test existed to catch.
- **GREEN evidence:** `python -m pytest tests/` → `42 passed`.
- **Guarantees:** media type is decided by magic bytes (DOCX verified by inspecting for `word/document.xml`, not merely the ZIP magic); `text[start_char:end_char] == page.text` holds by construction; a text-free PDF sets `needs_ocr` + `low_yield` instead of returning `""`; corrupt input raises `DocumentParseError` rather than returning a partial parse; filenames are traversal-safe; content hashes are stable.

### Cycle 3 — Persistence, resume upload, JD upload, tenant isolation

- **Execution:** Started PostgreSQL 16 (`docker run postgres:16-alpine`, port 5433). Wrote `tests/integration/test_ingestion_api.py` first, confirmed RED, then implemented `db.py`, `models.py`, `repositories/ingestion.py`, `services/storage.py`, `services/ingestion.py`, `schemas/ingestion.py`, and the `resumes`/`jobs` routers.
- **RED evidence:** `python -m pytest tests/integration` → all 18 tests ERROR on `ModuleNotFoundError: No module named 'app.db'`.
- **GREEN evidence:** `python -m pytest tests/` → `59 passed`.
- **Guarantees:** upload returns 202 with a document id; text is retrievable; disguised executables are rejected 422 `UNSUPPORTED_MEDIA_TYPE`; oversized files 413 `PAYLOAD_TOO_LARGE`; identical bytes deduplicate; stored filenames are sanitized; a foreign tenant gets 404 (not 403 — existence is not disclosed) and an empty listing; jobs can be created from text or an uploaded PDF and are tenant-scoped.

### Refactor

- `File(...)` / `Form(...)` defaults converted to the `Annotated[...]` idiom, clearing 3× `B008` without suppressing the rule.
- `UUID as PgUUID` renamed to `PG_UUID`, clearing `N811`.
- Package docstrings added to all ten `__init__.py` files, clearing `D104`.
- `ECC/` (an unrelated third-party directory in the project root, carrying a `pyproject.toml` with an invalid `src-path` field that crashed unscoped ruff) added to `extend-exclude`.

---

## 4. Test specification

| # | What is guaranteed | Test | Type | Result |
|---|---|---|---|---|
| 1 | Missing `DATABASE_URL` raises rather than defaulting | `test_foundations.py::test_settings_missing_required_field_fails_fast` | unit | PASS |
| 2 | Settings are parsed once and shared | `test_foundations.py::test_get_settings_is_cached` | unit | PASS |
| 3 | `/health` is reachable without a token | `test_foundations.py::test_health_returns_200_without_authentication` | unit | PASS |
| 4 | Every response carries a UUID `X-Request-ID`; a supplied one is echoed | `test_foundations.py::test_every_response_carries_a_request_id_header`, `::test_supplied_request_id_is_echoed_back` | unit | PASS |
| 5 | Unknown routes return the standard error envelope | `test_foundations.py::test_unknown_route_returns_the_standard_error_envelope` | unit | PASS |
| 6 | Domain errors expose stable codes and statuses | `test_foundations.py::test_exception_hierarchy_exposes_stable_error_codes` | unit | PASS |
| 7 | A valid token yields user, tenant, and roles | `test_auth.py::test_valid_token_yields_a_principal` | unit | PASS |
| 8 | Expired / wrong-key / wrong-issuer / wrong-audience tokens are rejected | `test_auth.py::test_expired_token_is_rejected` and 3 siblings | unit | PASS |
| 9 | A token without `tenant_id` cannot authenticate | `test_auth.py::test_token_missing_tenant_claim_is_rejected` | unit | PASS |
| 10 | `alg=none` cannot authenticate | `test_auth.py::test_algorithm_confusion_none_is_rejected` | unit | PASS |
| 11 | Tenancy cannot be overridden by a query parameter | `test_auth.py::test_caller_cannot_override_tenant_via_query_param` | unit | PASS |
| 12 | PDF and DOCX are identified from bytes, not extension | `test_parser.py::test_pdf_is_detected_from_magic_bytes` and 3 siblings | unit | PASS |
| 13 | Page offsets index back exactly into the extracted text | `test_parser.py::test_page_offsets_index_back_into_the_extracted_text`, `::test_docx_offsets_index_back_into_the_extracted_text` | unit | PASS |
| 14 | A text-free PDF flags `needs_ocr` / `low_yield` | `test_parser.py::test_scanned_pdf_yields_no_text_and_flags_ocr` | unit | PASS |
| 15 | Corrupt PDF and DOCX raise `DocumentParseError` | `test_parser.py::test_corrupt_pdf_raises_rather_than_returning_garbage`, `::test_corrupt_docx_raises` | unit | PASS |
| 16 | Filenames are traversal-safe; hashes are content-addressed | `test_parser.py::test_filename_is_sanitized_against_traversal`, `::test_content_hash_is_stable_and_content_addressed` | unit | PASS |
| 17 | PDF/DOCX upload returns 202 with a document id | `test_ingestion_api.py::test_upload_pdf_resume_returns_202_and_a_document_id`, `::test_upload_docx_resume_is_accepted` | integration | PASS |
| 18 | Uploaded text is retrievable | `test_ingestion_api.py::test_uploaded_resume_text_is_retrievable` | integration | PASS |
| 19 | Disguised executable rejected 422; empty rejected; >10 MiB rejected 413 | `test_ingestion_api.py::test_upload_rejects_a_disguised_executable` and 2 siblings | integration | PASS |
| 20 | Identical bytes deduplicate to one document | `test_ingestion_api.py::test_identical_bytes_deduplicate_to_one_document` | integration | PASS |
| 21 | A foreign tenant gets 404 and an empty listing | `test_ingestion_api.py::test_a_tenant_cannot_read_another_tenants_resume`, `::test_resume_listing_is_scoped_to_the_callers_tenant` | integration | PASS |
| 22 | Jobs are creatable from text and from an uploaded PDF | `test_ingestion_api.py::test_create_job_from_pasted_text`, `::test_upload_job_description_as_a_pdf` | integration | PASS |
| 23 | Blank title / empty description are rejected 422 | `test_ingestion_api.py::test_create_job_rejects_a_blank_title`, `::test_create_job_rejects_an_empty_description` | integration | PASS |
| 24 | Jobs are tenant-scoped on read | `test_ingestion_api.py::test_job_is_retrievable_and_tenant_scoped` | integration | PASS |

---

## 5. Coverage and known gaps

```
python -m pytest tests/ --cov=serving/app --cov-report=term-missing
59 passed
TOTAL  620 stmts  43 miss  93%
Required test coverage of 80.0% reached. Total coverage: 93.06%
```

Final verification:

```
ruff check .          -> All checks passed!
mypy serving/app      -> Success: no issues found in 23 source files
pytest tests/         -> 59 passed
build (openapi)       -> 7 paths generated, title "TalentLens"
```

**Known gaps, deliberate:**

- **No Alembic migration yet.** Schema is created from `Base.metadata` in the test fixture. `CLAUDE.md` requires Alembic for every schema change; the initial revision must be generated before this touches a shared database.
- **No OCR.** Tesseract is not installed on this machine. `needs_ocr` is detected and surfaced but nothing acts on it.
- **No sanitization pipeline.** `ARCHITECTURE.md` §15.2 Layers 1–2 (invisible-text stripping, injection scoring) are not implemented. Resume text is currently stored as extracted. This is the most significant deferred item — it is a security control, not a feature.
- **Supabase Storage adapter is a stub** that raises `StorageError`; only the in-memory adapter works. The `ObjectStore` port exists so this is an adapter swap.
- **No tenants/users/roles/api_keys/audit_events tables, no RLS.** `ARCHITECTURE.md` §19 Phase 0 requires these; tenancy is currently enforced at the repository query level only. Repository-level scoping is tested and holds, but RLS as defense-in-depth is absent.
- **No rate limiting, structured logging, OTel, or `/metrics`.**
- Uncovered lines are predominantly error branches in the Supabase storage stub and a few defensive paths.

---

## 6. Merge evidence

**The project is not a git repository** (`git init` has not been run), so the skill's checkpoint-commit protocol could not be followed — no RED/GREEN/refactor commits exist. This report is therefore the sole durable record of the RED→GREEN sequence. If the project is later placed under version control, the cycle boundaries above (RED command + output, GREEN command + output, refactor list) are what would have been committed.
