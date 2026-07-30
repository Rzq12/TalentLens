"""Structured logging configuration.

Configures ``structlog`` once per process. Development gets coloured,
human-readable output; production gets JSON lines suitable for log aggregation
tools (Datadog, CloudWatch, GCP Logging).

Every module that needs to log should call ``get_logger(__name__)``.
"""

from __future__ import annotations

import logging
import sys
from typing import Literal, cast

import structlog


def configure_logging(
    level: str = "INFO",
    environment: Literal["development", "test", "production"] = "development",
) -> None:
    """Set up structlog and stdlib logging for the application.

    Args:
        level: Root log level name (e.g. ``"INFO"``, ``"DEBUG"``).
        environment: Controls renderer selection — JSON for production,
            pretty-print for everything else.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if environment == "production":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for the given module name.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A bound logger with the module name pre-attached.
    """
    # `structlog.get_logger` is annotated as returning Any because the concrete
    # type depends on the configured wrapper class. We pin that wrapper to
    # `stdlib.BoundLogger` in `configure_logging`, so the cast is sound.
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))
