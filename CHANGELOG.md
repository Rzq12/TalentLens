# Changelog

All notable changes to TalentLens are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Initial project scaffolding: FastAPI application factory, layered architecture
- JWT authentication with tenant isolation
- Resume upload (PDF, DOCX) with content-based MIME validation
- Deterministic document parsing with exact character offsets
- Content-hash deduplication for resumes
- Job description upload and retrieval
- Per-tenant rate limiting (IP-based sliding window)
- Rubric authoring, versioning, and approval workflow
- Immutable-on-approval rubric versioning with `content_hash` fingerprinting
- Starter rubric templates per role family (7 templates)
- JD Analyst agent: draft rubric from job description (T0, free-tier LLM)
- LLM provider layer with multi-provider failover and PII-tier gating
- Deterministic Phase 4 scoring core: weighted aggregation, must-have capping
- Verbatim span verification for evidence citations
- Hybrid search with pgvector HNSW + GIN tsvector + cross-encoder rerank
- Parent-child chunking with pgvector embeddings
- Screening run, candidate score, requirement verdict ORM models
- Structured logging with request-id correlation
- Uniform error envelope for all API responses
- `ChunkRepositoryProtocol` for type-safe repository abstraction
- `test_docs_sync.py` to keep README and `.env.example` in sync with code

### Changed
- Rate limiter simplified from JWT-subject-based to IP-only keyed on X-Forwarded-For
- Removed `_HTTP_ERROR_CODES` dict in favor of simple `"HTTP_ERROR"` fallback

### Fixed
- Repository moved from `Rzq12/talentlens` to `Rzq12/TalentLens`
- Database quickstart image corrected to `pgvector/pgvector:pg16`
- README endpoint listing updated to reflect 20 actual endpoints

### Security
- LLM provider keys never returned in API responses, never logged
- Resume text treated as untrusted input throughout the pipeline
- Injection sanitization pipeline (Layer 1-2) with quarantine support

[unreleased]: https://github.com/Rzq12/TalentLens/compare/v0.1.0...HEAD
