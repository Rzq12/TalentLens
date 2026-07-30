"""FastAPI application factory.

Holds application wiring only: middleware, exception handlers, and router
registration. No business logic and no database access live here.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.exceptions import TalentLensError
from app.routers import auth, jobs, resumes

REQUEST_ID_HEADER = "X-Request-ID"


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
    """Attach CORS and the request-id middleware.

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
        """Assign or echo a correlation id and expose it on the response."""
        supplied = request.headers.get(REQUEST_ID_HEADER)
        try:
            request_id = str(uuid.UUID(supplied)) if supplied else str(uuid.uuid4())
        except ValueError:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
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
        code = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(_request_id(request), code, str(exc.detail), exc.status_code),
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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Optional configuration override, primarily for tests.

    Returns:
        A fully wired application instance.
    """
    cfg = settings or get_settings()
    app = FastAPI(
        title=cfg.app_name,
        version=cfg.version,
        summary="AI CV Screener — ingestion and identity surface.",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    _register_middleware(app, cfg)
    _register_exception_handlers(app)

    @app.get("/health", summary="Liveness probe", description="Unauthenticated.")
    async def health() -> dict[str, str]:
        """Report that the process is alive."""
        return {"status": "ok", "version": cfg.version, "environment": cfg.environment}

    app.include_router(auth.router, prefix=cfg.api_v1_prefix)
    app.include_router(resumes.router, prefix=cfg.api_v1_prefix)
    app.include_router(jobs.router, prefix=cfg.api_v1_prefix)
    return app
