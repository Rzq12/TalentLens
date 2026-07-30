"""Database engine, session factory, and the declarative base.

Engine construction lives here so the rest of the application depends on a
session, not on connection details. Pool sizing comes from `Settings`, never
from literals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine.

    Returns:
        A lazily constructed, cached `AsyncEngine`.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory.

    Returns:
        A cached `async_sessionmaker` bound to the engine.
    """
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


async def dispose_engine() -> None:
    """Close all pooled connections and reset the cached engine.

    Used by tests and by application shutdown so a torn-down event loop does not
    leave connections bound to it.
    """
    engine = get_engine()
    await engine.dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session.

    The session commits on clean exit and rolls back on any exception, so a
    router never has to remember to do either.

    Yields:
        An active `AsyncSession`.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_session)]
