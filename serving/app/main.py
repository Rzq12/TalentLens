"""FastAPI application factory.

Holds application wiring only: middleware, exception handlers, and router
registration. No business logic and no database access live here.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.db import get_sessionmaker, set_tenant_context as _set_tenant_context
from app.exceptions import TalentLensError
from app.logging import configure_logging, get_logger
from app.routers import (
    auth,
    candidates,
    demo,
    governance,
    jobs,
    resumes,
    rubric,
    screening,
    search,
)
from app.security import decode_access_token as _decode_access_token

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
FORWARDED_FOR_HEADER = "X-Forwarded-For"
MAX_ERROR_DETAIL_CHARS = 500

# --------------------------------------------------------------------------- #
# Rate limiting (in-process, per-IP sliding window)                            #
# --------------------------------------------------------------------------- #
#
# Keyed by client IP. When deployed behind a trusted reverse proxy the proxy
# is expected to set X-Forwarded-For; otherwise every request appears to come
# from the proxy and shares one bucket. In-process only — fine for a single
# worker; if you scale out, move this to the proxy or a shared store.

_RATE_LIMIT_REQUESTS = 20  # max requests per window
_RATE_LIMIT_WINDOW_SECONDS = 60  # window duration
_RATE_LIMIT_MAX_TRACKED_KEYS = 10_000  # hard ceiling on limiter memory

# Paths that are rate-limited (upload endpoints are the highest risk).
_RATE_LIMITED_PREFIXES = (
    "/api/v1/resumes",
    "/api/v1/jobs",
    "/api/v1/search",
    "/api/v1/rubrics",
)

_request_counts: dict[str, list[float]] = defaultdict(list)


def reset_rate_limiter() -> None:
    """Clear all rate-limit state.

    Exposed for tests: the limiter is process-global, so without an explicit
    reset one test's requests consume the next test's budget.
    """
    _request_counts.clear()


def _rate_limit_key(request: Request) -> str:
    """Derive the IP a rate-limit budget is charged against.

    Uses X-Forwarded-For when present (deployment behind a trusted reverse
    proxy), falling back to the direct peer address.

    Args:
        request: The incoming request.

    Returns:
        An opaque bucket key.
    """
    forwarded = request.headers.get(FORWARDED_FOR_HEADER)
    if forwarded:
        # First entry is the original client; later entries are intermediate
        # proxies. Trimming whitespace handles the common "x, y" formatting.
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return f"ip:{first}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def _is_rate_limited(key: str, now: float) -> bool:
    """Check whether `key` has exhausted its budget for the current window.

    Uses a sliding window. Stale buckets are evicted so the tracking map cannot
    grow without bound as callers or addresses churn — an unbounded map keyed
    on caller-controlled input is itself a denial-of-service vector.

    Args:
        key: Bucket identity from `_rate_limit_key`.
        now: Current monotonic timestamp.

    Returns:
        True if the caller has exceeded the limit.
    """
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS

    if len(_request_counts) > _RATE_LIMIT_MAX_TRACKED_KEYS:
        stale = [k for k, v in _request_counts.items() if not v or v[-1] <= window_start]
        for k in stale:
            del _request_counts[k]

    recent = [t for t in _request_counts[key] if t > window_start]
    if len(recent) >= _RATE_LIMIT_REQUESTS:
        _request_counts[key] = recent
        return True
    recent.append(now)
    _request_counts[key] = recent
    return False


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _error_body(request_id: str, code: str, message: str, status: int) -> dict[str, object]:
    """Build the uniform error envelope returned by every failure path.

    Args:
        request_id: Correlation id for this request.
        code: Stable machine-readable error identifier.
        message: Safe, caller-facing description.
        status: HTTP status code.

    Returns:
        The envelope as a plain dict, ready for `JSONResponse`.
    """
    return {
        "request_id": request_id,
        "error": code,
        "message": message,
        "status_code": status,
    }


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    """Attach CORS, request-id, logging, and rate-limiting middleware.

    Args:
        app: The application being configured.
        settings: Resolved runtime configuration.
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[JSONResponse]],
    ) -> JSONResponse:
        """Assign or echo a correlation id, log the request, and rate-limit."""
        # --- Request ID ---
        supplied = request.headers.get(REQUEST_ID_HEADER)
        try:
            request_id = str(uuid.UUID(supplied)) if supplied else str(uuid.uuid4())
        except ValueError:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # --- RLS tenant context ---
        # Extract tenant from bearer token (best-effort — skips unauthenticated
        # endpoints like /health and /metrics).
        try:
            header = request.headers.get("Authorization", "")
            scheme, _, token = header.partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                principal = _decode_access_token(token.strip())
                _set_tenant_context(principal.tenant_id)
        except Exception:
            pass  # /health, /metrics, auth errors — RLS stays unset

        # --- Rate limiting ---
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _RATE_LIMITED_PREFIXES):
            bucket = _rate_limit_key(request)
            if _is_rate_limited(bucket, time.monotonic()):
                logger.warning(
                    "rate_limited",
                    bucket=bucket,
                    path=path,
                    request_id=request_id,
                )
                return JSONResponse(
                    status_code=429,
                    content=_error_body(
                        request_id,
                        "RATE_LIMITED",
                        "Too many requests. Please try again later.",
                        429,
                    ),
                    headers={REQUEST_ID_HEADER: request_id},
                )

        # --- Execute request and log ---
        start = time.monotonic()
        response = await call_next(request)
        latency_ms = round((time.monotonic() - start) * 1000, 1)

        response.headers[REQUEST_ID_HEADER] = request_id

        logger.info(
            "http_request",
            method=request.method,
            path=path,
            status_code=response.status_code,
            latency_ms=latency_ms,
            request_id=request_id,
        )
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    """Attach global handlers so every error shares one envelope shape.

    Args:
        app: The application being configured.
    """

    def _request_id(request: Request) -> str:
        return str(getattr(request.state, "request_id", uuid.uuid4()))

    @app.exception_handler(TalentLensError)
    async def handle_domain_error(request: Request, exc: TalentLensError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(
                _request_id(request), exc.error_code, exc.message, exc.status_code
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "HTTP_ERROR"
        # Never echo `exc.detail` for server-side faults: library-raised
        # HTTPExceptions can carry internal paths, driver messages, or query
        # fragments. Client errors carry safe, caller-oriented text.
        if exc.status_code >= 500:
            message = "An unexpected error occurred."
            logger.error(
                "http_server_error",
                request_id=_request_id(request),
                status_code=exc.status_code,
                detail=str(exc.detail)[:500],
            )
        else:
            message = str(exc.detail)[:500]
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(_request_id(request), code, message, exc.status_code),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body(
                _request_id(request),
                "VALIDATION_FAILED",
                "The request payload failed validation.",
                422,
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all: log full details server-side, return safe envelope.

        This prevents stack traces, file paths, SQL fragments, and library
        internals from leaking to the caller.
        """
        request_id = _request_id(request)
        logger.exception(
            "unhandled_error",
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content=_error_body(
                request_id,
                "INTERNAL_ERROR",
                "An unexpected error occurred.",
                500,
            ),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional configuration override, primarily for tests.

    Returns:
        A fully wired application instance.
    """
    cfg = settings or get_settings()

    configure_logging(level=cfg.log_level, environment=cfg.environment)

    # The full API surface — every route, schema, and field name — is a useful
    # map for an attacker. Publish it everywhere except production.
    expose_docs = cfg.environment != "production"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Fail fast on schema/config drift before the app accepts traffic.

        ``verify_embedding_dimensions`` raises when a pgvector column width
        disagrees with ``Settings.embedding_dim`` — a mismatch that otherwise
        only surfaces as a pgvector error on the first insert, killing the
        ingest pipeline in a deployment that looked healthy. A database that
        is unreachable at boot logs a warning instead of crashing: liveness
        must not depend on the database being up at process start.
        """
        try:
            await verify_embedding_dimensions()
        except RuntimeError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "embedding_dimension_check_skipped",
                reason=type(exc).__name__,
                detail=str(exc),
            )
        yield

    app = FastAPI(
        title=cfg.app_name,
        version=cfg.version,
        summary="AI CV Screener — ingestion and identity surface.",
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
        lifespan=lifespan,
    )

    _register_middleware(app, cfg)
    _register_exception_handlers(app)

    @app.get("/health", summary="Liveness probe", description="Unauthenticated.")
    async def health() -> dict[str, str]:
        """Report that the process is alive."""
        return {"status": "ok", "version": cfg.version}

    @app.get("/metrics", summary="Prometheus metrics", description="Unauthenticated.")
    async def metrics() -> Response:
        """Expose Prometheus metrics in text format."""
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    # Set app info from config (non-request-scoped, called once at startup)
    try:
        from app.metrics import app_info  # noqa: F811

        app_info.info({"version": cfg.version, "environment": cfg.environment})
    except ImportError:
        pass  # prometheus_client not installed — metrics disabled

    app.include_router(auth.router, prefix=cfg.api_v1_prefix)
    app.include_router(resumes.router, prefix=cfg.api_v1_prefix)
    app.include_router(jobs.router, prefix=cfg.api_v1_prefix)
    app.include_router(rubric.router, prefix=cfg.api_v1_prefix)
    app.include_router(search.router, prefix=cfg.api_v1_prefix)
    app.include_router(screening.router, prefix=cfg.api_v1_prefix)
    app.include_router(candidates.router, prefix=cfg.api_v1_prefix)
    app.include_router(governance.router, prefix=cfg.api_v1_prefix)
    app.include_router(demo.router, prefix=cfg.api_v1_prefix)

    # === Agent startup: register all agents on boot ===
    from app.agents.ats_scoring import AtsScoringAgent
    from app.agents.bias_detection import BiasAgent
    from app.agents.cv_parser import CvParserAgent
    from app.agents.education_analyzer import EducationAnalyzerAgent
    from app.agents.experience_analyzer import ExperienceAnalyzerAgent
    from app.agents.factory import build_agent_factories
    from app.agents.fraud_detection import FraudAgent
    from app.agents.interview import InterviewAgent
    from app.agents.ocr_agent import OcrAgent
    from app.agents.recommendation import RecommendAgent
    from app.agents.semantic_matching import SemanticMatchingAgent
    from app.agents.skill_extraction import SkillExtractionAgent
    from app.agents.skill_gap import SkillGapAgent
    from app.routers.screening import get_registry

    factories = build_agent_factories(cfg)
    registry = get_registry()
    for agent_cls in (
        OcrAgent,
        CvParserAgent,
        SkillExtractionAgent,
        ExperienceAnalyzerAgent,
        EducationAnalyzerAgent,
        AtsScoringAgent,
        SemanticMatchingAgent,
        SkillGapAgent,
        InterviewAgent,
        BiasAgent,
        FraudAgent,
        RecommendAgent,
    ):
        registry.register(agent_cls, factories[agent_cls.name])

    return app


_VECTOR_TYPE_RE = re.compile(r"^(?:vector|halfvec)\((\d+)\)$")
_EMBEDDING_COLUMNS: dict[str, str] = {
    # table -> column, mirrors models.EMBEDDING_DIM usage.
    "resume_chunks": "embedding",
    "requirements": "embedding",
}


async def verify_embedding_dimensions() -> None:
    """Fail fast at startup when a pgvector column width disagrees with config.

    A mismatch otherwise surfaces only as a pgvector "expected N dimensions,
    not M" error on the first insert — killing the entire ingest pipeline in
    a deployment that appeared healthy. Reads the column types directly from
    the catalog so this works for both ``vector`` and ``halfvec`` columns.
    """
    from app.models import EMBEDDING_DIM

    async with get_sessionmaker()() as session:
        for table, column in _EMBEDDING_COLUMNS.items():
            col_type = (
                await session.execute(
                    text(
                        """
                        SELECT format_type(a.atttypid, a.atttypmod)
                        FROM pg_attribute a
                        JOIN pg_class c ON c.oid = a.attrelid
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relname = :table
                          AND a.attname = :column
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                          AND n.nspname = ANY (current_schemas(false))
                        """
                    ),
                    {"table": table, "column": column},
                )
            ).scalar_one_or_none()

            if col_type is None:
                # Table not migrated yet — the migrations own that failure
                # mode; don't duplicate it here.
                logger.warning(
                    "embedding_column_not_found",
                    table=table,
                    column=column,
                )
                continue

            match = _VECTOR_TYPE_RE.match(col_type)
            if match is None:
                logger.error(
                    "embedding_column_type_unexpected",
                    table=table,
                    column=column,
                    column_type=col_type,
                    expected_dim=EMBEDDING_DIM,
                )
                continue

            db_dim = int(match.group(1))
            if db_dim != EMBEDDING_DIM:
                raise RuntimeError(
                    f"Embedding dimension mismatch: {table}.{column} is "
                    f"{col_type} but Settings.embedding_dim is {EMBEDDING_DIM}. "
                    "Align the migrations, models.EMBEDDING_DIM, and "
                    "EMBEDDING_DIM config before serving."
                )
            logger.info(
                "embedding_dimension_verified",
                table=table,
                column=column,
                dim=db_dim,
            )
