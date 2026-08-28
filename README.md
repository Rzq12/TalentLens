# TalentLens

Resume screening backend for recruiters — structured document parsing,
tenant-isolated storage, and evidence-anchored text extraction.

[![CI](https://github.com/Rzq12/TalentLens/actions/workflows/ci.yml/badge.svg)](https://github.com/Rzq12/TalentLens/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## What this is, and what it is not

**Current state: Phase 0–4 backend workflow is operational. Deterministic
scoring persists ranked assessments, quoted evidence, and best-effort advisory
insights. All 31 ORM models, 15 table RLS policies, and agent infrastructure
are in place.**

The ingestion and identity foundations came first, because a scoring system
sitting on an unreliable parser produces confident nonsense. What exists today:

| Working                                                               | In progress / Next                                |
| --------------------------------------------------------------------- | ------------------------------------------------- |
| JWT + Supabase JWKS authentication with tenant isolation              | Recruiter Chat (RAG, #14)                         |
| Resume upload (PDF, DOCX) validated on content                        | Resume Improvement (candidate-facing, #10)        |
| Deterministic parsing with exact character offsets                    | Live-provider evaluation and labelled quality set |
| Content-hash deduplication with OCR fallback for scanned PDFs         | Live-provider evaluation and labelled quality set |
| Job description upload (pasted text or document)                      | Retrieval funnel measurement and cost controls    |
| Hybrid dense + lexical search with reranking                          | Fraud and bias sidecar wiring                     |
| Rubric versioning, approval, weight normalization                     | Recruiter Chat (RAG, #14)                         |
| JD Analyst rubric drafting                                            |                                                   |
| Candidate scoring runs, ranks, verdicts, and verified evidence        |                                                   |
| Skill-gap, interview, and recommendation insight persistence          |                                                   |
| Detailed result endpoint for ranked assessments                       |                                                   |
| Durable admission, Postgres task queue, retry/backoff, and worker service | Evaluation golden-set labelling (200+ recruiter cases) |
| Recruiter decisions, verdict overrides, audit verification, and PostgreSQL coverage | Compliance delivery gates and DSAR workflow |
| Tenant-local tamper-evident audit chain                               |                                                   |
| RLS on all tenant-scoped tables                                       |                                                   |
| ONNX e5-small embedding (CPU, no GPU)                                 |                                                   |
| SSE progress streaming                                                |                                                   |
| Alembic migrations, 31 ORM models                                     |                                                   |
| Structured logging, uniform error envelope, /metrics                  |                                                   |
| Dockerfile + docker-compose for local dev                             |                                                   |

The eventual design is a multi-agent screening pipeline. This repository is the
foundation it will sit on.

## Design commitments

Three constraints shape the whole system, and they are what separate this from
"send a resume to an LLM and ask for a score":

**The system will never reject a candidate.** It ranks, explains, and
recommends; a human makes every advance/reject decision. Recruitment AI is
classified high-risk under the EU AI Act (Annex III), so human oversight is a
structural property here, not a UI convention.

**Evidence is anchored to exact offsets.** The parser records
`(page, start_char, end_char)` for every span, and
`text[start_char:end_char] == page.text` holds by construction. This is why
parsing is deterministic library code rather than a model — an LLM paraphrases
where we need it to transcribe, and one drifted offset silently breaks every
citation downstream.

**Failures are loud.** A resume is parsed once and reused across every job, so a
partial or guessed parse would bias every future assessment of that candidate.
Corrupt input raises rather than degrading.

## Architecture

```
React + Vite SPA  ──HTTPS + Bearer JWT──▶  FastAPI          ──▶  PostgreSQL
    (Vercel)                              (HF Spaces Docker)
                                                │
                                                ▼
                                          Object storage
```

Backend layering is strictly one-directional:

```
serving/app/
├── main.py           app factory, middleware, error handlers — no logic
├── config.py         all configuration via pydantic-settings
├── exceptions.py     domain errors carrying stable codes + HTTP status
├── security.py       the single source of caller identity
├── logging.py        structured logging setup
├── db.py             engine, session factory, declarative base
├── models.py         ORM models
├── routers/          HTTP only. May call services.
├── services/         business logic. May call repositories and utils.
├── repositories/     the only layer that queries the database
├── schemas/          Pydantic request/response models
└── utils/            pure functions, no side effects
```

`routers → services → repositories`. Nothing skips a layer. Every tenant-scoped
query filters on `tenant_id`, and a row belonging to another tenant is reported
as **not found** rather than forbidden — existence is never disclosed.

## Quickstart

**Requirements:** Python 3.11 (not 3.12), Docker, PostgreSQL 16.

```bash
git clone https://github.com/Rzq12/TalentLens.git
```

```bash
pip install -e ".[dev]"
```

For scanned-PDF OCR outside Docker, install the optional Python package and a
Tesseract binary available on `PATH`:

```bash
pip install -e ".[ocr]"
```

```bash
cp .env.example .env
```

Fill in `DATABASE_URL` and `JWT_SECRET` — both are required and have no
defaults. The application refuses to start without them, by design.

Start a database. The image must ship pgvector — the first migration runs
`CREATE EXTENSION vector`, and stock `postgres:16` does not carry it:

```bash
docker run -d --name talentlens-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=talentlens -p 5432:5432 pgvector/pgvector:pg16
```

Apply the migrations:

```bash
alembic upgrade head
```

Neon is supported with an async runtime URL such as
`postgresql+asyncpg://...?...ssl=require`; Alembic automatically uses the
corresponding psycopg2 URL and TLS parameter while migrating. The target
database must permit the `vector` extension for resume embeddings.

Run the API:

```bash
uvicorn app.main:create_app --factory --reload --app-dir serving
```

Interactive API docs: <http://localhost:8000/docs>

## API

All endpoints are prefixed `/api/v1` and require `Authorization: Bearer <jwt>`,
except `/health`.

| Method | Path                                                   | Description                                           |
| ------ | ------------------------------------------------------ | ----------------------------------------------------- |
| `GET`  | `/health`                                              | Liveness probe (unauthenticated)                      |
| `GET`  | `/metrics`                                             | Prometheus metrics (unauthenticated)                  |
| `GET`  | `/api/v1/auth/me`                                      | Identity of the verified caller                       |
| `POST` | `/api/v1/resumes`                                      | Upload a PDF or DOCX resume, returns `202`            |
| `GET`  | `/api/v1/resumes`                                      | List the tenant's resumes (cursor-paginated)          |
| `GET`  | `/api/v1/resumes/{document_id}`                        | Document detail with extracted text                   |
| `POST` | `/api/v1/jobs`                                         | Create a job from pasted text, returns `201`          |
| `POST` | `/api/v1/jobs/upload`                                  | Create a job from an uploaded document                |
| `GET`  | `/api/v1/jobs`                                         | List the tenant's jobs (cursor-paginated)             |
| `GET`  | `/api/v1/jobs/{job_id}`                                | Read a job description                                |
| `POST` | `/api/v1/search/candidates`                            | Rank candidates against a job's requirements          |
| `POST` | `/api/v1/search/similar`                               | Find resumes similar to a free-text query             |
| `POST` | `/api/v1/rubrics`                                      | Create a draft rubric for a job                       |
| `GET`  | `/api/v1/rubrics/{rubric_version_id}`                  | Read one rubric version                               |
| `POST` | `/api/v1/rubrics/{rubric_version_id}/requirements`     | Replace a draft's criteria                            |
| `POST` | `/api/v1/rubrics/{rubric_version_id}/approve`          | Approve and freeze a rubric                           |
| `POST` | `/api/v1/screening/jobs/{job_id}/runs`                 | Start a screening run (202 + SSE)                     |
| `GET`  | `/api/v1/screening/runs/{run_id}`                      | Poll run status                                       |
| `GET`  | `/api/v1/screening/runs/{run_id}/events`               | SSE stream for run progress                           |
| `GET`  | `/api/v1/screening/runs/{run_id}/results`              | Get ranked results of a completed run                 |
| `POST` | `/api/v1/governance/scores/{score_id}/decisions`       | Record a human screening decision                     |
| `POST` | `/api/v1/governance/verdicts/{verdict_id}/override`    | Record a reasoned verdict override                    |
| `GET`  | `/api/v1/governance/audit/verify`                      | Verify the caller tenant's audit chain                |
| `POST` | `/api/v1/rubrics/{rubric_version_id}/versions`         | Mint the next version                                 |
| `POST` | `/api/v1/rubrics/{rubric_version_id}/score:preview`    | Score against hypothetical verdicts                   |
| `GET`  | `/api/v1/rubrics/templates`                            | List the starter templates                            |
| `GET`  | `/api/v1/rubrics/templates/{template_key}`             | Read one starter template                             |
| `POST` | `/api/v1/rubrics/templates/{template_key}:instantiate` | Seed a draft from a template                          |
| `GET`  | `/api/v1/demo/assessment/sample`                       | Sample Junior Architect job + 5 CVs (unauthenticated) |
| `GET`  | `/api/v1/demo/assessment/run`                          | Ranked report for the sample (unauthenticated)        |

Every response and error carries a `request_id`. Errors share one shape:

```json
{
  "request_id": "3f2b1c7e-...",
  "error": "UNSUPPORTED_MEDIA_TYPE",
  "message": "File must be a PDF or DOCX document.",
  "status_code": 422
}
```

Upload validation is content-based: the media type comes from magic bytes, and
DOCX is confirmed by inspecting the archive for `word/document.xml`. A `.pdf`
filename over executable bytes is rejected `422`.

## Operational behavior

Screening admission persists a `ScreeningRun` and durable task in the same
database transaction. The in-process runner and standalone worker can recover
stale task claims and resume a run after interruption. The Compose `worker`
service continuously drains ready runs. Transient failures use bounded exponential
backoff and stop at `max_attempts`; rate-limit or quota reschedules preserve the
attempt count and set `not_before`. Scoring reuses persisted candidate scores,
evaluates only unfinished candidates, and reranks the complete set.

Recruiters can record a decision on a score and override a displayed requirement
verdict only with a reason. Overrides retain the original automated verdict and
write tenant-local audit events. The decision actor is the authenticated
principal UUID and is intentionally not required to have a local `users` row;
apply Alembic revision `20260811_0115` before using the complete governance and
worker policy schema. PostgreSQL integration tests cover both governance access
controls and durable worker transitions.

The deterministic evaluation gate runs `eval/golden_set.v1.json` against
`eval/baseline.v1.json` and fails CI if a tracked metric drops by more than 3%.
The supplied fixture is a harness seed only; it is not a recruiter-labelled
production golden set.

External-provider smoke tests are opt-in and never reuse normal provider
credentials. Set `TALENTLENS_RUN_LIVE_PROVIDER_TESTS=1` and configure one local
dedicated credential, such as `TALENTLENS_LIVE_GOOGLE_API_KEY`, then run:

```bash
pytest tests/live/test_provider_smoke.py -q
```

Use synthetic T0 input only. Do not run a live test with applicant data or put
credentials in `.env.example`, source control, or chat.

## Testing

```bash
pytest tests/ -q
```

Integration tests need PostgreSQL with pgvector on port 5433:

```bash
docker run -d --name talentlens-test-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=talentlens_test -p 5433:5432 pgvector/pgvector:pg16
```

**582 tests (547 unit, 35 integration), 90.6% coverage** (floor enforced at 80%).
Written test-first — the per-cycle RED/GREEN evidence lives in
[docs/testing/](docs/testing/), one report per phase.

The integration tests need the database above; without it they error rather than
silently skipping, because a green suite that never touched PostgreSQL would
misreport what was verified.

Quality gates:

```bash
ruff check . && mypy serving/app && pytest tests/ -q
```

The live-provider marker is opt-in; a default full suite must report it as
skipped when no dedicated `TALENTLENS_LIVE_*_API_KEY` is configured.

## Data handling

This system processes personal data about job applicants.

- Candidate documents and databases are **never** committed. `data/`,
  `uploads/`, `storage/`, and `*.db` are gitignored — Git history is effectively
  irreversible, and a GDPR erasure request cannot reach it.
- No dataset is bundled. Bring your own documents.
- Resume text is treated as untrusted input, and the sanitization pipeline that
  acts on that assumption is implemented in `services/sanitize.py`: spans hidden
  by colour, zero-size fonts, or off-canvas placement are stripped and flagged
  before any text reaches a model. Detection is deterministic, so its behaviour
  is reproducible and auditable. Review the known gaps in the TDD reports before
  pointing this at real candidate data.

## Contributing

Solo project; `@Rzq12` is the sole author. Branch strategy, Conventional Commits
format, and the definition of done are documented in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 Riezqi Dhermatria
